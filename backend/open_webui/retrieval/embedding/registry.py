"""Enabled model lookup and model-ID lookup from embedding_models."""

import logging
from typing import Optional

from open_webui.models.embeddings import EmbeddingModel
from .inputs import EmbeddingModelSpec
from .errors import (
    EmbeddingError,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_DISABLED,
)

log = logging.getLogger(__name__)


def to_spec(row: EmbeddingModel) -> EmbeddingModelSpec:
    """
    Convert an EmbeddingModel ORM row to a detached EmbeddingModelSpec.
    The spec contains no credentials, API keys, or connection details.
    """
    return EmbeddingModelSpec(
        id=row.id,
        provider=row.provider,
        model_name=row.model_name,
        dimension=row.dimension,
        modalities=frozenset(row.modalities),
        status=row.status,
    )


def get_model_spec_by_name(model_name: str) -> EmbeddingModelSpec:
    """
    Look up an enabled embedding model by its model_name.
    
    Args:
        model_name: The model_name field from the embedding_models table.
        
    Returns:
        EmbeddingModelSpec for the enabled model.
        
    Raises:
        EmbeddingError: If model not found or not enabled.
    """
    row = EmbeddingModel.get_model_by_name(model_name)
    if row is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_NOT_CONFIGURED,
            detail=f"Embedding model '{model_name}' not found in registry.",
        )
    if row.status != "enabled":
        raise EmbeddingError(
            EMBEDDING_MODEL_DISABLED,
            detail=f"Embedding model '{model_name}' is not enabled (status={row.status}).",
        )
    return to_spec(row)


def get_model_spec_by_id(model_id: str) -> EmbeddingModelSpec:
    """
    Look up an enabled embedding model by its ID.
    
    Args:
        model_id: The id field from the embedding_models table.
        
    Returns:
        EmbeddingModelSpec for the enabled model.
        
    Raises:
        EmbeddingError: If model not found or not enabled.
    """
    row = EmbeddingModel.get_model_by_id(model_id)
    if row is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_NOT_CONFIGURED,
            detail=f"Embedding model with id '{model_id}' not found in registry.",
        )
    if row.status != "enabled":
        raise EmbeddingError(
            EMBEDDING_MODEL_DISABLED,
            detail=f"Embedding model with id '{model_id}' is not enabled (status={row.status}).",
        )
    return to_spec(row)


def list_enabled_models() -> list[EmbeddingModelSpec]:
    """
    List all enabled embedding models.
    
    Returns:
        List of EmbeddingModelSpec for all enabled models.
    """
    rows = EmbeddingModel.get_enabled_models()
    return [to_spec(row) for row in rows]
