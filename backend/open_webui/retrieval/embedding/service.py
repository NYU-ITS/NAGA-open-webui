"""EmbeddingService: modality gate, provider selection, provider call, and full response validation."""

import logging
import math
import numbers
from typing import Sequence, Optional

from .inputs import (
    EmbeddingInput,
    TextEmbeddingInput,
    ImageEmbeddingInput,
    EmbeddingModelSpec,
    EmbeddingBatch,
)
from .errors import (
    EmbeddingError,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_CREDENTIALS_MISSING,
    EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_OUTPUT_COUNT_MISMATCH,
    EMBEDDING_VECTOR_NOT_SEQUENCE,
    EMBEDDING_VECTOR_VALUE_INVALID,
    EMBEDDING_VECTOR_NON_FINITE,
    EMBEDDING_DIMENSION_MISMATCH,
)
from .provider import EmbeddingProvider, EmbeddingProviderFactory
from .providers.portkey import PortkeyEmbeddingProvider
from .resolution import (
    EmbeddingExecutionContext,
    resolve_for_user,
    resolve_for_admin_id,
    resolve_frozen,
    resolve_credential_for_admin,
    resolve_base_url_for_admin,
)

log = logging.getLogger(__name__)

# Phase 2 storage dimension constant
CURRENT_DOCUMENT_CHUNK_DIMENSION = 1536


class EmbeddingService:
    """
    Embedding service that handles modality gating, provider selection,
    provider invocation, and output validation.
    
    Credentials are obtained only after provider selection and are not
    exposed beyond the provider call.
    """
    
    def __init__(self, config):
        """
        Initialize the embedding service.
        
        Args:
            config: The app config (request.app.state.config).
        """
        self._config = config
    
    def embed_for_user(self, inputs: Sequence[EmbeddingInput], user_id: str) -> EmbeddingBatch:
        """
        Generate embeddings for a user.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            user_id: The user ID to resolve admin/model for.
            
        Returns:
            EmbeddingBatch with validated vectors.
            
        Raises:
            EmbeddingError: On resolution, modality, provider, or validation errors.
        """
        context = resolve_for_user(user_id, self._config)
        return self._embed(inputs, context)
    
    def embed_for_admin_id(self, inputs: Sequence[EmbeddingInput], admin_id: str) -> EmbeddingBatch:
        """
        Generate embeddings for a known admin ID.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            admin_id: The admin user ID.
            
        Returns:
            EmbeddingBatch with validated vectors.
            
        Raises:
            EmbeddingError: On resolution, modality, provider, or validation errors.
        """
        context = resolve_for_admin_id(admin_id, self._config)
        return self._embed(inputs, context)
    
    def embed_for_frozen_context(
        self,
        inputs: Sequence[EmbeddingInput],
        admin_id: str,
        embedding_model_id: str,
    ) -> EmbeddingBatch:
        """
        Generate embeddings from a frozen (enqueued) context.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            admin_id: The frozen admin user ID.
            embedding_model_id: The frozen embedding model ID.
            
        Returns:
            EmbeddingBatch with validated vectors.
            
        Raises:
            EmbeddingError: On resolution, modality, provider, or validation errors.
        """
        context = resolve_frozen(admin_id, embedding_model_id)
        return self._embed(inputs, context)
    
    def _embed(
        self,
        inputs: Sequence[EmbeddingInput],
        context: EmbeddingExecutionContext,
    ) -> EmbeddingBatch:
        """
        Internal embedding method that handles the full pipeline.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            context: The embedding execution context.
            
        Returns:
            EmbeddingBatch with validated vectors.
            
        Raises:
            EmbeddingError: On modality, credential, provider, or validation errors.
        """
        # Gate modalities before resolving credential or calling provider
        self._check_modalities(inputs, context.model)
        
        # Resolve credential only after modality check passes
        admin = self._resolve_admin(context.admin_id)
        credential = resolve_credential_for_admin(admin.email, context.model, self._config)
        base_url = resolve_base_url_for_admin(context.model, self._config)
        
        # Create request-scoped provider
        provider = self._create_provider(context.model, credential, base_url)
        
        # Call provider
        raw_vectors = provider.embed(inputs, context.model)
        
        # Validate vectors
        validate_vectors(raw_vectors, len(inputs), context.model)
        
        # Build result with non-secret provenance only
        vectors = tuple(tuple(float(v) for v in vec) for vec in raw_vectors)
        
        return EmbeddingBatch(
            model_id=context.model.id,
            provider=context.model.provider,
            dimension=context.model.dimension,
            vectors=vectors,
        )
    
    def _check_modalities(self, inputs: Sequence[EmbeddingInput], model: EmbeddingModelSpec):
        """
        Check that all input modalities are supported by the model.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            model: The embedding model spec.
            
        Raises:
            EmbeddingError: If any input modality is not supported.
        """
        for item in inputs:
            if item.modality not in model.modalities:
                raise EmbeddingError(
                    EMBEDDING_MODALITY_UNSUPPORTED,
                    detail=f"Model '{model.model_name}' does not support '{item.modality}' modality.",
                )
    
    def _resolve_admin(self, admin_id: str):
        """
        Resolve admin user by ID.
        
        Args:
            admin_id: The admin user ID.
            
        Returns:
            The admin user object.
            
        Raises:
            EmbeddingError: If admin cannot be resolved.
        """
        from open_webui.models.users import Users
        
        admin = Users.get_user_by_id(admin_id)
        if admin is None:
            raise EmbeddingError(
                EMBEDDING_CREDENTIALS_MISSING,
                detail=f"Admin {admin_id} not found.",
            )
        
        if admin.role != "admin":
            raise EmbeddingError(
                EMBEDDING_CREDENTIALS_MISSING,
                detail=f"User {admin_id} is not an admin.",
            )
        
        return admin
    
    def _create_provider(
        self,
        model: EmbeddingModelSpec,
        credential: str,
        base_url: str,
    ) -> EmbeddingProvider:
        """
        Create a request-scoped provider based on the model's provider field.
        
        Args:
            model: The embedding model spec.
            credential: The provider-specific credential.
            base_url: The provider-specific base URL.
            
        Returns:
            An EmbeddingProvider instance.
            
        Raises:
            EmbeddingError: If provider is unsupported.
        """
        if model.provider == "portkey":
            return PortkeyEmbeddingProvider(base_url=base_url, credential=credential)
        else:
            raise EmbeddingError(
                EMBEDDING_PROVIDER_UNSUPPORTED,
                detail=f"Unsupported provider: {model.provider}.",
            )


