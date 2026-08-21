"""Authorized reconstruction of retrieved image and temporal video chunks."""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import shutil
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass

import fitz

from open_webui.models.files import Files
from open_webui.retrieval.utils import AuthorizedAttachmentScope
from open_webui.storage.provider import Storage


log = logging.getLogger(__name__)

MAX_RECONSTRUCTED_VISUALS = 4
MAX_RECONSTRUCTED_VIDEO_SEGMENTS = 4
VIDEO_FRAMES_PER_SEGMENT = 2
VIDEO_FRAME_MAX_DIMENSION = 1024
VIDEO_FRAME_MAX_BYTES = 2 * 1024 * 1024
VIDEO_FRAME_EXTRACTION_TIMEOUT_SECONDS = 15
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"

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
    "chunkIndex",
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
class _VisualCandidate:
    metadata: dict
    distance: float | None
    source_index: int
    row_index: int


def reconstruct_and_sanitize_sources(
    sources: list[dict],
    *,
    authorized_scope: AuthorizedAttachmentScope,
    vision_enabled: bool,
    limit: int = MAX_RECONSTRUCTED_VISUALS,
) -> tuple[list[dict], list[dict]]:
    """Reconstruct authorized visual hits and return frontend-safe sources.

    Authorization is inherited only from the canonical server-validated scope:
    a hit must belong to an attached file or attached knowledge collection.
    Images and selected video frames are attached transiently to the answer-model
    request. Storage paths, crop geometry, hashes, recipes, and Base64 are never
    returned in the sanitized citation metadata.
    """
    direct_file_ids = set(authorized_scope.file_ids)
    knowledge_ids = set(authorized_scope.knowledge_ids)
    image_candidates_by_id: dict[str, _VisualCandidate] = {}
    video_candidates_by_id: dict[tuple[str, str, str, str], _VisualCandidate] = {}
    if vision_enabled:
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
                if modality == "image":
                    visual_id = str(metadata.get("visual_asset_id") or "")
                    if not visual_id:
                        continue
                    current = image_candidates_by_id.get(visual_id)
                    if current is None or _candidate_rank_key(
                        candidate
                    ) < _candidate_rank_key(current):
                        image_candidates_by_id[visual_id] = candidate
                elif modality == "video":
                    segment_id = _video_segment_id(metadata)
                    if segment_id is None:
                        continue
                    current = video_candidates_by_id.get(segment_id)
                    if current is None or _candidate_rank_key(
                        candidate
                    ) < _candidate_rank_key(current):
                        video_candidates_by_id[segment_id] = candidate

    selection_limit = max(0, int(limit))
    selected_image_candidates = sorted(
        image_candidates_by_id.values(), key=_candidate_rank_key
    )[:selection_limit]
    selected_video_candidates = sorted(
        video_candidates_by_id.values(), key=_candidate_rank_key
    )[: min(selection_limit, MAX_RECONSTRUCTED_VIDEO_SEGMENTS)]

    reconstructed_images = _reconstruct_candidates(
        [candidate.metadata for candidate in selected_image_candidates]
    )
    reconstructed_video_segments = _reconstruct_video_candidates(
        [candidate.metadata for candidate in selected_video_candidates]
    )
    reconstructed_image_ids = {
        visual.visual_asset_id for visual in reconstructed_images
    }
    reconstructed_video_ids = {
        segment.segment_id for segment in reconstructed_video_segments
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
    sanitized_sources = _sanitize_sources(
        sources,
        direct_file_ids=direct_file_ids,
        knowledge_ids=knowledge_ids,
        selected_visual_positions=selected_image_positions,
        selected_video_positions=selected_video_positions,
    )
    content_parts = [visual.image_url_part() for visual in reconstructed_images]
    for segment in reconstructed_video_segments:
        content_parts.extend(segment.message_parts())
    return content_parts, sanitized_sources


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
    )


