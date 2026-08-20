"""Canonical mixed-modality file preparation for upload and reindex paths."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, Optional

import fitz
import tiktoken
from langchain.text_splitter import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain_core.documents import Document

from open_webui.retrieval.embedding.errors import (
    EMBEDDING_IMAGE_FORMAT_UNSUPPORTED,
    EMBEDDING_IMAGE_INVALID,
    EMBEDDING_MODALITY_UNSUPPORTED,
    PDF_VISUAL_EXTRACTION_FAILED,
    PDF_VISUAL_LIMIT_EXCEEDED,
    PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL,
    VIDEO_DURATION_EXCEEDED,
    VIDEO_VALIDATION_FAILED,
    EmbeddingError,
)
from open_webui.retrieval.embedding.inputs import (
    EmbeddingInput,
    EmbeddingModelSpec,
    ImageEmbeddingInput,
    TextEmbeddingInput,
    VideoEmbeddingInput,
)
from open_webui.retrieval.loaders.main import Loader
from open_webui.retrieval.loaders.pdf_complex import (
    COMPLEX_PDF_EXTRACTION_VERSION,
    ComplexPDFExtractionError,
    ComplexPDFExtractor,
    PDF_FIGURE_MIN_AREA,
    PDF_FIGURE_MIN_HEIGHT,
    PDF_FIGURE_MIN_WIDTH,
    PDF_RENDER_ALPHA,
    PDF_RENDER_FORMAT,
    PDF_RENDER_SCALE,
    PDF_TABLE_PADDING_POINTS,
    PDFVisualLimitExceededError,
    TextBlock,
    VisualBlock,
)


PreparedModality = Literal["text", "image", "video"]
STANDALONE_IMAGE_EXTRACTION_VERSION = "standalone_image_v1"
VIDEO_EXTRACTION_VERSION = "video_temporal_v1"
PREPARATION_RECIPE_VERSION = "multimodal_preparation_v1"
PDF_COORDINATE_SPACE = "rotated_cropbox_top_left_points"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")
# Keep a decoded RGB image near or below 120 MiB and reject extreme aspect
# ratios before asking the image decoder to allocate its pixel buffer.
MAX_STANDALONE_IMAGE_DIMENSION = 16_384
MAX_STANDALONE_IMAGE_PIXELS = 40_000_000
_BYTES_PER_MEBIBYTE = 1024 * 1024
_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_UNSUPPORTED_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


class UploadByteLimitExceededError(ValueError):
    """Raised before upload validation when a configured byte limit is exceeded."""

    def __init__(self, max_size_mb: int):
        self.max_size_mb = max_size_mb
        super().__init__("upload exceeds the configured byte limit")


def read_upload_bytes(upload_file: Any, max_size_mb: Optional[int]) -> bytes:
    """Read an upload once, bounding the read when an upload limit is configured."""
    byte_limit: Optional[int] = None
    if max_size_mb is not None:
        if isinstance(max_size_mb, bool) or not isinstance(max_size_mb, int):
            raise ValueError("upload byte limit must be an integer or null")
        if max_size_mb < 0:
            raise ValueError("upload byte limit must not be negative")
        byte_limit = max_size_mb * _BYTES_PER_MEBIBYTE
        declared_size = getattr(upload_file, "size", None)
        if isinstance(declared_size, int) and declared_size > byte_limit:
            raise UploadByteLimitExceededError(max_size_mb)

    stream = getattr(upload_file, "file", None)
    if stream is None or not callable(getattr(stream, "read", None)):
        raise TypeError("upload_file must expose a readable binary stream")
    contents = stream.read() if byte_limit is None else stream.read(byte_limit + 1)
    if not isinstance(contents, (bytes, bytearray)):
        raise TypeError("upload stream must return bytes")
    if byte_limit is not None and len(contents) > byte_limit:
        raise UploadByteLimitExceededError(max_size_mb)
    return bytes(contents)


@dataclass(frozen=True)
class PreparationRecipe:
    """Frozen, canonical inputs that determine file extraction and chunking.

    Reindex jobs persist both this record and its digest. Workers use these
    values instead of mutable live settings, while retry creation compares a
    newly resolved recipe with the snapshot and requires a fresh model change
    when behavior has drifted.
    """

    complex_pdf_parser_enabled: bool
    max_visuals_per_page: int
    max_visuals_per_document: int
    text_splitter: str
    tiktoken_encoding_name: str
    chunk_size: int
    chunk_overlap: int
    content_extraction_engine: str
    recipe_version: str = PREPARATION_RECIPE_VERSION
    complex_pdf_extraction_version: str = COMPLEX_PDF_EXTRACTION_VERSION
    standalone_image_extraction_version: str = (
        STANDALONE_IMAGE_EXTRACTION_VERSION
    )
    pdf_figure_min_width: float = PDF_FIGURE_MIN_WIDTH
    pdf_figure_min_height: float = PDF_FIGURE_MIN_HEIGHT
    pdf_figure_min_area: float = PDF_FIGURE_MIN_AREA
    pdf_render_scale: float = PDF_RENDER_SCALE
    pdf_table_padding_points: float = PDF_TABLE_PADDING_POINTS
    pdf_render_format: str = PDF_RENDER_FORMAT
    pdf_render_alpha: bool = PDF_RENDER_ALPHA
    pdf_coordinate_space: str = PDF_COORDINATE_SPACE
    video_chunk_duration: int = 16
    video_min_chunk_duration: int = 4
    video_max_duration: int = 120
    video_extraction_version: str = VIDEO_EXTRACTION_VERSION

    def __post_init__(self) -> None:
        integer_values = (
            self.max_visuals_per_page,
            self.max_visuals_per_document,
            self.chunk_size,
            self.chunk_overlap,
            self.video_chunk_duration,
            self.video_min_chunk_duration,
            self.video_max_duration,
        )
        numeric_values = (
            self.pdf_figure_min_width,
            self.pdf_figure_min_height,
            self.pdf_figure_min_area,
            self.pdf_render_scale,
            self.pdf_table_padding_points,
        )
        string_values = (
            self.recipe_version,
            self.complex_pdf_extraction_version,
            self.standalone_image_extraction_version,
            self.video_extraction_version,
            self.pdf_render_format,
            self.pdf_coordinate_space,
            self.text_splitter,
            self.tiktoken_encoding_name,
            self.content_extraction_engine,
        )
        if not isinstance(self.complex_pdf_parser_enabled, bool):
            raise ValueError("complex PDF parser flag must be boolean")
        if not isinstance(self.pdf_render_alpha, bool):
            raise ValueError("PDF render alpha flag must be boolean")
        if any(not isinstance(value, str) for value in string_values):
            raise ValueError("preparation recipe string field has an invalid type")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in integer_values
        ):
            raise ValueError("preparation recipe integer field has an invalid type")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in numeric_values
        ):
            raise ValueError("preparation recipe numeric field has an invalid type")
        if self.recipe_version != PREPARATION_RECIPE_VERSION:
            raise ValueError("unsupported preparation recipe version")
        if self.complex_pdf_extraction_version != COMPLEX_PDF_EXTRACTION_VERSION:
            raise ValueError("unsupported complex PDF extraction version")
        if (
            self.standalone_image_extraction_version
            != STANDALONE_IMAGE_EXTRACTION_VERSION
        ):
            raise ValueError("unsupported standalone image extraction version")
        if self.video_extraction_version != VIDEO_EXTRACTION_VERSION:
            raise ValueError("unsupported video extraction version")
        if self.video_chunk_duration <= 0:
            raise ValueError("video chunk duration must be positive")
        if self.video_min_chunk_duration <= 0:
            raise ValueError("video minimum chunk duration must be positive")
        if self.video_min_chunk_duration >= self.video_chunk_duration:
            raise ValueError("video minimum chunk duration must be less than chunk duration")
        if self.video_max_duration <= 0:
            raise ValueError("video max duration must be positive")
        if self.text_splitter not in {"recursive", "token"}:
            raise ValueError("unsupported text splitter")
        if not self.tiktoken_encoding_name:
            raise ValueError("tiktoken encoding name is required")
        if self.chunk_size <= 0:
            raise ValueError("chunk size must be positive")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        if self.max_visuals_per_page < 1:
            raise ValueError("per-page visual limit must be positive")
        if self.max_visuals_per_document < 1:
            raise ValueError("per-document visual limit must be positive")
        expected_constants = {
            "pdf_figure_min_width": PDF_FIGURE_MIN_WIDTH,
            "pdf_figure_min_height": PDF_FIGURE_MIN_HEIGHT,
            "pdf_figure_min_area": PDF_FIGURE_MIN_AREA,
            "pdf_render_scale": PDF_RENDER_SCALE,
            "pdf_table_padding_points": PDF_TABLE_PADDING_POINTS,
            "pdf_render_format": PDF_RENDER_FORMAT,
            "pdf_render_alpha": PDF_RENDER_ALPHA,
            "pdf_coordinate_space": PDF_COORDINATE_SPACE,
        }
        for field_name, expected in expected_constants.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"unsupported preparation constant: {field_name}")

    @property
    def sha256(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def chunk_settings(self) -> tuple[int, int, str, str]:
        return (
            self.chunk_size,
            self.chunk_overlap,
            self.text_splitter,
            self.tiktoken_encoding_name,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the stable JSON record whose canonical bytes are hashed."""
        return {
            "recipe_version": self.recipe_version,
            "complex_pdf_parser_enabled": self.complex_pdf_parser_enabled,
            "max_visuals_per_page": self.max_visuals_per_page,
            "max_visuals_per_document": self.max_visuals_per_document,
            "complex_pdf_extraction_version": self.complex_pdf_extraction_version,
            "standalone_image_extraction_version": (
                self.standalone_image_extraction_version
            ),
            "video_extraction_version": self.video_extraction_version,
            "pdf_figure_min_width": self.pdf_figure_min_width,
            "pdf_figure_min_height": self.pdf_figure_min_height,
            "pdf_figure_min_area": self.pdf_figure_min_area,
            "pdf_render_scale": self.pdf_render_scale,
            "pdf_table_padding_points": self.pdf_table_padding_points,
            "pdf_render_format": self.pdf_render_format,
            "pdf_render_alpha": self.pdf_render_alpha,
            "pdf_coordinate_space": self.pdf_coordinate_space,
            "text_splitter": self.text_splitter,
            "tiktoken_encoding_name": self.tiktoken_encoding_name,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "content_extraction_engine": self.content_extraction_engine,
            "video_chunk_duration": self.video_chunk_duration,
            "video_min_chunk_duration": self.video_min_chunk_duration,
            "video_max_duration": self.video_max_duration,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PreparationRecipe":
        """Validate and rebuild a recipe persisted in a job snapshot."""
        if not isinstance(data, Mapping):
            raise ValueError("preparation recipe must be an object")
        try:
            parser_enabled = data["complex_pdf_parser_enabled"]
            render_alpha = data["pdf_render_alpha"]
            extraction_engine = data["content_extraction_engine"]
            string_fields = (
                "recipe_version",
                "complex_pdf_extraction_version",
                "standalone_image_extraction_version",
                "pdf_render_format",
                "pdf_coordinate_space",
                "text_splitter",
                "tiktoken_encoding_name",
            )
            integer_fields = (
                "max_visuals_per_page",
                "max_visuals_per_document",
                "chunk_size",
                "chunk_overlap",
            )
            number_fields = (
                "pdf_figure_min_width",
                "pdf_figure_min_height",
                "pdf_figure_min_area",
                "pdf_render_scale",
                "pdf_table_padding_points",
            )
            # Video fields are optional for backward compatibility with
            # snapshots created before video support was added.
            video_optional_fields = {
                "video_extraction_version",
                "video_chunk_duration",
                "video_min_chunk_duration",
                "video_max_duration",
            }
            expected_fields = {
                *string_fields,
                *integer_fields,
                *number_fields,
                "complex_pdf_parser_enabled",
                "pdf_render_alpha",
                "content_extraction_engine",
            }
            present_keys = set(data)
            # Accept snapshots that have the video fields or lack them entirely.
            extra_keys = present_keys - expected_fields - video_optional_fields
            if extra_keys:
                raise ValueError("preparation recipe fields are not canonical")
            missing_required = expected_fields - present_keys
            if missing_required:
                raise ValueError("preparation recipe fields are not canonical")
            if not isinstance(parser_enabled, bool):
                raise ValueError("parser flag must be boolean")
            if not isinstance(render_alpha, bool):
                raise ValueError("render alpha flag must be boolean")
            if not isinstance(extraction_engine, str):
                raise ValueError("extraction engine must be a string")
            if any(not isinstance(data[name], str) for name in string_fields):
                raise ValueError("recipe string field has an invalid type")
            if any(
                isinstance(data[name], bool) or not isinstance(data[name], int)
                for name in integer_fields
            ):
                raise ValueError("recipe integer field has an invalid type")
            if any(
                isinstance(data[name], bool)
                or not isinstance(data[name], (int, float))
                for name in number_fields
            ):
                raise ValueError("recipe numeric field has an invalid type")
            return cls(
                recipe_version=data["recipe_version"],
                complex_pdf_parser_enabled=parser_enabled,
                max_visuals_per_page=data["max_visuals_per_page"],
                max_visuals_per_document=data["max_visuals_per_document"],
                complex_pdf_extraction_version=data[
                    "complex_pdf_extraction_version"
                ],
                standalone_image_extraction_version=data[
                    "standalone_image_extraction_version"
                ],
                pdf_figure_min_width=data["pdf_figure_min_width"],
                pdf_figure_min_height=data["pdf_figure_min_height"],
                pdf_figure_min_area=data["pdf_figure_min_area"],
                pdf_render_scale=data["pdf_render_scale"],
                pdf_table_padding_points=data["pdf_table_padding_points"],
                pdf_render_format=data["pdf_render_format"],
                pdf_render_alpha=render_alpha,
                pdf_coordinate_space=data["pdf_coordinate_space"],
                text_splitter=data["text_splitter"],
                tiktoken_encoding_name=data["tiktoken_encoding_name"],
                chunk_size=data["chunk_size"],
                chunk_overlap=data["chunk_overlap"],
                content_extraction_engine=extraction_engine,
                video_chunk_duration=data.get("video_chunk_duration", 16),
                video_min_chunk_duration=data.get("video_min_chunk_duration", 4),
                video_max_duration=data.get("video_max_duration", 120),
                video_extraction_version=data.get(
                    "video_extraction_version", VIDEO_EXTRACTION_VERSION
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid preparation recipe") from error


def build_preparation_recipe(config, admin_email: str) -> PreparationRecipe:
    """Resolve one admin's mutable preparation settings into a frozen recipe."""
    chunk_size, chunk_overlap, splitter_name, encoding_name = _chunk_settings(
        config, admin_email
    )
    return PreparationRecipe(
        complex_pdf_parser_enabled=_bool_config(
            config, "RAG_PDF_COMPLEX_PARSER_ENABLED", True
        ),
        max_visuals_per_page=_positive_int_config(
            config, "RAG_PDF_MAX_VISUALS_PER_PAGE", 6
        ),
        max_visuals_per_document=_positive_int_config(
            config, "RAG_PDF_MAX_VISUALS_PER_DOCUMENT", 80
        ),
        text_splitter=splitter_name,
        tiktoken_encoding_name=encoding_name,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        content_extraction_engine=str(
            _config_value(config, "CONTENT_EXTRACTION_ENGINE", "") or ""
        ),
        video_chunk_duration=_positive_int_config(
            config, "RAG_VIDEO_CHUNK_DURATION", 16
        ),
        video_min_chunk_duration=_positive_int_config(
            config, "RAG_VIDEO_MIN_CHUNK_DURATION", 4
        ),
        video_max_duration=_positive_int_config(
            config, "RAG_VIDEO_MAX_DURATION", 120
        ),
    )


def preparation_recipe_from_snapshot(snapshot: Mapping[str, Any]) -> PreparationRecipe:
    """Return an integrity-checked recipe from one persisted file snapshot."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("file snapshot must be an object")
    recipe = PreparationRecipe.from_dict(snapshot.get("preparation_recipe"))
    digest = snapshot.get("preparation_recipe_sha256")
    if not isinstance(digest, str) or digest != recipe.sha256:
        raise ValueError("preparation recipe digest mismatch")
    return recipe


# ──────────────────────────────────────────────────────────────────────
# Video temporal chunking planner
# ──────────────────────────────────────────────────────────────────────

_MPEG_SIGNATURES = (b"\x00\x00\x01\xb3", b"\x00\x00\x01\xba")
_VIDEO_MIME_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}


@dataclass(frozen=True)
class VideoChunk:
    """One temporal range within a video, ready for provider dispatch."""

    chunk_index: int
    start_offset_seconds: float
    end_offset_seconds: float
    interval_seconds: float


def plan_video_chunks(
    duration_seconds: float,
    *,
    chunk_duration_seconds: int = 16,
    minimum_chunk_duration_seconds: int = 4,
) -> tuple[VideoChunk, ...]:
    """Create sequential non-overlapping temporal ranges for a video.

    Pure planner: no I/O, no provider calls, independently unit-testable.
    Boundaries are rounded to three decimal places for deterministic manifests.
    """
    if not isinstance(duration_seconds, (int, float)):
        raise ValueError("duration_seconds must be numeric")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be a finite positive number")
    if not isinstance(chunk_duration_seconds, int) or chunk_duration_seconds <= 0:
        raise ValueError("chunk_duration_seconds must be a positive integer")
    if (
        not isinstance(minimum_chunk_duration_seconds, int)
        or minimum_chunk_duration_seconds <= 0
    ):
        raise ValueError("minimum_chunk_duration_seconds must be a positive integer")
    if minimum_chunk_duration_seconds >= chunk_duration_seconds:
        raise ValueError(
            "minimum_chunk_duration_seconds must be less than chunk_duration_seconds"
        )

    ranges: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_seconds:
        end = min(start + chunk_duration_seconds, duration_seconds)
        ranges.append((start, end))
        start = end

    # Merge trailing chunk if shorter than minimum into the previous chunk.
    if len(ranges) >= 2:
        last_start, last_end = ranges[-1]
        last_duration = last_end - last_start
        if last_duration < minimum_chunk_duration_seconds:
            prev_start, _prev_end = ranges[-2]
            ranges[-2] = (prev_start, last_end)
            ranges.pop()

    chunks: list[VideoChunk] = []
    for index, (range_start, range_end) in enumerate(ranges):
        chunks.append(
            VideoChunk(
                chunk_index=index,
                start_offset_seconds=round(range_start, 3),
                end_offset_seconds=round(range_end, 3),
                interval_seconds=round(range_end - range_start, 3),
            )
        )
    return tuple(chunks)


def validate_video(
    source_bytes: bytes,
    *,
    max_duration_seconds: int = 120,
    declared_mime_type: Optional[str] = None,
    filename: str = "",
) -> tuple[str, float]:
    """Validate video bytes with ffprobe and return (canonical_mime, duration).

    Writes bytes to a temporary file, invokes Docker-provided ffprobe, verifies
    a video stream exists, reads duration, and enforces the maximum.

    When magic bytes are inconclusive, declared MIME type or file extension is
    used to select the candidate type; ffprobe remains the final authority.

    Raises EmbeddingError with VIDEO_VALIDATION_FAILED or VIDEO_DURATION_EXCEEDED.
    """
    if not isinstance(source_bytes, bytes) or not source_bytes:
        raise EmbeddingError(VIDEO_VALIDATION_FAILED)

    # Infer MIME from magic bytes; fall back to declared MIME / extension.
    canonical_mime = _infer_video_mime(source_bytes)
    if canonical_mime is None:
        canonical_mime = canonical_video_content_type(
            source_bytes, filename, declared_mime_type
        )
    if canonical_mime is None:
        raise EmbeddingError(VIDEO_VALIDATION_FAILED)

    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=_video_suffix(canonical_mime)) as tmp:
            tmp.write(source_bytes)
            tmp.flush()
            tmp_path = tmp.name
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    tmp_path,
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise EmbeddingError(VIDEO_VALIDATION_FAILED)

            probe = json.loads(result.stdout)
            streams = probe.get("streams", [])
            has_video = any(
                stream.get("codec_type") == "video" for stream in streams
            )
            if not has_video:
                raise EmbeddingError(VIDEO_VALIDATION_FAILED)

            format_info = probe.get("format", {})
            duration_raw = format_info.get("duration")
            if duration_raw is None:
                raise EmbeddingError(VIDEO_VALIDATION_FAILED)
            try:
                duration = float(duration_raw)
            except (TypeError, ValueError):
                raise EmbeddingError(VIDEO_VALIDATION_FAILED) from None

            if not math.isfinite(duration) or duration <= 0:
                raise EmbeddingError(VIDEO_VALIDATION_FAILED)
            if duration > max_duration_seconds:
                raise EmbeddingError(
                    VIDEO_DURATION_EXCEEDED,
                    detail=f"Video duration {duration:.1f}s exceeds maximum {max_duration_seconds}s.",
                )

            return canonical_mime, duration
    except EmbeddingError:
        raise
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        raise EmbeddingError(VIDEO_VALIDATION_FAILED) from None
    except Exception:
        raise EmbeddingError(VIDEO_VALIDATION_FAILED) from None


def _infer_video_mime(source_bytes: bytes) -> Optional[str]:
    """Infer video MIME type from file magic. Returns None if not video."""
    if len(source_bytes) < 12:
        return None
    # MP4/ISO BMFF: ftyp box at offset 4
    if source_bytes[4:8] == b"ftyp":
        return "video/mp4"
    # MPEG-PS start code
    if source_bytes[:4] in _MPEG_SIGNATURES:
        return "video/mpeg"
    return None


def _video_suffix(mime_type: str) -> str:
    if mime_type == "video/mp4":
        return ".mp4"
    if mime_type == "video/mpeg":
        return ".mpeg"
    return ".mp4"


def is_video_upload(
    source_bytes: bytes,
    filename: str,
    declared_mime_type: Optional[str],
) -> bool:
    """Return True if the upload should be treated as a video."""
    if _infer_video_mime(source_bytes) is not None:
        return True
    normalized_mime = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime in {"video/mp4", "video/mpeg"}:
        return True
    extension = Path(filename).suffix.lower()
    if extension in _VIDEO_MIME_EXTENSIONS:
        return True
    return False


def canonical_video_content_type(
    source_bytes: bytes,
    filename: str,
    declared_mime_type: Optional[str],
) -> Optional[str]:
    """Return a magic-authoritative video MIME, or None if not a video."""
    inferred = _infer_video_mime(source_bytes)
    if inferred is not None:
        return inferred
    normalized_mime = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime in {"video/mp4", "video/mpeg"}:
        return normalized_mime
    extension = Path(filename).suffix.lower()
    return _VIDEO_MIME_EXTENSIONS.get(extension)


@dataclass(frozen=True)
class PreparedChunk:
    """One aligned persisted chunk, provider input, hash, and metadata record."""

    content: str
    content_type: PreparedModality
    embedding_input: EmbeddingInput
    content_sha256: str
    modality: PreparedModality
    chunk_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.content_type != self.modality:
            raise ValueError("content_type and modality must match")
        if self.embedding_input.modality != self.modality:
            raise ValueError("embedding input modality does not match chunk modality")
        if not _is_sha256(self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        if self.modality == "text":
            if not isinstance(self.embedding_input, TextEmbeddingInput):
                raise TypeError("text chunks require TextEmbeddingInput")
            if self.embedding_input.text != self.content:
                raise ValueError("text chunk content and provider input must match")
            expected_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        elif self.modality == "video":
            if not isinstance(self.embedding_input, VideoEmbeddingInput):
                raise TypeError("video chunks require VideoEmbeddingInput")
            if self.content:
                raise ValueError("video chunk content must be empty")
            expected_hash = hashlib.sha256(self.embedding_input.video).hexdigest()
        else:
            if not isinstance(self.embedding_input, ImageEmbeddingInput):
                raise TypeError("image chunks require ImageEmbeddingInput")
            if self.content:
                raise ValueError("image chunk content must be empty")
            expected_hash = hashlib.sha256(self.embedding_input.image).hexdigest()
        if expected_hash != self.content_sha256:
            raise ValueError("content_sha256 does not match the embedding input")
        object.__setattr__(
            self,
            "chunk_metadata",
            MappingProxyType(dict(self.chunk_metadata)),
        )

    def as_rag_chunk(self) -> dict:
        return {
            "content": self.content,
            "content_type": self.content_type,
            "content_sha256": self.content_sha256,
            "chunk_metadata": dict(self.chunk_metadata),
        }


@dataclass(frozen=True)
class PreparedFile:
    """Immutable result shared by normal ingestion and reindex workers."""

    chunks: tuple[PreparedChunk, ...]
    text_content: str
    source_sha256: str
    extraction_version: Optional[str]
    warnings: tuple[str, ...]
    visual_summary: Mapping[str, int]

    def __post_init__(self) -> None:
        if not _is_sha256(self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "chunks", tuple(self.chunks))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self,
            "visual_summary",
            MappingProxyType(
                {
                    str(key): int(value)
                    for key, value in dict(self.visual_summary).items()
                }
            ),
        )


def build_persisted_chunks(
    prepared: PreparedFile,
    *,
    admin_id: str,
    file_id: str,
) -> list[dict[str, Any]]:
    """Build the canonical immutable chunk manifest for every ingest path."""
    persisted: list[dict[str, Any]] = []
    for index, chunk in enumerate(prepared.chunks):
        metadata = {
            **dict(chunk.chunk_metadata),
            "chunk_index": index,
            "admin_id": admin_id,
            "file_id": file_id,
            "content_type": chunk.content_type,
            "modality": chunk.modality,
            "content_sha256": chunk.content_sha256,
            "source_sha256": prepared.source_sha256,
            **(
                {"extraction_version": prepared.extraction_version}
                if prepared.extraction_version
                else {}
            ),
        }
        persisted.append(
            {
                "content": chunk.content,
                "content_type": chunk.content_type,
                "content_sha256": chunk.content_sha256,
                "chunk_metadata": metadata,
            }
        )
    return persisted


@dataclass(frozen=True)
class ValidatedStandaloneImage:
    mime_type: Literal["image/png", "image/jpeg"]
    pixel_width: int
    pixel_height: int
    content_sha256: str


def _png_dimensions(source_bytes: bytes) -> tuple[int, int]:
    if (
        len(source_bytes) < 24
        or source_bytes[8:12] != b"\x00\x00\x00\r"
        or source_bytes[12:16] != b"IHDR"
    ):
        raise ValueError("invalid PNG header")
    return (
        int.from_bytes(source_bytes[16:20], "big"),
        int.from_bytes(source_bytes[20:24], "big"),
    )


def _jpeg_dimensions(source_bytes: bytes) -> tuple[int, int]:
    offset = 2
    source_length = len(source_bytes)
    while offset < source_length:
        if source_bytes[offset] != 0xFF:
            raise ValueError("invalid JPEG marker")
        while offset < source_length and source_bytes[offset] == 0xFF:
            offset += 1
        if offset >= source_length:
            break

        marker = source_bytes[offset]
        offset += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if marker in {0x00, 0xD9, 0xDA} or offset + 2 > source_length:
            break

        segment_length = int.from_bytes(source_bytes[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > source_length:
            raise ValueError("invalid JPEG segment")
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 8:
                raise ValueError("invalid JPEG frame header")
            height = int.from_bytes(source_bytes[offset + 3 : offset + 5], "big")
            width = int.from_bytes(source_bytes[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    raise ValueError("JPEG frame header not found")


def _validate_standalone_image_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if (
        width > MAX_STANDALONE_IMAGE_DIMENSION
        or height > MAX_STANDALONE_IMAGE_DIMENSION
        or width * height > MAX_STANDALONE_IMAGE_PIXELS
    ):
        raise ValueError("image dimensions exceed the safety ceiling")


def validate_standalone_image(
    source_bytes: bytes, declared_mime_type: Optional[str] = None
) -> ValidatedStandaloneImage:
    """Validate and decode a standalone PNG/JPEG using file magic as authority."""
    if not isinstance(source_bytes, bytes) or not source_bytes:
        raise EmbeddingError(EMBEDDING_IMAGE_INVALID)

    if source_bytes.startswith(_PNG_SIGNATURE):
        mime_type: Literal["image/png", "image/jpeg"] = "image/png"
        filetype = "png"
    elif source_bytes.startswith(_JPEG_SIGNATURE):
        mime_type = "image/jpeg"
        filetype = "jpeg"
    elif source_bytes.startswith(_GIF_SIGNATURES) or _is_webp_or_avif(source_bytes):
        raise EmbeddingError(EMBEDDING_IMAGE_FORMAT_UNSUPPORTED)
    elif (declared_mime_type or "").lower().startswith("image/"):
        canonical_declared = (declared_mime_type or "").split(";", 1)[0].lower()
        if canonical_declared not in {"image/png", "image/jpeg"}:
            raise EmbeddingError(EMBEDDING_IMAGE_FORMAT_UNSUPPORTED)
        raise EmbeddingError(EMBEDDING_IMAGE_INVALID)
    else:
        raise EmbeddingError(EMBEDDING_IMAGE_INVALID)

    try:
        width, height = (
            _png_dimensions(source_bytes)
            if mime_type == "image/png"
            else _jpeg_dimensions(source_bytes)
        )
        _validate_standalone_image_dimensions(width, height)
        with fitz.open(stream=source_bytes, filetype=filetype) as image_document:
            if len(image_document) != 1:
                raise ValueError("unexpected image page count")
            image_page = image_document[0]
            page_width = float(image_page.rect.width)
            page_height = float(image_page.rect.height)
            if page_width <= 0 or page_height <= 0:
                raise ValueError("invalid decoded image dimensions")
            pixmap = image_page.get_pixmap(
                matrix=fitz.Matrix(width / page_width, height / page_height),
                alpha=False,
            )
            _validate_standalone_image_dimensions(
                int(pixmap.width), int(pixmap.height)
            )
    except Exception:
        raise EmbeddingError(EMBEDDING_IMAGE_INVALID) from None

    return ValidatedStandaloneImage(
        mime_type=mime_type,
        pixel_width=width,
        pixel_height=height,
        content_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )


def validate_uploaded_standalone_image(
    source_bytes: bytes, filename: str, declared_mime_type: Optional[str]
) -> Optional[ValidatedStandaloneImage]:
    """Validate an upload when its MIME, extension, or magic denotes an image."""
    normalized_mime = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if source_bytes.startswith(b"%PDF-"):
        return None
    if not _is_standalone_image_candidate(source_bytes, filename, normalized_mime):
        return None
    return validate_standalone_image(source_bytes, normalized_mime)


def canonical_upload_content_type(
    source_bytes: bytes,
    filename: str,
    declared_mime_type: Optional[str],
) -> Optional[str]:
    """Return a magic-authoritative upload MIME for supported direct formats."""
    if source_bytes.startswith(b"%PDF-"):
        return "application/pdf"
    image = validate_uploaded_standalone_image(
        source_bytes,
        filename,
        declared_mime_type,
    )
    if image is not None:
        return image.mime_type
    video_mime = canonical_video_content_type(source_bytes, filename, declared_mime_type)
    if video_mime is not None:
        return video_mime
    return declared_mime_type


def prepare_file_for_embedding(
    *,
    source_bytes: bytes,
    source_path: Optional[str],
    filename: str,
    content_type: Optional[str],
    file_id: str,
    created_by: str,
    model: EmbeddingModelSpec,
    config,
    admin_email: str,
    content_override: Optional[str] = None,
    preparation_recipe: Optional[PreparationRecipe] = None,
) -> PreparedFile:
    """Prepare a stored file for one frozen admin/model embedding context."""
    if not isinstance(source_bytes, bytes):
        raise TypeError("source_bytes must be bytes")

    recipe = preparation_recipe or build_preparation_recipe(config, admin_email)

    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    source_kind = _classify_source(
        source_bytes,
        normalized_content_type,
        filename,
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    base_metadata = {
        "file_id": file_id,
        "name": filename,
        "source": filename,
        "created_by": created_by,
        "source_sha256": source_sha256,
        "preparation_recipe_sha256": recipe.sha256,
    }
    chunk_settings = recipe.chunk_settings

    if not source_bytes:
        if source_kind == "image":
            raise EmbeddingError(EMBEDDING_IMAGE_INVALID)
        if source_kind == "pdf":
            raise EmbeddingError(PDF_VISUAL_EXTRACTION_FAILED)
        return PreparedFile(
            chunks=(),
            text_content="",
            source_sha256=source_sha256,
            extraction_version=None,
            warnings=(),
            visual_summary=_visual_summary(
                figure_count=0,
                table_image_count=0,
                image_chunk_count=0,
                text_chunk_count=0,
            ),
        )

    if source_kind == "image":
        image = validate_standalone_image(source_bytes, normalized_content_type)
        if "image" not in model.modalities:
            raise EmbeddingError(EMBEDDING_MODALITY_UNSUPPORTED)
        identity_payload = f"{file_id}\0{source_sha256}".encode("utf-8")
        visual_asset_id = f"fileimg_{hashlib.sha256(identity_payload).hexdigest()}"
        metadata = {
            **base_metadata,
            "modality": "image",
            "content_kind": "standalone_image",
            "visual_asset_id": visual_asset_id,
            "extraction_version": recipe.standalone_image_extraction_version,
            "mime_type": image.mime_type,
            "pixel_width": image.pixel_width,
            "pixel_height": image.pixel_height,
            "image_sha256": image.content_sha256,
        }
        chunk = PreparedChunk(
            content="",
            content_type="image",
            embedding_input=ImageEmbeddingInput(
                image=source_bytes, mime_type=image.mime_type
            ),
            content_sha256=image.content_sha256,
            modality="image",
            chunk_metadata=metadata,
        )
        return PreparedFile(
            chunks=(chunk,),
            text_content="",
            source_sha256=source_sha256,
            extraction_version=recipe.standalone_image_extraction_version,
            warnings=(),
            visual_summary=_visual_summary(
                figure_count=0,
                table_image_count=0,
                image_chunk_count=1,
                text_chunk_count=0,
            ),
        )

    if source_kind == "video":
        return _prepare_video(
            source_bytes=source_bytes,
            normalized_content_type=normalized_content_type,
            filename=filename,
            file_id=file_id,
            source_sha256=source_sha256,
            model=model,
            recipe=recipe,
            base_metadata=base_metadata,
        )

    if source_kind == "pdf":
        if recipe.complex_pdf_parser_enabled:
            return _prepare_complex_pdf(
                source_bytes=source_bytes,
                source_path=source_path,
                filename=filename,
                file_id=file_id,
                model=model,
                config=config,
                preparation_recipe=recipe,
                base_metadata=base_metadata,
                chunk_settings=chunk_settings,
            )

    documents = _load_legacy_documents(
        source_path=source_path,
        filename=filename,
        content_type=normalized_content_type,
        config=config,
        content_override=content_override,
        base_metadata=base_metadata,
        content_extraction_engine=recipe.content_extraction_engine,
    )
    chunks = _prepare_text_documents(documents, chunk_settings)
    text_content = "\n\n".join(
        document.page_content.strip()
        for document in documents
        if document.page_content and document.page_content.strip()
    )
    return PreparedFile(
        chunks=tuple(chunks),
        text_content=text_content,
        source_sha256=source_sha256,
        extraction_version=None,
        warnings=(),
        visual_summary=_visual_summary(
            figure_count=0,
            table_image_count=0,
            image_chunk_count=0,
            text_chunk_count=len(chunks),
        ),
    )


def _prepare_complex_pdf(
    *,
    source_bytes: bytes,
    source_path: Optional[str],
    filename: str,
    file_id: str,
    model: EmbeddingModelSpec,
    config,
    preparation_recipe: PreparationRecipe,
    base_metadata: dict,
    chunk_settings: tuple[int, int, str, str],
) -> PreparedFile:
    # Always obtain text from the legacy loader. The complex parser is strictly
    # a visual sidecar and must not alter text, normalization, or chunking.
    legacy_documents = _load_legacy_documents(
        source_path=source_path, filename=filename, content_type="application/pdf",
        config=config, content_override=None, base_metadata=base_metadata,
        content_extraction_engine=preparation_recipe.content_extraction_engine,
    )
    legacy_chunks = _prepare_text_documents(legacy_documents, chunk_settings)
    legacy_text = "\n\n".join(
        document.page_content.strip() for document in legacy_documents
        if document.page_content and document.page_content.strip()
    )
    try:
        extraction = ComplexPDFExtractor(
            max_visuals_per_page=preparation_recipe.max_visuals_per_page,
            max_visuals_per_document=(
                preparation_recipe.max_visuals_per_document
            ),
        ).extract(source_bytes)
    except PDFVisualLimitExceededError:
        raise EmbeddingError(PDF_VISUAL_LIMIT_EXCEEDED) from None
    except ComplexPDFExtractionError:
        if "image" in model.modalities:
            raise EmbeddingError(PDF_VISUAL_EXTRACTION_FAILED) from None
        if not legacy_chunks:
            raise EmbeddingError(EMBEDDING_MODALITY_UNSUPPORTED) from None
        return PreparedFile(
            chunks=tuple(legacy_chunks), text_content=legacy_text,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            extraction_version=COMPLEX_PDF_EXTRACTION_VERSION,
            warnings=(
                PDF_VISUAL_EXTRACTION_FAILED,
                PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL,
            ),
            visual_summary=_visual_summary(
                figure_count=0,
                table_image_count=0,
                image_chunk_count=0,
                text_chunk_count=len(legacy_chunks),
            ),
        )
    except Exception:
        raise EmbeddingError(PDF_VISUAL_EXTRACTION_FAILED) from None

    visual_chunks: list[PreparedChunk] = []
    visual_supported = "image" in model.modalities
    warning_codes = [warning.code for warning in extraction.warnings]

    for block in extraction.blocks:
        common = {
            **base_metadata,
            "extraction_version": extraction.extraction_version,
            "page_index": block.page_index,
            "page_number": block.page_index + 1,
            "element_number": block.page_local_sequence + 1,
            "page_local_sequence": block.page_local_sequence,
            "source_sequence": block.source_sequence,
            "top_norm": block.normalized_vertical_position,
        }
        if isinstance(block, TextBlock):
            if not block.text.strip():
                continue
            continue

        if not isinstance(block, VisualBlock) or not visual_supported:
            continue
        visual_asset_id = _pdf_visual_asset_id(
            source_sha256=extraction.source_sha256,
            extraction_version=extraction.extraction_version,
            block=block,
        )
        metadata = {
            **common,
            "modality": "image",
            "content_kind": (
                "pdf_table" if block.kind == "table_image" else "pdf_figure"
            ),
            "visual_asset_id": visual_asset_id,
            "bbox": list(block.bbox),
            "coordinate_space": block.coordinate_space,
            "render_scale": block.render_scale,
            "padding_points": block.padding_points,
            "output_format": block.output_format,
            "alpha": block.alpha,
            "mime_type": block.mime_type,
            "pixel_width": block.pixel_width,
            "pixel_height": block.pixel_height,
            "image_sha256": block.content_sha256,
        }
        visual_chunks.append(
            PreparedChunk(
                content="",
                content_type="image",
                embedding_input=ImageEmbeddingInput(
                    image=block.png_bytes, mime_type=block.mime_type
                ),
                content_sha256=block.content_sha256,
                modality="image",
                chunk_metadata=metadata,
            )
        )

    visual_count = extraction.summary.visual_block_count
    if visual_count and not visual_supported:
        warning_codes.append(PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL)
    warning_codes = list(dict.fromkeys(warning_codes))

    if not legacy_chunks and visual_count and not visual_supported:
        raise EmbeddingError(EMBEDDING_MODALITY_UNSUPPORTED)

    def page_index(chunk: PreparedChunk) -> int:
        value = chunk.chunk_metadata.get("page", chunk.chunk_metadata.get("page_index", 0))
        return int(value) if isinstance(value, int) else 0

    text_by_page: dict[int, list[PreparedChunk]] = {}
    for chunk in legacy_chunks:
        text_by_page.setdefault(page_index(chunk), []).append(chunk)
    visual_by_page: dict[int, list[PreparedChunk]] = {}
    for chunk in visual_chunks:
        visual_by_page.setdefault(page_index(chunk), []).append(chunk)
    chunks = []
    for page in sorted(set(text_by_page) | set(visual_by_page)):
        chunks.extend(text_by_page.get(page, []))
        chunks.extend(visual_by_page.get(page, []))

    image_chunk_count = len(visual_chunks)
    text_chunk_count = len(legacy_chunks)
    return PreparedFile(
        chunks=tuple(chunks),
        text_content=legacy_text,
        source_sha256=extraction.source_sha256,
        extraction_version=extraction.extraction_version,
        warnings=tuple(warning_codes),
        visual_summary=_visual_summary(
            figure_count=extraction.summary.figure_count,
            table_image_count=extraction.summary.image_bearing_table_count,
            image_chunk_count=image_chunk_count,
            text_chunk_count=text_chunk_count,
        ),
    )


def _prepare_video(
    *,
    source_bytes: bytes,
    normalized_content_type: str,
    filename: str,
    file_id: str,
    source_sha256: str,
    model: EmbeddingModelSpec,
    recipe: PreparationRecipe,
    base_metadata: dict,
) -> PreparedFile:
    """Prepare a video file for temporal embedding.

    Validates with ffprobe (defense in depth), plans temporal chunks, and
    creates one PreparedChunk per range. Original bytes are sent to the
    provider; no frames are extracted or transcoded.
    """
    if "video" not in model.modalities:
        raise EmbeddingError(EMBEDDING_MODALITY_UNSUPPORTED)

    canonical_mime, duration = validate_video(
        source_bytes,
        max_duration_seconds=recipe.video_max_duration,
        declared_mime_type=normalized_content_type,
        filename=filename,
    )

    video_chunks = plan_video_chunks(
        duration,
        chunk_duration_seconds=recipe.video_chunk_duration,
        minimum_chunk_duration_seconds=recipe.video_min_chunk_duration,
    )

    content_sha256 = hashlib.sha256(source_bytes).hexdigest()
    chunks: list[PreparedChunk] = []
    for vc in video_chunks:
        metadata = {
            **base_metadata,
            "modality": "video",
            "content_kind": "video_temporal",
            "startTimeSeconds": vc.start_offset_seconds,
            "endTimeSeconds": vc.end_offset_seconds,
            "chunkIndex": vc.chunk_index,
            "fileId": file_id,
            "extraction_version": recipe.video_extraction_version,
            "mime_type": canonical_mime,
            "duration_seconds": duration,
        }
        chunks.append(
            PreparedChunk(
                content="",
                content_type="video",
                embedding_input=VideoEmbeddingInput(
                    video=source_bytes,
                    mime_type=canonical_mime,
                    start_offset_seconds=vc.start_offset_seconds,
                    end_offset_seconds=vc.end_offset_seconds,
                    interval_seconds=vc.interval_seconds,
                ),
                content_sha256=content_sha256,
                modality="video",
                chunk_metadata=metadata,
            )
        )

    return PreparedFile(
        chunks=tuple(chunks),
        text_content="",
        source_sha256=source_sha256,
        extraction_version=recipe.video_extraction_version,
        warnings=(),
        visual_summary=_visual_summary(
            figure_count=0,
            table_image_count=0,
            image_chunk_count=0,
            text_chunk_count=0,
            video_chunk_count=len(chunks),
        ),
    )


def _prepare_text_documents(
    documents: list[Document], chunk_settings: tuple[int, int, str, str]
) -> list[PreparedChunk]:
    chunk_size, chunk_overlap, splitter_name, encoding_name = chunk_settings
    splitter = _make_text_splitter(
        chunk_size, chunk_overlap, splitter_name, encoding_name
    )
    split_documents = splitter.split_documents(
        [
            document
            for document in documents
            if document.page_content and document.page_content.strip()
        ]
    )
    chunks: list[PreparedChunk] = []
    for document in split_documents:
        text = document.page_content
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        metadata = {
            **document.metadata,
            "modality": "text",
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "text_splitter": splitter_name,
        }
        chunks.append(
            PreparedChunk(
                content=text,
                content_type="text",
                embedding_input=TextEmbeddingInput(text=text),
                content_sha256=digest,
                modality="text",
                chunk_metadata=metadata,
            )
        )
    return chunks


def _load_legacy_documents(
    *,
    source_path: Optional[str],
    filename: str,
    content_type: str,
    config,
    content_override: Optional[str],
    base_metadata: dict,
    content_extraction_engine: str,
) -> list[Document]:
    if content_override is not None:
        return [
            Document(
                page_content=content_override.replace("<br/>", "\n"),
                metadata=dict(base_metadata),
            )
        ]
    if not source_path or not os.path.isfile(source_path):
        return []
    try:
        loader = Loader(
            engine=content_extraction_engine,
            TIKA_SERVER_URL=_config_value(config, "TIKA_SERVER_URL", ""),
            PDF_EXTRACT_IMAGES=False,
            DOCUMENT_INTELLIGENCE_ENDPOINT=_config_value(
                config, "DOCUMENT_INTELLIGENCE_ENDPOINT", ""
            ),
            DOCUMENT_INTELLIGENCE_KEY=_config_value(
                config, "DOCUMENT_INTELLIGENCE_KEY", ""
            ),
        )
        loaded = loader.load(filename, content_type, source_path)
    except Exception:
        if _is_pdf(b"%PDF", content_type, filename):
            raise EmbeddingError(PDF_VISUAL_EXTRACTION_FAILED) from None
        raise
    return [
        Document(
            page_content=document.page_content,
            metadata={
                **{
                    key: value
                    for key, value in (document.metadata or {}).items()
                    if key not in {"file_path", "path", "source", "storage_key"}
                },
                **base_metadata,
            },
        )
        for document in loaded
    ]


def _chunk_settings(config, admin_email: str) -> tuple[int, int, str, str]:
    chunk_size = _user_config_value(config, "CHUNK_SIZE", admin_email, 1000)
    chunk_overlap = _user_config_value(config, "CHUNK_OVERLAP", admin_email, 200)
    try:
        chunk_size = int(chunk_size)
    except (TypeError, ValueError):
        chunk_size = 1000
    try:
        chunk_overlap = int(chunk_overlap)
    except (TypeError, ValueError):
        chunk_overlap = 200
    if chunk_size <= 0:
        chunk_size = 1000
    if chunk_overlap < 0:
        chunk_overlap = 0
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 4
    # ``TEXT_SPLITTER`` is the canonical application-state key. Older
    # installations may persist an empty value to mean the character splitter;
    # normalize that legacy representation without consulting an alias that the
    # application does not register.
    splitter_name = str(
        _config_value(config, "TEXT_SPLITTER", "character") or "character"
    ).strip().lower()
    if splitter_name in {"", "character", "recursive"}:
        splitter_name = "recursive"
    encoding_name = str(_config_value(config, "TIKTOKEN_ENCODING_NAME", "cl100k_base"))
    return chunk_size, chunk_overlap, splitter_name, encoding_name


def _make_text_splitter(
    chunk_size: int, chunk_overlap: int, splitter_name: str, encoding_name: str
):
    if splitter_name in {"", "character", "recursive"}:
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )
    if splitter_name == "token":
        tiktoken.get_encoding(encoding_name)
        return TokenTextSplitter(
            encoding_name=encoding_name,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )
    raise ValueError("Invalid text splitter")


def _config_value(config, name: str, default):
    value = getattr(config, name, default)
    return value.value if hasattr(value, "value") else value


def _bool_config(config, name: str, default: bool) -> bool:
    value = _config_value(config, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _positive_int_config(config, name: str, default: int) -> int:
    value = _config_value(config, name, default)
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return resolved if resolved > 0 else default


def _user_config_value(config, name: str, email: str, default):
    value = getattr(config, name, default)
    if hasattr(value, "get"):
        try:
            resolved = value.get(email)
            return default if resolved is None else resolved
        except Exception:
            return default
    return value


def _is_pdf(source_bytes: bytes, content_type: str, filename: str) -> bool:
    return bool(
        source_bytes.startswith(b"%PDF-")
        or content_type == "application/pdf"
        or Path(filename).suffix.lower() == ".pdf"
    )


def _classify_source(
    source_bytes: bytes,
    content_type: str,
    filename: str,
) -> Literal["pdf", "image", "video", "other"]:
    """Classify supported direct formats with byte magic taking precedence."""
    if source_bytes.startswith(b"%PDF-"):
        return "pdf"
    if source_bytes.startswith((_PNG_SIGNATURE, _JPEG_SIGNATURE) + _GIF_SIGNATURES):
        return "image"
    if _is_webp_or_avif(source_bytes):
        return "image"
    if _is_standalone_image_candidate(source_bytes, filename, content_type):
        return "image"
    if is_video_upload(source_bytes, filename, content_type):
        return "video"
    if _is_pdf(source_bytes, content_type, filename):
        return "pdf"
    return "other"


def _is_standalone_image_candidate(
    source_bytes: bytes, filename: str, content_type: str
) -> bool:
    extension = Path(filename).suffix.lower()
    return bool(
        source_bytes.startswith((_PNG_SIGNATURE, _JPEG_SIGNATURE) + _GIF_SIGNATURES)
        or _is_webp_or_avif(source_bytes)
        or content_type.startswith("image/")
        or extension in _UNSUPPORTED_IMAGE_EXTENSIONS | {".png", ".jpg", ".jpeg"}
    )


def _is_webp_or_avif(source_bytes: bytes) -> bool:
    return bool(
        len(source_bytes) >= 12
        and (
            (source_bytes[:4] == b"RIFF" and source_bytes[8:12] == b"WEBP")
            or source_bytes[4:12] in {b"ftypavif", b"ftypavis"}
        )
    )


def _pdf_visual_asset_id(
    *, source_sha256: str, extraction_version: str, block: VisualBlock
) -> str:
    recipe = {
        "source_sha256": source_sha256,
        "extraction_version": extraction_version,
        "page_index": block.page_index,
        "kind": block.kind,
        "source_sequence": block.source_sequence,
        "bbox": list(block.bbox),
        "render_scale": block.render_scale,
        "padding_points": block.padding_points,
        "output_format": block.output_format,
        "alpha": block.alpha,
    }
    encoded = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"pdfvis_{hashlib.sha256(encoded).hexdigest()}"


def _visual_summary(
    *,
    figure_count: int,
    table_image_count: int,
    image_chunk_count: int,
    text_chunk_count: int,
    video_chunk_count: int = 0,
) -> dict:
    return {
        "figure_count": int(figure_count),
        "table_image_count": int(table_image_count),
        "image_chunk_count": int(image_chunk_count),
        "text_chunk_count": int(text_chunk_count),
        "video_chunk_count": int(video_chunk_count),
    }


_PUBLIC_CHUNK_METADATA_KEYS = {
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


def safe_chunk_metadata(metadata: dict) -> dict:
    """Return only metadata fields approved for browser-facing citations."""
    return {
        key: metadata[key]
        for key in _PUBLIC_CHUNK_METADATA_KEYS
        if metadata.get(key) is not None
    }


def _is_sha256(value: str) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "MAX_STANDALONE_IMAGE_DIMENSION",
    "MAX_STANDALONE_IMAGE_PIXELS",
    "PreparationRecipe",
    "PreparedChunk",
    "PreparedFile",
    "STANDALONE_IMAGE_EXTRACTION_VERSION",
    "VIDEO_EXTRACTION_VERSION",
    "UploadByteLimitExceededError",
    "ValidatedStandaloneImage",
    "VideoChunk",
    "build_persisted_chunks",
    "build_preparation_recipe",
    "canonical_upload_content_type",
    "canonical_video_content_type",
    "is_video_upload",
    "plan_video_chunks",
    "preparation_recipe_from_snapshot",
    "prepare_file_for_embedding",
    "read_upload_bytes",
    "safe_chunk_metadata",
    "validate_standalone_image",
    "validate_uploaded_standalone_image",
    "validate_video",
]