def validate_vectors(
    raw_vectors: Sequence[Sequence[float]],
    input_count: int,
    model: EmbeddingModelSpec,
):
    """
    Validate embedding vectors before storage.
    
    Rejects:
    - None and wrong count
    - String/bytes vectors
    - Wrong dimension
    - bool, non-numeric, and non-finite values
    
    Args:
        raw_vectors: The raw vectors from the provider.
        input_count: Expected number of vectors.
        model: The embedding model spec (for dimension check).
        
    Raises:
        EmbeddingError: On any validation failure.
    """
    if raw_vectors is None:
        raise EmbeddingError(
            EMBEDDING_OUTPUT_COUNT_MISMATCH,
            detail="Provider returned None vectors.",
        )
    
    if len(raw_vectors) != input_count:
        raise EmbeddingError(
            EMBEDDING_OUTPUT_COUNT_MISMATCH,
            detail=f"Expected {input_count} vectors, got {len(raw_vectors)}.",
        )
    
    for i, raw_vector in enumerate(raw_vectors):
        # Reject string/bytes vectors
        if isinstance(raw_vector, (str, bytes)):
            raise EmbeddingError(
                EMBEDDING_VECTOR_NOT_SEQUENCE,
                detail=f"Vector {i} is a string/bytes, expected sequence.",
            )
        
        # Reject non-sequence vectors
        if not isinstance(raw_vector, Sequence):
            raise EmbeddingError(
                EMBEDDING_VECTOR_NOT_SEQUENCE,
                detail=f"Vector {i} is not a sequence.",
            )
        
        # Check dimension
        if len(raw_vector) != model.dimension:
            raise EmbeddingError(
                EMBEDDING_DIMENSION_MISMATCH,
                detail=f"Vector {i} has dimension {len(raw_vector)}, expected {model.dimension}.",
            )
        
        # Validate each value
        for j, value in enumerate(raw_vector):
            # Reject bool values (before numeric check since bool is subclass of int)
            if isinstance(value, bool):
                raise EmbeddingError(
                    EMBEDDING_VECTOR_VALUE_INVALID,
                    detail=f"Vector {i}[{j}] is a boolean.",
                )
            
            # Reject non-numeric values
            if not isinstance(value, numbers.Real):
                raise EmbeddingError(
                    EMBEDDING_VECTOR_VALUE_INVALID,
                    detail=f"Vector {i}[{j}] is not numeric.",
                )
            
            # Reject non-finite values
            try:
                if not math.isfinite(float(value)):
                    raise EmbeddingError(
                        EMBEDDING_VECTOR_NON_FINITE,
                        detail=f"Vector {i}[{j}] is not finite.",
                    )
            except (TypeError, ValueError) as e:
                raise EmbeddingError(
                    EMBEDDING_VECTOR_VALUE_INVALID,
                    detail=f"Vector {i}[{j}] cannot be converted to float.",
                )


def validate_storage_dimension(batch: EmbeddingBatch):
    """
    Validate that the batch dimension matches the storage dimension.
    
    Args:
        batch: The embedding batch to validate.
        
    Raises:
        EmbeddingError: If dimension doesn't match storage dimension.
    """
    if batch.dimension != CURRENT_DOCUMENT_CHUNK_DIMENSION:
        raise EmbeddingError(
            EMBEDDING_DIMENSION_MISMATCH,
            detail=f"Embedding dimension {batch.dimension} does not match storage dimension {CURRENT_DOCUMENT_CHUNK_DIMENSION}.",
        )
