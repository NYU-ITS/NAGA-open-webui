"""Legacy callable adapters for embedding-service consumers."""

from typing import Callable, Optional, Union

from .errors import EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED, EmbeddingError
from .inputs import EmbeddingBatch, TextEmbeddingInput
from .service import EmbeddingService


# The existing document-chunk vector column is fixed at 1536 dimensions.
CURRENT_DOCUMENT_CHUNK_DIMENSION = 1536


def _embed_batch(
    service: EmbeddingService,
    query: Union[str, list[str]],
    user,
    *,
    user_id: Optional[str],
    admin_id: Optional[str],
    embedding_model_id: Optional[str],
) -> EmbeddingBatch:
    texts = [query] if isinstance(query, str) else query
    inputs = [TextEmbeddingInput(text=text) for text in texts]

    if admin_id and embedding_model_id:
        return service.embed_for_frozen_context(inputs, admin_id, embedding_model_id)

    effective_user_id = user_id or (user.id if user else None)
    if not effective_user_id:
        raise EmbeddingError(
            "embedding_admin_unresolved",
            detail="No user_id available for embedding resolution.",
        )
    return service.embed_for_user(inputs, effective_user_id)


def _legacy_vectors(query: Union[str, list[str]], batch: EmbeddingBatch):
    if isinstance(query, str):
        return list(batch.vectors[0])
    return [list(vector) for vector in batch.vectors]


def validate_storage_dimension(batch: EmbeddingBatch) -> None:
    """Reject vectors that cannot fit the current document-chunk storage."""
    if batch.dimension != CURRENT_DOCUMENT_CHUNK_DIMENSION:
        raise EmbeddingError(
            EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
            detail=(
                f"Embedding dimension {batch.dimension} does not match document storage "
                f"dimension {CURRENT_DOCUMENT_CHUNK_DIMENSION}."
            ),
        )


def make_embedding_function(
    service: EmbeddingService,
    *,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> Callable:
    """Create a service-backed callable that preserves legacy return shapes."""

    def embed(query: Union[str, list[str]], user=None) -> Union[list[float], list[list[float]]]:
        batch = _embed_batch(
            service,
            query,
            user,
            user_id=user_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        return _legacy_vectors(query, batch)

    return embed


def get_user_embedding_function(config, user_id: str) -> Callable:
    """Create a user-context legacy embedding callable."""
    return make_embedding_function(EmbeddingService(config), user_id=user_id)


def make_embedding_function_with_storage_guard(
    service: EmbeddingService,
    *,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> Callable:
    """Create an ingestion callable that enforces document storage dimensions."""

    def embed_with_guard(
        query: Union[str, list[str]], user=None
    ) -> Union[list[float], list[list[float]]]:
        batch = _embed_batch(
            service,
            query,
            user,
            user_id=user_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        validate_storage_dimension(batch)
        return _legacy_vectors(query, batch)

    return embed_with_guard
