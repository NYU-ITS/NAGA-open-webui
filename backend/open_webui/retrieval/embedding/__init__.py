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
)
from .provider import EmbeddingProvider, EmbeddingProviderFactory
from .state import (
    AdminEmbeddingModelStateView,
    AdminEmbeddingModelStateRepository,
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
    # State
    "AdminEmbeddingModelStateView",
    "AdminEmbeddingModelStateRepository",
    # Protocols
    "EmbeddingProvider",
    "EmbeddingProviderFactory",
]
