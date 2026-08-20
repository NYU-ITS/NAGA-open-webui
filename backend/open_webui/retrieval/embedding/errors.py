"""Stable sanitized error codes and domain exceptions."""

from typing import Optional


class EmbeddingError(Exception):
    """
    Base exception for embedding domain errors.
    Carries only a stable error code; no secrets, provider details, or upstream error text.
    """

    def __init__(self, code: str, detail: Optional[str] = None):
        self.code = code
        self.detail = detail
        super().__init__(code)

    def __str__(self) -> str:
        # Sanitize: only expose the stable code, not any upstream details
        return self.code

    def __repr__(self) -> str:
        return f"EmbeddingError(code={self.code!r})"


# ──────────────────────────────────────────────────────────────────────
# Stable error codes for Phase 2
# ──────────────────────────────────────────────────────────────────────

EMBEDDING_MODEL_NOT_CONFIGURED = "embedding_model_not_configured"
EMBEDDING_MODEL_DISABLED = "embedding_model_disabled"
EMBEDDING_ADMIN_UNRESOLVED = "embedding_admin_unresolved"
EMBEDDING_ADMIN_AMBIGUOUS = "embedding_admin_ambiguous"
EMBEDDING_CREDENTIALS_MISSING = "embedding_credentials_missing"
EMBEDDING_PROVIDER_UNSUPPORTED = "embedding_provider_unsupported"
EMBEDDING_MODALITY_UNSUPPORTED = "embedding_modality_unsupported"
EMBEDDING_OUTPUT_COUNT_MISMATCH = "embedding_output_count_mismatch"
EMBEDDING_VECTOR_NOT_SEQUENCE = "embedding_vector_not_sequence"
EMBEDDING_VECTOR_VALUE_INVALID = "embedding_vector_value_invalid"
EMBEDDING_VECTOR_NON_FINITE = "embedding_vector_non_finite"
EMBEDDING_DIMENSION_MISMATCH = "embedding_dimension_mismatch"
EMBEDDING_PROVIDER_FAILED = "embedding_provider_failed"
EMBEDDING_IMAGE_FORMAT_UNSUPPORTED = "embedding_image_format_unsupported"
EMBEDDING_IMAGE_INVALID = "embedding_image_invalid"
VIDEO_VALIDATION_FAILED = "video_validation_failed"
VIDEO_DURATION_EXCEEDED = "video_duration_exceeded"
PDF_VISUAL_EXTRACTION_FAILED = "pdf_visual_extraction_failed"
PDF_VISUAL_LIMIT_EXCEEDED = "pdf_visual_limit_exceeded"
PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL = "pdf_visuals_require_multimodal_model"
FILE_PROCESSING_FAILED = "file_processing_failed"
EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED = "embedding_storage_dimension_unsupported"
EMBEDDING_MODEL_SPACE_MIXED = "embedding_model_space_mixed"
EMBEDDING_MODEL_STATE_CONFLICT = "embedding_model_state_conflict"
EMBEDDING_INVENTORY_UNRESOLVED_SOURCE = "embedding_inventory_unresolved_source"
EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE = "embedding_inventory_ambiguous_source"
EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN = "embedding_inventory_ambiguous_admin"
EMBEDDING_INVENTORY_MISSING_FILE = "embedding_inventory_missing_file"
EMBEDDING_INVENTORY_MALFORMED_REFERENCE = "embedding_inventory_malformed_reference"
EMBEDDING_JOB_ACTIVE_EXISTS = "embedding_job_active_exists"
EMBEDDING_JOB_NOT_FOUND = "embedding_job_not_found"
EMBEDDING_JOB_STALE_OPERATION = "embedding_job_stale_operation"
EMBEDDING_JOB_LEDGER_MISMATCH = "embedding_job_ledger_mismatch"
EMBEDDING_JOB_TERMINAL = "embedding_job_terminal"
EMBEDDING_JOB_WRONG_STATUS = "embedding_job_wrong_status"
EMBEDDING_FILE_NOT_FOUND = "embedding_file_not_found"
EMBEDDING_FILE_WRONG_STATUS = "embedding_file_wrong_status"
EMBEDDING_REINDEX_NOT_READY = "embedding_reindex_not_ready"
EMBEDDING_REINDEX_SOURCE_CHANGED = "embedding_reindex_source_changed"
EMBEDDING_RETRY_ACTIVE_EXISTS = "embedding_retry_active_exists"


