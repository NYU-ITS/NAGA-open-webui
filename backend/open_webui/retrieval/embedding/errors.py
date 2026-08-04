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
EMBEDDING_JOB_TERMINAL = "embedding_job_terminal"
EMBEDDING_JOB_WRONG_STATUS = "embedding_job_wrong_status"
EMBEDDING_FILE_NOT_FOUND = "embedding_file_not_found"
EMBEDDING_FILE_WRONG_STATUS = "embedding_file_wrong_status"
EMBEDDING_REINDEX_NOT_READY = "embedding_reindex_not_ready"
EMBEDDING_REINDEX_SOURCE_CHANGED = "embedding_reindex_source_changed"
EMBEDDING_RETRY_ACTIVE_EXISTS = "embedding_retry_active_exists"