def _sanitize_sources(
    sources: list[dict],
    *,
    direct_file_ids: set[str],
    knowledge_ids: set[str],
    selected_visual_positions: set[tuple[int, int]],
    selected_video_positions: set[tuple[int, int]],
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
            elif is_video:
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                safe_document = (
                    _video_context_text(metadata)
                    if (source_index, row_index) in selected_video_positions
                    else ""
                )
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


def _reconstruct_candidates(candidates: list[dict]) -> list[ReconstructedVisual]:
    grouped: dict[str, list[dict]] = {}
    for metadata in candidates:
        grouped.setdefault(str(metadata.get("file_id")), []).append(metadata)

    output: dict[str, ReconstructedVisual] = {}
    with ExitStack() as stack:
        for file_id, group in grouped.items():
            stored_source = _load_stored_source(file_id)
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
                continue

            if all(item.get("content_kind") == "standalone_image" for item in group):
                for metadata in group:
                    visual = _reconstruct_standalone(file_id, source_bytes, metadata)
                    if visual is not None:
                        output[visual.visual_asset_id] = visual
                continue

            try:
                pdf = stack.enter_context(
                    fitz.open(stream=source_bytes, filetype="pdf")
                )
            except Exception:
                continue
            for metadata in group:
                visual = _reconstruct_pdf_crop(file_id, pdf, metadata)
                if visual is not None:
                    output[visual.visual_asset_id] = visual

    # Preserve dense-hit order across parent-file grouping.
    return [
        output[visual_id]
        for visual_id in (str(item.get("visual_asset_id")) for item in candidates)
        if visual_id in output
    ]


def _reconstruct_video_candidates(
    candidates: list[dict],
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
    for file_id, group in grouped.items():
        stored_source = _load_stored_source(file_id)
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
            continue

        for metadata in group:
            segment = _reconstruct_video_segment(
                ffmpeg=ffmpeg,
                path=path,
                file_id=file_id,
                source_hash=source_hash,
                metadata=metadata,
            )
            if segment is not None:
                output[segment.segment_id] = segment

    return [
        output[segment_id]
        for segment_id in (_video_segment_id(item) for item in candidates)
        if segment_id in output
    ]


def _load_stored_source(file_id: str) -> tuple[str, bytes] | None:
    if not file_id:
        return None
    try:
        file = Files.get_file_by_id(file_id)
    except Exception:
        log.warning("Visual source lookup failed")
        return None
    if file is None or not file.path:
        return None
    try:
        path = Storage.get_file(file.path)
    except Exception:
        log.warning("Visual source storage read failed")
        return None
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as source_handle:
            return path, source_handle.read()
    except OSError:
        return None


def _reconstruct_video_segment(
    *,
    ffmpeg: str,
    path: str,
    file_id: str,
    source_hash: str,
    metadata: dict,
) -> ReconstructedVideoSegment | None:
    segment_id = _video_segment_id(metadata)
    timing = _video_segment_timing(metadata)
    if (
        segment_id is None
        or timing is None
        or metadata.get("content_kind") != "video_temporal"
        or metadata.get("mime_type") not in {"video/mp4", "video/mpeg"}
    ):
        return None

    start_seconds, end_seconds = timing
    frames = []
    for frame_index, timestamp in enumerate(
        _sample_video_timestamps(start_seconds, end_seconds)
    ):
        frame_data = _extract_video_frame(ffmpeg, path, timestamp)
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
    chunk_index = metadata.get("chunk_index", metadata.get("chunkIndex", ""))
    return (
        file_id,
        str(chunk_index),
        f"{start_seconds:.6f}",
        f"{end_seconds:.6f}",
    )


def _video_segment_timing(metadata: dict) -> tuple[float, float] | None:
    try:
        start_seconds = float(metadata["startTimeSeconds"])
        end_seconds = float(metadata["endTimeSeconds"])
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
    ffmpeg: str, path: str, timestamp_seconds: float
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
            timeout=VIDEO_FRAME_EXTRACTION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
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


def _safe_source_name(metadata: dict) -> str:
    raw_name = str(metadata.get("name") or metadata.get("source") or "attached video")
    name = " ".join(raw_name.split())[:200]
    return name or "attached video"


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
    "MAX_RECONSTRUCTED_VISUALS",
    "MAX_RECONSTRUCTED_VIDEO_SEGMENTS",
    "ReconstructedVisual",
    "ReconstructedVideoFrame",
    "ReconstructedVideoSegment",
    "reconstruct_and_sanitize_sources",
    "sanitize_text_sources",
]
