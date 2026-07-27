"""Legacy single/list callable adaptation plus legacy storage-dimension guard."""

import logging
from typing import Callable, Optional, Union

from .inputs import TextEmbeddingInput, EmbeddingBatch
from .service import EmbeddingService, validate_storage_dimension
from .errors import EmbeddingError

log = logging.getLogger(__name__)


def make_embedding_function(
    service: EmbeddingService,
    *,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> Callable:
    """
    Create a service-backed embedding callable that preserves legacy return shapes.
    
    The callable accepts either a single string or a list of strings,
    and returns either a single vector or a list of vectors.
    
    Args:
        service: The EmbeddingService instance.
        user_id: User ID for user-context resolution.
        admin_id: Admin ID for frozen-context resolution.
        embedding_model_id: Embedding model ID for frozen-context resolution.
        
    Returns:
        A callable with the legacy signature: embed(query, user=None) -> list[float] | list[list[float]]
    """
    def embed(query: Union[str, list[str]], user=None) -> Union[list[float], list[list[float]]]:
        """
        Generate embeddings using the service.
        
        Args:
            query: Single string or list of strings to embed.
            user: Optional user object (for compatibility).
            
        Returns:
            Single vector if query is string, list of vectors if query is list.
        """
        # Convert to list for uniform processing
        texts = [query] if isinstance(query, str) else query
        
        # Create typed inputs
        inputs = [TextEmbeddingInput(text=text) for text in texts]
        
        # Determine which service entry point to use
        if admin_id and embedding_model_id:
            batch = service.embed_for_frozen_context(inputs, admin_id, embedding_model_id)
        else:
            # Use user_id or user.id
            effective_user_id = user_id or (user.id if user else None)
            if not effective_user_id:
                raise EmbeddingError(
                    "embedding_admin_unresolved",
                    detail="No user_id available for embedding resolution.",
                )
            batch = service.embed_for_user(inputs, effective_user_id)
        
        # Return in legacy format
        if isinstance(query, str):
            return list(batch.vectors[0])
        else:
            return [list(v) for v in batch.vectors]
    
    return embed


def get_user_embedding_function(config, user_id: str) -> Callable:
    """
    Convenience wrapper: create an EmbeddingService from config and return
    a legacy-compatible embedding callable for the given user.

    Intended for thin callers (routers, middleware) that only need
    ``embedding_function(text) -> vector`` and don't want to know about
    EmbeddingService internals.

    Args:
        config: The app config (request.app.state.config).
        user_id: The resolved user ID.

    Returns:
        A callable with the legacy signature.
    """
    service = EmbeddingService(config)
    return make_embedding_function(service, user_id=user_id)


def make_embedding_function_with_storage_guard(
    service: EmbeddingService,
    *,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> Callable:
    """
    Create a service-backed embedding callable with storage dimension validation.
    
    This is used for ingestion paths where the validated batch must match
    the storage dimension (1536).
    
    Args:
        service: The EmbeddingService instance.
        user_id: User ID for user-context resolution.
        admin_id: Admin ID for frozen-context resolution.
        embedding_model_id: Embedding model ID for frozen-context resolution.
        
    Returns:
        A callable with the legacy signature.
    """
    base_func = make_embedding_function(
        service,
        user_id=user_id,
        admin_id=admin_id,
        embedding_model_id=embedding_model_id,
    )
    
    def embed_with_guard(query: Union[str, list[str]], user=None) -> Union[list[float], list[list[float]]]:
        """
        Generate embeddings with storage dimension validation.
        
        Args:
            query: Single string or list of strings to embed.
            user: Optional user object (for compatibility).
            
        Returns:
            Single vector if query is string, list of vectors if query is list.
            
        Raises:
            EmbeddingError: If dimension doesn't match storage dimension.
        """
        # For storage guard, we need to validate the batch dimension
        # This is done by calling the service directly
        texts = [query] if isinstance(query, str) else query
        inputs = [TextEmbeddingInput(text=text) for text in texts]
        
        if admin_id and embedding_model_id:
            batch = service.embed_for_frozen_context(inputs, admin_id, embedding_model_id)
        else:
            effective_user_id = user_id or (user.id if user else None)
            if not effective_user_id:
                raise EmbeddingError(
                    "embedding_admin_unresolved",
                    detail="No user_id available for embedding resolution.",
                )
            batch = service.embed_for_user(inputs, effective_user_id)
        
        # Validate storage dimension
        validate_storage_dimension(batch)
        
        # Return in legacy format
        if isinstance(query, str):
            return list(batch.vectors[0])
        else:
            return [list(v) for v in batch.vectors]
    
    return embed_with_guard
