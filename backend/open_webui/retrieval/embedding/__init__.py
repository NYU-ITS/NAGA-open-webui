"""Embedding domain package: credential-free typed inputs, errors, and provider protocols."""

from .inputs import (
    TextEmbeddingInput,
    ImageEmbeddingInput,
    EmbeddingInput,
    EmbeddingModelSpec,
    EmbeddingBatch,
)
from .errors import (
    EmbeddingError,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_ADMIN_AMBIGUOUS,
    EMBEDDING_CREDENTIALS_MISSING,
    EMBEDDING_PROVIDER_UNSUPPORTED,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_OUTPUT_COUNT_MISMATCH,
    EMBEDDING_VECTOR_NOT_SEQUENCE,
    EMBEDDING_VECTOR_VALUE_INVALID,
    EMBEDDING_VECTOR_NON_FINITE,
    EMBEDDING_DIMENSION_MISMATCH,
    EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_MODEL_SPACE_MIXED,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
    EMBEDDING_INVENTORY_MISSING_FILE,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
    EMBEDDING_JOB_ACTIVE_EXISTS,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_TERMINAL,
    EMBEDDING_JOB_WRONG_STATUS,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_FILE_WRONG_STATUS,
)
from .provider import EmbeddingProvider, EmbeddingProviderFactory
from .state import (
    AdminEmbeddingModelStateView,
    AdminEmbeddingModelStateRepository,
)
from .inventory import (
    ReindexFile,
    build_reindex_inventory,
    SOURCE_KNOWLEDGE,
    SOURCE_CHAT_UPLOAD,
)
from .jobs import (
    EmbeddingJobView,
    EmbeddingJobFileView,
    CreateJobResult,
    EmbeddingJobRepository,
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
    FILE_STATUS_PENDING,
    FILE_STATUS_PROCESSING,
    FILE_STATUS_COMPLETED,
    FILE_STATUS_FAILED,
)
from .model_change import (
    ModelChangeResult,
    ModelChangeNoOp,
    request_model_change,
)
from .worker import process_embedding_job
from .enqueue import (
    enqueue_embedding_job,
    EMBEDDING_REINDEX_QUEUE_NAME,
)

__all__ = [
    # Inputs
    "TextEmbeddingInput",
    "ImageEmbeddingInput",
    "EmbeddingInput",
    "EmbeddingModelSpec",
    "EmbeddingBatch",
    # Errors
    "EmbeddingError",
    "EMBEDDING_MODEL_NOT_CONFIGURED",
    "EMBEDDING_MODEL_DISABLED",
    "EMBEDDING_ADMIN_UNRESOLVED",
    "EMBEDDING_ADMIN_AMBIGUOUS",
    "EMBEDDING_CREDENTIALS_MISSING",
    "EMBEDDING_PROVIDER_UNSUPPORTED",
    "EMBEDDING_MODALITY_UNSUPPORTED",
    "EMBEDDING_OUTPUT_COUNT_MISMATCH",
    "EMBEDDING_VECTOR_NOT_SEQUENCE",
    "EMBEDDING_VECTOR_VALUE_INVALID",
    "EMBEDDING_VECTOR_NON_FINITE",
    "EMBEDDING_DIMENSION_MISMATCH",
    "EMBEDDING_PROVIDER_FAILED",
    "EMBEDDING_MODEL_SPACE_MIXED",
    "EMBEDDING_MODEL_STATE_CONFLICT",
    "EMBEDDING_INVENTORY_UNRESOLVED_SOURCE",
    "EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE",
    "EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN",
    "EMBEDDING_INVENTORY_MISSING_FILE",
    "EMBEDDING_INVENTORY_MALFORMED_REFERENCE",
    "EMBEDDING_JOB_ACTIVE_EXISTS",
    "EMBEDDING_JOB_NOT_FOUND",
    "EMBEDDING_JOB_TERMINAL",
    "EMBEDDING_JOB_WRONG_STATUS",
    "EMBEDDING_FILE_NOT_FOUND",
    "EMBEDDING_FILE_WRONG_STATUS",
    # State
    "AdminEmbeddingModelStateView",
    "AdminEmbeddingModelStateRepository",
    # Inventory
    "ReindexFile",
    "build_reindex_inventory",
    "SOURCE_KNOWLEDGE",
    "SOURCE_CHAT_UPLOAD",
    # Protocols
    "EmbeddingProvider",
    "EmbeddingProviderFactory",
    # Jobs
    "EmbeddingJobView",
    "EmbeddingJobFileView",
    "CreateJobResult",
    "EmbeddingJobRepository",
    "JOB_STATUS_QUEUED",
    "JOB_STATUS_PROCESSING",
    "JOB_STATUS_COMPLETED",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_PARTIALLY_FAILED",
    "FILE_STATUS_PENDING",
    "FILE_STATUS_PROCESSING",
    "FILE_STATUS_COMPLETED",
    "FILE_STATUS_FAILED",
    # Model Change
    "ModelChangeResult",
    "ModelChangeNoOp",
    "request_model_change",
    # Enqueue
    "enqueue_embedding_job",
    "EMBEDDING_REINDEX_QUEUE_NAME",
    # Worker
    "process_embedding_job",
]