# Public file-status messages must be selected from this allowlist. In
# particular, never use ``EmbeddingError.detail`` or an upstream exception
# string in a status API: either may contain provider payloads or source data.
_SAFE_FILE_PROCESSING_ERROR_MESSAGES = {
    EMBEDDING_IMAGE_FORMAT_UNSUPPORTED: (
        "Only PNG and JPEG images can be processed."
    ),
    EMBEDDING_IMAGE_INVALID: "The image file is invalid or could not be decoded.",
    VIDEO_VALIDATION_FAILED: "The video file is invalid or could not be validated.",
    VIDEO_DURATION_EXCEEDED: (
        "The video exceeds the maximum allowed duration."
    ),
    PDF_VISUAL_EXTRACTION_FAILED: "The PDF visual content could not be processed.",
    PDF_VISUAL_LIMIT_EXCEEDED: (
        "The PDF contains more visual content than the configured processing limit."
    ),
    FILE_PROCESSING_FAILED: "The file could not be processed.",
    EMBEDDING_MODALITY_UNSUPPORTED: (
        "The selected embedding model does not support this file's content type."
    ),
    PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL: (
        "This file contains visual content incompatible with the current embedding model."
    ),
    EMBEDDING_PROVIDER_FAILED: "The embedding provider could not process this file.",
    EMBEDDING_OUTPUT_COUNT_MISMATCH: (
        "The embedding provider returned an invalid number of results."
    ),
    EMBEDDING_DIMENSION_MISMATCH: (
        "The embedding provider returned vectors with an invalid dimension."
    ),
    EMBEDDING_VECTOR_NOT_SEQUENCE: "The embedding provider returned an invalid result.",
    EMBEDDING_VECTOR_VALUE_INVALID: "The embedding provider returned an invalid result.",
    EMBEDDING_VECTOR_NON_FINITE: "The embedding provider returned an invalid result.",
}

_GENERIC_FILE_PROCESSING_ERROR_MESSAGE = "The file could not be processed."

_PUBLIC_FILE_PROCESSING_ERROR_CODES = frozenset(
    {
        EMBEDDING_MODEL_NOT_CONFIGURED,
        EMBEDDING_MODEL_DISABLED,
        EMBEDDING_ADMIN_UNRESOLVED,
        EMBEDDING_ADMIN_AMBIGUOUS,
        EMBEDDING_CREDENTIALS_MISSING,
        EMBEDDING_PROVIDER_UNSUPPORTED,
        EMBEDDING_MODALITY_UNSUPPORTED,
        PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL,
        EMBEDDING_OUTPUT_COUNT_MISMATCH,
        EMBEDDING_VECTOR_NOT_SEQUENCE,
        EMBEDDING_VECTOR_VALUE_INVALID,
        EMBEDDING_VECTOR_NON_FINITE,
        EMBEDDING_DIMENSION_MISMATCH,
        EMBEDDING_PROVIDER_FAILED,
        EMBEDDING_IMAGE_FORMAT_UNSUPPORTED,
        EMBEDDING_IMAGE_INVALID,
        VIDEO_VALIDATION_FAILED,
        VIDEO_DURATION_EXCEEDED,
        PDF_VISUAL_EXTRACTION_FAILED,
        PDF_VISUAL_LIMIT_EXCEEDED,
        FILE_PROCESSING_FAILED,
        EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
        EMBEDDING_MODEL_SPACE_MIXED,
        EMBEDDING_MODEL_STATE_CONFLICT,
        EMBEDDING_FILE_NOT_FOUND,
        EMBEDDING_REINDEX_SOURCE_CHANGED,
    }
)

_PUBLIC_FILE_PROCESSING_WARNING_CODES = frozenset(
    {
        PDF_VISUAL_EXTRACTION_FAILED,
        PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL,
        "pdf_table_outside_visible_page",
    }
)


def safe_file_processing_error_message(code: Optional[str]) -> str:
    """Return a stable, allowlisted status message for an embedding error code."""

    return _SAFE_FILE_PROCESSING_ERROR_MESSAGES.get(
        code, _GENERIC_FILE_PROCESSING_ERROR_MESSAGE
    )


def safe_file_processing_error_code(code: Optional[str]) -> Optional[str]:
    """Return a public stable code, collapsing unknown values to one fallback."""
    if code is None:
        return None
    return code if code in _PUBLIC_FILE_PROCESSING_ERROR_CODES else FILE_PROCESSING_FAILED


def safe_file_processing_warnings(values) -> list[str]:
    """Deduplicate and allowlist durable warning codes for public responses."""
    if not isinstance(values, (list, tuple, set)):
        return []
    return list(
        dict.fromkeys(
            value
            for value in values
            if isinstance(value, str)
            and value in _PUBLIC_FILE_PROCESSING_WARNING_CODES
        )
    )
