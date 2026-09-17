"""Authorized reconstruction of retrieved image, video, and audio chunks."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
import os
import shutil
import subprocess
import time
import wave
from contextlib import ExitStack
from dataclasses import dataclass

import fitz

from open_webui.models.files import Files
from open_webui.retrieval.utils import AuthorizedAttachmentScope
from open_webui.retrieval.reconstruction import ReconstructionControl
from open_webui.storage.provider import Storage
from open_webui.retrieval.reconstruction_storage import reconstruction_source_path
from open_webui.utils.multimodal import (
    AUDIO_INPUT_FORMAT_GEMINI_DATA_URL,
    AUDIO_INPUT_FORMAT_OPENAI,
    SUPPORTED_AUDIO_INPUT_FORMATS,
)
from open_webui.utils.otel_instrumentation import add_metric_counter, add_span_event


log = logging.getLogger(__name__)

MAX_RECONSTRUCTED_VISUALS = 4
MAX_RECONSTRUCTED_VIDEO_SEGMENTS = 4
MAX_RECONSTRUCTED_AUDIO_SEGMENTS = 4
VIDEO_FRAMES_PER_SEGMENT = 2
VIDEO_FRAME_MAX_DIMENSION = 1024
VIDEO_FRAME_MAX_BYTES = 2 * 1024 * 1024
VIDEO_FRAME_EXTRACTION_TIMEOUT_SECONDS = 15
AUDIO_SEGMENT_EXTRACTION_TIMEOUT_SECONDS = 30
AUDIO_SAMPLE_RATE = 16_000
AUDIO_SAMPLE_WIDTH = 2
AUDIO_CHANNELS = 1
MAX_AUDIO_SEGMENT_DURATION_SECONDS = 120
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_RECONSTRUCTABLE_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
}
_AUDIO_VIDEO_CONTENT_KINDS = {
    "audio_temporal",
}

_PUBLIC_VISUAL_METADATA = {
    "file_id",
    "name",
    "source",
    "modality",
    "content_kind",
    "visual_asset_id",
    "page_number",
    "element_number",
    "mime_type",
    "pixel_width",
    "pixel_height",
    "startTimeSeconds",
    "endTimeSeconds",
    "segment_start_s",
    "segment_end_s",
    "chunkIndex",
    "video_segment_id",
    "duration_seconds",
}
_PUBLIC_FILE_TEXT_METADATA = {
    "file_id",
    "name",
    "source",
    "modality",
    "content_kind",
    "page",
    "page_number",
    "element_number",
    "start_index",
}
_PUBLIC_AUDIO_METADATA = {
    "file_id",
    "name",
    "source",
    "modality",
    "content_kind",
    "mime_type",
    "source_mime_type",
    "startTimeSeconds",
    "endTimeSeconds",
    "segment_start_s",
    "segment_end_s",
    "chunkIndex",
    "video_segment_id",
    "duration_seconds",
}


@dataclass(frozen=True)
class ReconstructedVisual:
    visual_asset_id: str
    file_id: str
    mime_type: str
    data: bytes

    def image_url_part(self) -> dict:
        encoded = base64.b64encode(self.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.mime_type};base64,{encoded}"},
        }


@dataclass(frozen=True)
class ReconstructedVideoFrame:
    frame_id: str
    file_id: str
    timestamp_seconds: float
    mime_type: str
    data: bytes

    def image_url_part(self) -> dict:
        encoded = base64.b64encode(self.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.mime_type};base64,{encoded}"},
        }


@dataclass(frozen=True)
class ReconstructedVideoSegment:
    segment_id: tuple[str, str, str, str]
    file_id: str
    source_name: str
    start_seconds: float
    end_seconds: float
    frames: tuple[ReconstructedVideoFrame, ...]

    def message_parts(self) -> list[dict]:
        parts = [
            {
                "type": "text",
                "text": (
                    f'Retrieved video evidence from "{self.source_name}", '
                    f"segment {_format_timestamp(self.start_seconds)}–"
                    f"{_format_timestamp(self.end_seconds)}. "
                    "The following frames are ordered chronologically."
                ),
            }
        ]
        for frame in self.frames:
            parts.extend(
                [
                    {
                        "type": "text",
                        "text": (
                            "Video frame at "
                            f"{_format_timestamp(frame.timestamp_seconds)}:"
                        ),
                    },
                    frame.image_url_part(),
                ]
            )
        return parts


@dataclass(frozen=True)
class ReconstructedAudioSegment:
    segment_id: tuple[str, str, str, str]
    file_id: str
    source_name: str
    start_seconds: float
    end_seconds: float
    data: bytes

    def message_parts(self, audio_input_format: str) -> list[dict]:
        encoded = base64.b64encode(self.data).decode("ascii")
        if audio_input_format == AUDIO_INPUT_FORMAT_GEMINI_DATA_URL:
            audio_part = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:audio/wav;base64,{encoded}",
                },
            }
        elif audio_input_format == AUDIO_INPUT_FORMAT_OPENAI:
            audio_part = {
                "type": "input_audio",
                "input_audio": {
                    "data": encoded,
                    "format": "wav",
                },
            }
        else:
            return []
        return [
            {
                "type": "text",
                "text": (
                    f'Retrieved audio evidence from "{self.source_name}", '
                    f"{_format_timestamp(self.start_seconds)}–"
                    f"{_format_timestamp(self.end_seconds)}."
                ),
            },
            audio_part,
        ]


@dataclass(frozen=True)
class _VisualCandidate:
    metadata: dict
    distance: float | None
    source_index: int
    row_index: int


@dataclass(frozen=True)
class ReconstructionResult:
    content_parts: list[dict]
    sources: list[dict]
    unavailable_evidence: list[dict]
    timed_out: bool = False

    @property
    def has_usable_evidence(self) -> bool:
        return bool(self.content_parts) or any(
            isinstance(document, str) and document.strip()
            for source in self.sources
            for document in source.get("document", [])
        )

    def __iter__(self):
        # Keep the existing internal two-value unpacking contract additive.
        yield self.content_parts
        yield self.sources


def is_reconstructable_video_metadata(metadata: dict) -> bool:
    """Return whether one authorized hit can ground reconstructed video frames."""
    if not isinstance(metadata, dict):
        return False

    modality = metadata.get("modality")
    content_kind = metadata.get("content_kind")
    if modality == "video":
        if content_kind != "video_temporal":
            return False
    elif modality == "audio":
        if not is_reconstructable_audio_metadata(metadata):
            return False
    else:
        return False

    return (
        _source_video_mime_type(metadata) in _RECONSTRUCTABLE_VIDEO_MIME_TYPES
        and _video_segment_id(metadata) is not None
    )


def is_reconstructable_audio_metadata(metadata: dict) -> bool:
    """Return whether an authorized dense hit can reconstruct raw audio."""

    if not isinstance(metadata, dict):
        return False
    return bool(
        metadata.get("modality") == "audio"
        and metadata.get("content_kind") in _AUDIO_VIDEO_CONTENT_KINDS
        and metadata.get("mime_type") == "audio/wav"
        and metadata.get("source_mime_type") in _RECONSTRUCTABLE_VIDEO_MIME_TYPES
        and _video_segment_id(metadata) is not None
    )


def _source_video_mime_type(metadata: dict) -> str:
    if metadata.get("modality") == "audio":
        return str(metadata.get("source_mime_type") or "")
    return str(metadata.get("mime_type") or "")


def reconstruct_and_sanitize_sources(
    sources: list[dict],
    *,
    authorized_scope: AuthorizedAttachmentScope,
    vision_enabled: bool,
    audio_input_format: str | None,
    limit: int = MAX_RECONSTRUCTED_VISUALS,
    audio_limit: int = MAX_RECONSTRUCTED_AUDIO_SEGMENTS,
    control: ReconstructionControl | None = None,
) -> ReconstructionResult:
    """Reconstruct authorized media hits and return frontend-safe sources.

    Authorization is inherited only from the canonical server-validated scope:
    a hit must belong to an attached file or attached knowledge collection.
    Images, selected video frames, and supported audio segments are attached
    transiently to the answer-model request. Storage paths, crop geometry,
    hashes, recipes, and Base64 are never returned in citation metadata.
    """
    if control is None:
        with ExitStack() as resources:
            return reconstruct_and_sanitize_sources(
                sources,
                authorized_scope=authorized_scope,
                vision_enabled=vision_enabled,
                audio_input_format=audio_input_format,
                limit=limit,
                audio_limit=audio_limit,
                control=ReconstructionControl(
                    time.monotonic() + 30, resources=resources
                ),
            )
    direct_file_ids = set(authorized_scope.file_ids)
    knowledge_ids = set(authorized_scope.knowledge_ids)
    audio_enabled = audio_input_format in SUPPORTED_AUDIO_INPUT_FORMATS
    image_candidates_by_id: dict[str, _VisualCandidate] = {}
    video_candidates_by_id: dict[tuple[str, str, str, str], _VisualCandidate] = {}
    audio_candidates_by_id: dict[tuple[str, str, str, str], _VisualCandidate] = {}
    if vision_enabled or audio_enabled:
        for source_index, source in enumerate(sources or []):
            if not isinstance(source, dict):
                continue
            metadatas = source.get("metadata") or []
            distances = source.get("distances") or []
            if not isinstance(metadatas, list):
                continue
            for row_index, metadata in enumerate(metadatas):
                if not isinstance(metadata, dict):
                    continue
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                distance = _dense_distance(
                    distances[row_index]
                    if isinstance(distances, list) and row_index < len(distances)
                    else None
                )
                candidate = _VisualCandidate(
                    metadata=dict(metadata),
                    distance=distance,
                    source_index=source_index,
                    row_index=row_index,
                )
                modality = metadata.get("modality")
                if vision_enabled and modality == "image":
                    visual_id = str(metadata.get("visual_asset_id") or "")
                    if not visual_id:
                        continue
                    current = image_candidates_by_id.get(visual_id)
                    if current is None or _candidate_rank_key(
                        candidate
                    ) < _candidate_rank_key(current):
                        image_candidates_by_id[visual_id] = candidate
                if vision_enabled and is_reconstructable_video_metadata(metadata):
                    segment_id = _video_segment_id(metadata)
                    if segment_id is None:
                        continue
                    current = video_candidates_by_id.get(segment_id)
                    if current is None or _candidate_rank_key(
                        candidate
                    ) < _candidate_rank_key(current):
                        video_candidates_by_id[segment_id] = candidate
                if audio_enabled and is_reconstructable_audio_metadata(metadata):
                    segment_id = _video_segment_id(metadata)
                    if segment_id is None:
                        continue
                    current = audio_candidates_by_id.get(segment_id)
                    if current is None or _candidate_rank_key(
                        candidate
                    ) < _candidate_rank_key(current):
                        audio_candidates_by_id[segment_id] = candidate

    selection_limit = max(0, int(limit))
    selected_image_candidates = sorted(
        image_candidates_by_id.values(), key=_candidate_rank_key
    )[:selection_limit]
    selected_video_candidates = sorted(
        video_candidates_by_id.values(), key=_candidate_rank_key
    )[: min(selection_limit, MAX_RECONSTRUCTED_VIDEO_SEGMENTS)]
    selected_audio_candidates = sorted(
        audio_candidates_by_id.values(), key=_candidate_rank_key
    )[: min(selection_limit, max(0, int(audio_limit)))]

    reconstructed_images = []
    reconstructed_video_segments = []
    reconstructed_audio_segments = []

    def checkpoint():
        # Publish immutable snapshots so a late audio read cannot discard frames.
        control.partial_result = _reconstruction_result(
            sources,
            authorized_scope=authorized_scope,
            vision_enabled=vision_enabled,
            audio_input_format=audio_input_format,
            selected_candidates=(
                selected_image_candidates,
                selected_video_candidates,
                selected_audio_candidates,
            ),
            reconstructed=(
                reconstructed_images,
                reconstructed_video_segments,
                reconstructed_audio_segments,
            ),
            control=control,
        )
        return control.partial_result

    def images_ready(items):
        nonlocal reconstructed_images
        reconstructed_images = items
        checkpoint()

    def video_ready(items):
        nonlocal reconstructed_video_segments
        reconstructed_video_segments = items
        checkpoint()

    def audio_ready(items):
        nonlocal reconstructed_audio_segments
        reconstructed_audio_segments = items
        checkpoint()

    checkpoint()
    reconstructed_images = _reconstruct_candidates(
        [candidate.metadata for candidate in selected_image_candidates],
        control=control,
        on_progress=images_ready,
    )
    checkpoint()
    reconstructed_video_segments = _reconstruct_video_candidates(
        [candidate.metadata for candidate in selected_video_candidates],
        control=control,
        on_progress=video_ready,
    )
    checkpoint()
    reconstructed_audio_segments = _reconstruct_audio_candidates(
        [candidate.metadata for candidate in selected_audio_candidates],
        control=control,
        on_progress=audio_ready,
    )
    return checkpoint()


def _reconstruction_result(
    sources: list[dict],
    *,
    authorized_scope: AuthorizedAttachmentScope,
    vision_enabled: bool,
    audio_input_format: str | None,
    selected_candidates: tuple,
    reconstructed: tuple,
    control: ReconstructionControl,
) -> ReconstructionResult:
    selected_image_candidates, selected_video_candidates, selected_audio_candidates = (
        selected_candidates
    )
    reconstructed_images, reconstructed_video_segments, reconstructed_audio_segments = (
        reconstructed
    )
    direct_file_ids = set(authorized_scope.file_ids)
    knowledge_ids = set(authorized_scope.knowledge_ids)
    audio_enabled = audio_input_format in SUPPORTED_AUDIO_INPUT_FORMATS
    reconstructed_image_ids = {
        visual.visual_asset_id for visual in reconstructed_images
    }
    reconstructed_video_ids = {
        segment.segment_id for segment in reconstructed_video_segments
    }
    reconstructed_audio_ids = {
        segment.segment_id for segment in reconstructed_audio_segments
    }
    selected_image_positions = {
        (candidate.source_index, candidate.row_index)
        for candidate in selected_image_candidates
        if str(candidate.metadata.get("visual_asset_id") or "")
        in reconstructed_image_ids
    }
    selected_video_positions = {
        (candidate.source_index, candidate.row_index)
        for candidate in selected_video_candidates
        if _video_segment_id(candidate.metadata) in reconstructed_video_ids
    }
    selected_audio_positions = {
        (candidate.source_index, candidate.row_index)
        for candidate in selected_audio_candidates
        if _video_segment_id(candidate.metadata) in reconstructed_audio_ids
    }
    sanitized_sources = _sanitize_sources(
        sources,
        direct_file_ids=direct_file_ids,
        knowledge_ids=knowledge_ids,
        selected_visual_positions=selected_image_positions,
        selected_video_positions=selected_video_positions,
        selected_audio_positions=selected_audio_positions,
    )
    content_parts = [visual.image_url_part() for visual in reconstructed_images]
    for segment in reconstructed_video_segments:
        content_parts.extend(segment.message_parts())
    if audio_enabled and audio_input_format is not None:
        for segment in reconstructed_audio_segments:
            content_parts.extend(segment.message_parts(audio_input_format))
    unavailable = []
    selected_positions = {
        (candidate.source_index, candidate.row_index)
        for candidate in (
            selected_image_candidates
            + selected_video_candidates
            + selected_audio_candidates
        )
    }
    for source_index, source in enumerate(sources or []):
        if not isinstance(source, dict):
            continue
        for row_index, metadata in enumerate(source.get("metadata") or []):
            if not isinstance(metadata, dict) or not _metadata_is_authorized(
                metadata, direct_file_ids, knowledge_ids
            ):
                continue
            modality = metadata.get("modality")
            if modality not in {"image", "video", "audio"}:
                continue
            position = (source_index, row_index)
            supplied = (
                position in selected_audio_positions
                if modality == "audio"
                else position in selected_image_positions
                or position in selected_video_positions
            )
            if supplied:
                continue
            supported = audio_enabled if modality == "audio" else vision_enabled
            if not supported:
                reason = "answer_model_unsupported"
            elif str(metadata.get("file_id")) in control.source_changed:
                reason = "source_changed"
            elif control.stopped:
                reason = "reconstruction_timeout"
            elif position in selected_positions or not selected_positions:
                reason = "media_reconstruction_failed"
            else:
                reason = "evidence_limit"
            item = {
                "file_id": str(metadata.get("file_id") or ""),
                "name": _safe_source_name(metadata),
                "modality": modality,
                "reason": reason,
            }
            if item not in unavailable:
                unavailable.append(item)
    return ReconstructionResult(
        content_parts, sanitized_sources, unavailable, control.stopped
    )


def sanitize_text_sources(
    sources: list[dict], *, authorized_scope: AuthorizedAttachmentScope
) -> list[dict]:
    """Return safe text citations without performing visual reconstruction."""
    direct_file_ids = set(authorized_scope.file_ids)
    knowledge_ids = set(authorized_scope.knowledge_ids)
    return _sanitize_sources(
        sources,
        direct_file_ids=direct_file_ids,
        knowledge_ids=knowledge_ids,
        selected_visual_positions=set(),
        selected_video_positions=set(),
        selected_audio_positions=set(),
    )


def _sanitize_sources(
    sources: list[dict],
    *,
    direct_file_ids: set[str],
    knowledge_ids: set[str],
    selected_visual_positions: set[tuple[int, int]],
    selected_video_positions: set[tuple[int, int]],
    selected_audio_positions: set[tuple[int, int]],
) -> list[dict]:
    sanitized_sources: list[dict] = []
    for source_index, source in enumerate(sources or []):
        if not isinstance(source, dict):
            continue
        documents = source.get("document") or []
        metadatas = source.get("metadata") or []
        distances = source.get("distances") or []
        if not isinstance(documents, list) or not isinstance(metadatas, list):
            continue

        safe_documents: list[str] = []
        safe_metadatas: list[dict] = []
        safe_distances: list[object] = []
        kept_file_backed_row = False
        for row_index, metadata in enumerate(metadatas):
            metadata = metadata if isinstance(metadata, dict) else {}
            document = documents[row_index] if row_index < len(documents) else ""
            modality = metadata.get("modality")
            is_image = modality == "image"
            is_video = modality == "video"
            is_audio = modality == "audio"
            if is_image:
                if (source_index, row_index) not in selected_visual_positions:
                    continue
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                safe_document = ""
                safe_metadata = _sanitize_visual_metadata(metadata)
                kept_file_backed_row = True
            elif is_audio:
                if not is_reconstructable_audio_metadata(metadata):
                    continue
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                position = (source_index, row_index)
                if position in selected_audio_positions:
                    safe_document = _audio_context_text(metadata, attached=True)
                elif position in selected_video_positions:
                    safe_document = _video_context_text(metadata)
                else:
                    # A timestamp alone is not audio evidence.
                    continue
                safe_metadata = _sanitize_audio_metadata(metadata)
                kept_file_backed_row = True
            elif is_video:
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                if (source_index, row_index) not in selected_video_positions:
                    continue
                safe_document = _video_context_text(metadata)
                safe_metadata = _sanitize_visual_metadata(metadata)
                kept_file_backed_row = True
            else:
                if not isinstance(document, str) or not document.strip():
                    continue
                safe_document = document
                file_backed = _is_file_backed_metadata(metadata)
                if file_backed and not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                safe_metadata = _sanitize_text_metadata(
                    metadata, file_backed=file_backed
                )
                kept_file_backed_row = kept_file_backed_row or file_backed

            safe_documents.append(safe_document)
            safe_metadatas.append(safe_metadata)
            if isinstance(distances, list) and distances:
                safe_distances.append(
                    distances[row_index] if row_index < len(distances) else None
                )

        if not safe_documents:
            continue
        source_descriptor = source.get("source") or {}
        descriptor_is_file_backed = (
            kept_file_backed_row
            or _descriptor_is_file_backed(
                source_descriptor, direct_file_ids, knowledge_ids
            )
        )
        if descriptor_is_file_backed:
            source_descriptor = _sanitize_source_descriptor(source_descriptor)
        elif isinstance(source_descriptor, dict):
            source_descriptor = dict(source_descriptor)
        else:
            source_descriptor = {}
        if not source_descriptor.get("name") and safe_metadatas:
            source_descriptor["name"] = safe_metadatas[0].get("name") or safe_metadatas[
                0
            ].get("source")
        safe_source = {
            "source": source_descriptor,
            "document": safe_documents,
            "metadata": safe_metadatas,
        }
        if isinstance(distances, list) and distances:
            safe_source["distances"] = safe_distances
        else:
            safe_source.pop("distances", None)
        sanitized_sources.append(safe_source)
    return sanitized_sources


def _dense_distance(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return None
    return distance if math.isfinite(distance) else None


def _candidate_rank_key(candidate: _VisualCandidate) -> tuple:
    metadata = candidate.metadata
    stable_order = (
        str(metadata.get("file_id") or ""),
        _sortable_int(metadata.get("chunk_index")),
        _sortable_int(metadata.get("page_index")),
        _sortable_int(metadata.get("page_local_sequence")),
        _sortable_int(metadata.get("source_sequence")),
        _sortable_float(metadata.get("startTimeSeconds")),
        _sortable_float(metadata.get("endTimeSeconds")),
        str(metadata.get("visual_asset_id") or ""),
        candidate.source_index,
        candidate.row_index,
    )
    if candidate.distance is None:
        return (1, 0.0, *stable_order)
    return (0, candidate.distance, *stable_order)


def _sortable_int(value) -> tuple[int, int | str]:
    if isinstance(value, bool):
        return (1, "")
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value or ""))


def _sortable_float(value) -> tuple[int, float | str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return (1, str(value or ""))
    return (0, number) if math.isfinite(number) else (1, str(value or ""))


def _metadata_is_authorized(
    metadata: dict, direct_file_ids: set[str], knowledge_ids: set[str]
) -> bool:
    file_id = str(metadata.get("file_id") or "")
    knowledge_id = str(metadata.get("knowledge_id") or "")
    return bool(
        file_id
        and (file_id in direct_file_ids or (knowledge_id and knowledge_id in knowledge_ids))
    )


def _reconstruct_candidates(
    candidates: list[dict], *, control: ReconstructionControl, on_progress=None
) -> list[ReconstructedVisual]:
    grouped: dict[str, list[dict]] = {}
    for metadata in candidates:
        grouped.setdefault(str(metadata.get("file_id")), []).append(metadata)

    output: dict[str, ReconstructedVisual] = {}
    with ExitStack() as stack:
        for file_id, group in grouped.items():
            if control.stopped:
                break
            stored_source = _load_stored_source(file_id, control=control)
            if stored_source is None:
                continue
            _path, source_bytes = stored_source

            source_hashes = {
                str(item.get("source_sha256") or "") for item in group
            }
            if (
                len(source_hashes) != 1
                or not _is_sha256(next(iter(source_hashes), ""))
                or not _hash_matches(source_bytes, next(iter(source_hashes)))
            ):
                control.source_changed.add(file_id)
                continue

            if all(item.get("content_kind") == "standalone_image" for item in group):
                for metadata in group:
                    if control.stopped:
                        break
                    visual = _reconstruct_standalone(file_id, source_bytes, metadata)
                    if visual is not None:
                        output[visual.visual_asset_id] = visual
                        if on_progress is not None:
                            on_progress(list(output.values()))
                continue

            try:
                pdf = stack.enter_context(
                    fitz.open(stream=source_bytes, filetype="pdf")
                )
            except Exception:
                continue
            for metadata in group:
                if control.stopped:
                    break
                visual = _reconstruct_pdf_crop(file_id, pdf, metadata)
                if visual is not None:
                    output[visual.visual_asset_id] = visual
                    if on_progress is not None:
                        on_progress(list(output.values()))

    # Preserve dense-hit order across parent-file grouping.
    return [
        output[visual_id]
        for visual_id in (str(item.get("visual_asset_id")) for item in candidates)
        if visual_id in output
    ]


def _reconstruct_video_candidates(
    candidates: list[dict],
    *,
    control: ReconstructionControl,
    on_progress=None,
) -> list[ReconstructedVideoSegment]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if candidates:
            log.warning(
                "Video frame reconstruction skipped because FFmpeg is unavailable"
            )
        return []

    grouped: dict[str, list[dict]] = {}
    for metadata in candidates:
        grouped.setdefault(str(metadata.get("file_id") or ""), []).append(metadata)

    output: dict[tuple[str, str, str, str], ReconstructedVideoSegment] = {}

    def record_segment(segment):
        output[segment.segment_id] = segment
        if on_progress is not None:
            on_progress(list(output.values()))

    for file_id, group in grouped.items():
        if control.stopped:
            break
        stored_source = _load_stored_source(file_id, control=control)
        if stored_source is None:
            continue
        path, source_bytes = stored_source

        source_hashes = {str(item.get("source_sha256") or "") for item in group}
        source_hash = next(iter(source_hashes), "")
        if (
            len(source_hashes) != 1
            or not _is_sha256(source_hash)
            or not _hash_matches(source_bytes, source_hash)
        ):
            control.source_changed.add(file_id)
            continue

        for metadata in group:
            if control.stopped:
                break
            segment = _reconstruct_video_segment(
                ffmpeg=ffmpeg,
                path=path,
                file_id=file_id,
                source_hash=source_hash,
                metadata=metadata,
                control=control,
                on_progress=record_segment,
            )
            if segment is not None:
                record_segment(segment)

    return [
        output[segment_id]
        for segment_id in (_video_segment_id(item) for item in candidates)
        if segment_id in output
    ]


def _reconstruct_audio_candidates(
    candidates: list[dict],
    *,
    control: ReconstructionControl,
    on_progress=None,
) -> list[ReconstructedAudioSegment]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if candidates:
            log.warning(
                "Retrieved audio reconstruction skipped because FFmpeg is unavailable"
            )
            add_metric_counter(
                "retrieval.video.audio_fallback_visual_only",
                {"stage": "retrieval"},
            )
        return []

    grouped: dict[str, list[dict]] = {}
    for metadata in candidates:
        grouped.setdefault(str(metadata.get("file_id") or ""), []).append(metadata)

    output: dict[tuple[str, str, str, str], ReconstructedAudioSegment] = {}
    for file_id, group in grouped.items():
        if control.stopped:
            break
        stored_source = _load_stored_source(file_id, control=control)
        if stored_source is None:
            continue
        path, source_bytes = stored_source

        source_hashes = {str(item.get("source_sha256") or "") for item in group}
        source_hash = next(iter(source_hashes), "")
        if (
            len(source_hashes) != 1
            or not _is_sha256(source_hash)
            or not _hash_matches(source_bytes, source_hash)
        ):
            control.source_changed.add(file_id)
            continue

        for metadata in group:
            if control.stopped:
                break
            segment = _reconstruct_audio_segment(
                ffmpeg=ffmpeg,
                path=path,
                file_id=file_id,
                metadata=metadata,
                control=control,
            )
            if segment is None:
                add_metric_counter(
                    "retrieval.video.audio_fallback_visual_only",
                    {"stage": "retrieval"},
                )
                add_span_event(
                    "retrieval.video.audio.reconstruction_failed",
                    {"video.segment_id": str(metadata.get("video_segment_id") or "")},
                )
                continue
            output[segment.segment_id] = segment
            add_metric_counter("retrieval.video.audio_attachments")
            if on_progress is not None:
                on_progress(list(output.values()))

    return [
        output[segment_id]
        for segment_id in (_video_segment_id(item) for item in candidates)
        if segment_id in output
    ]


def _reconstruct_audio_segment(
    *,
    ffmpeg: str,
    path: str,
    file_id: str,
    metadata: dict,
    control: ReconstructionControl,
) -> ReconstructedAudioSegment | None:
    segment_id = _video_segment_id(metadata)
    timing = _video_segment_timing(metadata)
    if (
        segment_id is None
        or timing is None
        or not is_reconstructable_audio_metadata(metadata)
    ):
        return None

    start_seconds, end_seconds = timing
    duration_seconds = end_seconds - start_seconds
    if duration_seconds > MAX_AUDIO_SEGMENT_DURATION_SECONDS:
        return None
    pcm_bytes = _extract_audio_pcm(
        ffmpeg,
        path,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
        control=control,
    )
    if pcm_bytes is None:
        return None
    return ReconstructedAudioSegment(
        segment_id=segment_id,
        file_id=file_id,
        source_name=_safe_source_name(metadata),
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        data=_build_audio_wav(pcm_bytes),
    )


def _extract_audio_pcm(
    ffmpeg: str,
    path: str,
    *,
    start_seconds: float,
    duration_seconds: float,
    control: ReconstructionControl,
) -> bytes | None:
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                path,
                "-ss",
                f"{start_seconds:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                str(AUDIO_CHANNELS),
                "-ar",
                str(AUDIO_SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=control.timeout(AUDIO_SEGMENT_EXTRACTION_TIMEOUT_SECONDS),
        )
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        return None

    pcm_bytes = result.stdout
    frame_width = AUDIO_CHANNELS * AUDIO_SAMPLE_WIDTH
    maximum_frames = math.ceil(duration_seconds * AUDIO_SAMPLE_RATE)
    maximum_bytes = maximum_frames * frame_width
    if (
        result.returncode != 0
        or not pcm_bytes
        or len(pcm_bytes) > maximum_bytes
        or len(pcm_bytes) % frame_width
    ):
        return None
    return pcm_bytes


def _build_audio_wav(pcm_bytes: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        wav_file.writeframes(pcm_bytes)
    return output.getvalue()


def _load_stored_source(
    file_id: str, *, control: ReconstructionControl
) -> tuple[str, bytes] | None:
    if not file_id or control.stopped:
        return None
    if file_id in control.source_cache:
        return control.source_cache[file_id]
    try:
        file = Files.get_file_by_id(file_id)
    except Exception:
        log.warning("Visual source lookup failed")
        return None
    if file is None or not file.path:
        return None
    if control.stopped:
        return None
    try:
        path = reconstruction_source_path(Storage, file.path, control)
    except Exception:
        log.warning("Visual source storage read failed")
        return None
    if control.stopped or not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as source_handle:
            chunks = []
            while not control.stopped:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    source = path, b"".join(chunks)
                    control.source_cache[file_id] = source
                    return source
                chunks.append(chunk)
        return None
    except OSError:
        return None


def _reconstruct_video_segment(
    *,
    ffmpeg: str,
    path: str,
    file_id: str,
    source_hash: str,
    metadata: dict,
    control: ReconstructionControl,
    on_progress=None,
) -> ReconstructedVideoSegment | None:
    segment_id = _video_segment_id(metadata)
    timing = _video_segment_timing(metadata)
    if (
        segment_id is None
        or timing is None
        or not is_reconstructable_video_metadata(metadata)
    ):
        return None

    start_seconds, end_seconds = timing
    frames = []
    for frame_index, timestamp in enumerate(
        _sample_video_timestamps(start_seconds, end_seconds)
    ):
        if control.stopped:
            break
        frame_data = _extract_video_frame(ffmpeg, path, timestamp, control=control)
        if frame_data is None:
            continue
        frame_id = hashlib.sha256(
            (
                f"video_frame_v1\0{source_hash}\0{segment_id}\0"
                f"{frame_index}\0{timestamp:.6f}"
            ).encode("utf-8")
        ).hexdigest()
        frames.append(
            ReconstructedVideoFrame(
                frame_id=frame_id,
                file_id=file_id,
                timestamp_seconds=timestamp,
                mime_type="image/jpeg",
                data=frame_data,
            )
        )
        if on_progress is not None:
            on_progress(
                ReconstructedVideoSegment(
                    segment_id=segment_id,
                    file_id=file_id,
                    source_name=_safe_source_name(metadata),
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    frames=tuple(frames),
                )
            )
    if not frames:
        return None
    return ReconstructedVideoSegment(
        segment_id=segment_id,
        file_id=file_id,
        source_name=_safe_source_name(metadata),
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        frames=tuple(frames),
    )


def _video_segment_id(metadata: dict) -> tuple[str, str, str, str] | None:
    timing = _video_segment_timing(metadata)
    file_id = str(metadata.get("file_id") or "")
    if not file_id or timing is None:
        return None
    start_seconds, end_seconds = timing
    segment_key = str(metadata.get("video_segment_id") or "").strip()
    if not segment_key:
        segment_key = str(
            metadata.get("chunkIndex", metadata.get("chunk_index", ""))
        )
    return (
        file_id,
        segment_key,
        f"{start_seconds:.6f}",
        f"{end_seconds:.6f}",
    )


def _video_segment_timing(metadata: dict) -> tuple[float, float] | None:
    try:
        start_value = metadata.get("startTimeSeconds")
        if start_value is None:
            start_value = metadata["segment_start_s"]
        end_value = metadata.get("endTimeSeconds")
        if end_value is None:
            end_value = metadata["segment_end_s"]
        start_seconds = float(start_value)
        end_seconds = float(end_value)
        duration_seconds = float(metadata["duration_seconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not all(
            math.isfinite(value)
            for value in (start_seconds, end_seconds, duration_seconds)
        )
        or start_seconds < 0
        or end_seconds <= start_seconds
        or duration_seconds <= 0
        or end_seconds > duration_seconds + 0.01
    ):
        return None
    return start_seconds, min(end_seconds, duration_seconds)


def _sample_video_timestamps(
    start_seconds: float, end_seconds: float
) -> tuple[float, ...]:
    interval = end_seconds - start_seconds
    return tuple(
        round(start_seconds + interval * index / (VIDEO_FRAMES_PER_SEGMENT + 1), 3)
        for index in range(1, VIDEO_FRAMES_PER_SEGMENT + 1)
    )


def _extract_video_frame(
    ffmpeg: str, path: str, timestamp_seconds: float, *, control: ReconstructionControl
) -> bytes | None:
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-ss",
                f"{timestamp_seconds:.3f}",
                "-i",
                path,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                (
                    f"scale={VIDEO_FRAME_MAX_DIMENSION}:"
                    f"{VIDEO_FRAME_MAX_DIMENSION}:"
                    "force_original_aspect_ratio=decrease"
                ),
                "-q:v",
                "4",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=control.timeout(VIDEO_FRAME_EXTRACTION_TIMEOUT_SECONDS),
        )
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        return None
    frame_data = result.stdout
    if (
        result.returncode != 0
        or not frame_data.startswith(_JPEG_SIGNATURE)
        or len(frame_data) > VIDEO_FRAME_MAX_BYTES
    ):
        return None
    return frame_data


def _video_context_text(metadata: dict) -> str:
    timing = _video_segment_timing(metadata)
    if timing is None:
        return ""
    start_seconds, end_seconds = timing
    return (
        f'Retrieved chronological frames from video "{_safe_source_name(metadata)}" '
        f"for segment {_format_timestamp(start_seconds)}–"
        f"{_format_timestamp(end_seconds)} are attached to the latest user message."
    )


def _audio_context_text(metadata: dict, *, attached: bool) -> str:
    if not attached:
        return ""
    timing = _video_segment_timing(metadata)
    if timing is None:
        return ""
    start_seconds, end_seconds = timing
    text = (
        f'Retrieved audio evidence from "{_safe_source_name(metadata)}", '
        f"{_format_timestamp(start_seconds)}–{_format_timestamp(end_seconds)}."
    )
    if attached:
        text += " The WAV segment is attached to the latest user message."
    return text


def _safe_source_name(metadata: dict) -> str:
    raw_name = str(metadata.get("name") or metadata.get("source") or "attached file")
    name = " ".join(raw_name.split())[:200]
    return name or "attached file"


def _format_timestamp(seconds: float) -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _reconstruct_standalone(
    file_id: str, source_bytes: bytes, metadata: dict
) -> ReconstructedVisual | None:
    mime_type = str(metadata.get("mime_type") or "")
    if mime_type == "image/png":
        valid_magic = source_bytes.startswith(_PNG_SIGNATURE)
    elif mime_type == "image/jpeg":
        valid_magic = source_bytes.startswith(_JPEG_SIGNATURE)
    else:
        return None
    if not valid_magic or not _hash_matches(
        source_bytes, str(metadata.get("image_sha256") or "")
    ):
        return None
    return ReconstructedVisual(
        visual_asset_id=str(metadata["visual_asset_id"]),
        file_id=file_id,
        mime_type=mime_type,
        data=source_bytes,
    )


def _reconstruct_pdf_crop(
    file_id: str, pdf: fitz.Document, metadata: dict
) -> ReconstructedVisual | None:
    if (
        metadata.get("mime_type") != "image/png"
        or metadata.get("output_format") != "png"
        or metadata.get("coordinate_space")
        != "rotated_cropbox_top_left_points"
        or metadata.get("alpha") is not False
    ):
        return None
    try:
        page_index = int(metadata["page_index"])
        scale = float(metadata["render_scale"])
        bbox = _valid_bbox(metadata["bbox"])
        padding_points = float(metadata.get("padding_points", 0.0))
    except (KeyError, TypeError, ValueError):
        return None
    expected_padding = {
        "pdf_figure": 0.0,
        "pdf_table": 2.0,
    }.get(metadata.get("content_kind"))
    if (
        page_index < 0
        or page_index >= len(pdf)
        or scale != 2.0
        or expected_padding is None
        or padding_points != expected_padding
    ):
        return None
    if bbox is None:
        return None

    page = pdf[page_index]
    page_bounds = _canonical_bbox(tuple(page.rect))
    render_bbox = _expand_bbox(bbox, padding_points, page_bounds)
    if render_bbox is None:
        return None
    try:
        display_rect = fitz.Rect(render_bbox)
        unrotated_rect = display_rect * page.derotation_matrix
        unrotated_bounds = fitz.Rect(page.rect) * page.derotation_matrix
        clipped_unrotated_bbox = _clip_bbox(
            tuple(unrotated_rect),
            _canonical_bbox(tuple(unrotated_bounds)),
        )
        if clipped_unrotated_bbox is None:
            return None
        pixmap = page.get_pixmap(
            clip=fitz.Rect(clipped_unrotated_bbox),
            matrix=fitz.Matrix(scale, scale),
            alpha=False,
        )
        png_bytes = pixmap.tobytes("png")
    except Exception:
        return None

    if not png_bytes.startswith(_PNG_SIGNATURE) or not _hash_matches(
        png_bytes, str(metadata.get("image_sha256") or "")
    ):
        return None
    expected_width = metadata.get("pixel_width")
    expected_height = metadata.get("pixel_height")
    try:
        if expected_width is not None and int(expected_width) != pixmap.width:
            return None
        if expected_height is not None and int(expected_height) != pixmap.height:
            return None
        visual_asset_id = str(metadata["visual_asset_id"])
    except (KeyError, TypeError, ValueError):
        return None
    return ReconstructedVisual(
        visual_asset_id=visual_asset_id,
        file_id=file_id,
        mime_type="image/png",
        data=png_bytes,
    )


def _hash_matches(data: bytes, expected: str) -> bool:
    return bool(expected) and hashlib.sha256(data).hexdigest() == expected


def _is_sha256(value: str) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_bbox(values) -> tuple[float, float, float, float] | None:
    if values is None:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return _canonical_bbox((x0, y0, x1, y1))


def _canonical_bbox(values) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = values
    return (
        round(float(x0), 6),
        round(float(y0), 6),
        round(float(x1), 6),
        round(float(y1), 6),
    )


def _clip_bbox(
    values, bounds: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    bbox = _valid_bbox(values)
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    bx0, by0, bx1, by1 = bounds
    return _valid_bbox(
        (max(x0, bx0), max(y0, by0), min(x1, bx1), min(y1, by1))
    )


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    padding: float,
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = bbox
    return _clip_bbox(
        (x0 - padding, y0 - padding, x1 + padding, y1 + padding),
        bounds,
    )


def _sanitize_visual_metadata(metadata: dict) -> dict:
    return {
        key: metadata[key]
        for key in _PUBLIC_VISUAL_METADATA
        if metadata.get(key) is not None
    }


def _sanitize_audio_metadata(metadata: dict) -> dict:
    return {
        key: metadata[key]
        for key in _PUBLIC_AUDIO_METADATA
        if metadata.get(key) is not None
    }


def _sanitize_text_metadata(metadata: dict, *, file_backed: bool) -> dict:
    if not file_backed:
        return dict(metadata)
    return {
        key: metadata[key]
        for key in _PUBLIC_FILE_TEXT_METADATA
        if metadata.get(key) is not None
    }


def _is_file_backed_metadata(metadata: dict) -> bool:
    return bool(metadata.get("file_id"))


def _descriptor_is_file_backed(
    source,
    direct_file_ids: set[str],
    knowledge_ids: set[str],
) -> bool:
    if not isinstance(source, dict) or source.get("type") == "web_search":
        return False
    identifier = str(source.get("id") or "")
    return bool(
        identifier
        and (identifier in direct_file_ids or identifier in knowledge_ids)
    )


def _sanitize_source_descriptor(source) -> dict:
    if not isinstance(source, dict):
        return {}
    public_keys = {
        "id",
        "name",
        "filename",
        "type",
        "collection_name",
        "status",
        "mime",
        "size",
    }
    return {key: source[key] for key in public_keys if source.get(key) is not None}


__all__ = [
    "MAX_RECONSTRUCTED_AUDIO_SEGMENTS",
    "MAX_RECONSTRUCTED_VISUALS",
    "MAX_RECONSTRUCTED_VIDEO_SEGMENTS",
    "ReconstructedAudioSegment",
    "ReconstructedVisual",
    "ReconstructedVideoFrame",
    "ReconstructedVideoSegment",
    "is_reconstructable_audio_metadata",
    "is_reconstructable_video_metadata",
    "reconstruct_and_sanitize_sources",
    "sanitize_text_sources",
]
