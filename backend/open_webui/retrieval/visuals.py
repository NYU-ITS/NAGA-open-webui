"""Authorized, deterministic reconstruction of retrieved image chunks."""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
from contextlib import ExitStack
from dataclasses import dataclass
import fitz

from open_webui.models.files import Files
from open_webui.retrieval.utils import AuthorizedAttachmentScope
from open_webui.storage.provider import Storage


log = logging.getLogger(__name__)

MAX_RECONSTRUCTED_VISUALS = 4
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
    """Reconstruct authorized image hits and return frontend-safe sources.

    Authorization is inherited only from the canonical server-validated scope:
    a hit must belong to an attached file or attached knowledge collection.
    Storage paths, crop geometry, hashes, recipes, and Base64 are never returned
    in the sanitized citation metadata.
    """
    direct_file_ids = set(authorized_scope.file_ids)
    knowledge_ids = set(authorized_scope.knowledge_ids)
    candidates_by_id: dict[str, _VisualCandidate] = {}
    if vision_enabled:
        for source_index, source in enumerate(sources or []):
            if not isinstance(source, dict):
                continue
            metadatas = source.get("metadata") or []
            distances = source.get("distances") or []
            if not isinstance(metadatas, list):
                continue
            for row_index, metadata in enumerate(metadatas):
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("modality") != "image"
                ):
                    continue
                if not _metadata_is_authorized(
                    metadata, direct_file_ids, knowledge_ids
                ):
                    continue
                visual_id = str(metadata.get("visual_asset_id") or "")
                if not visual_id:
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
                current = candidates_by_id.get(visual_id)
                if current is None or _candidate_rank_key(
                    candidate
                ) < _candidate_rank_key(current):
                    candidates_by_id[visual_id] = candidate

    ranked_candidates = sorted(candidates_by_id.values(), key=_candidate_rank_key)
    selected_candidates = ranked_candidates[: max(0, int(limit))]
    reconstructed = _reconstruct_candidates(
        [candidate.metadata for candidate in selected_candidates]
    )
    reconstructed_ids = {visual.visual_asset_id for visual in reconstructed}
    selected_positions = {
        (candidate.source_index, candidate.row_index)
        for candidate in selected_candidates
        if str(candidate.metadata.get("visual_asset_id") or "") in reconstructed_ids
    }
    sanitized_sources = _sanitize_sources(
        sources,
        direct_file_ids=direct_file_ids,
        knowledge_ids=knowledge_ids,
        selected_visual_positions=selected_positions,
    )
    return [visual.image_url_part() for visual in reconstructed], sanitized_sources


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
    )


def _sanitize_sources(
    sources: list[dict],
    *,
    direct_file_ids: set[str],
    knowledge_ids: set[str],
    selected_visual_positions: set[tuple[int, int]],
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
                safe_document = ""
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
            try:
                file = Files.get_file_by_id(file_id)
            except Exception:
                log.warning("Visual source lookup failed")
                continue
            if file is None or not file.path:
                continue
            try:
                path = Storage.get_file(file.path)
            except Exception:
                log.warning("Visual source storage read failed")
                continue
            if not path or not os.path.isfile(path):
                continue

            try:
                with open(path, "rb") as source_handle:
                    source_bytes = source_handle.read()
            except OSError:
                continue

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
    "ReconstructedVisual",
    "reconstruct_and_sanitize_sources",
    "sanitize_text_sources",
]
