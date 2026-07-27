"""Portkey-only request normalization and sanitized provider failure translation."""

import logging
from typing import Sequence

from ..inputs import EmbeddingInput, TextEmbeddingInput, ImageEmbeddingInput, EmbeddingModelSpec
from ..errors import (
    EmbeddingError,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_CREDENTIALS_MISSING,
)

log = logging.getLogger(__name__)

# Try to import Portkey SDK
try:
    from portkey_ai import Portkey
    PORTKEY_SDK_AVAILABLE = True
except ImportError:
    PORTKEY_SDK_AVAILABLE = False


class PortkeyEmbeddingProvider:
    """
    Request-scoped Portkey embedding provider.
    
    Accepts base URL and credential in constructor.
    Creates a new Portkey client per request to avoid credential leakage.
    """
    
    def __init__(self, base_url: str, credential: str):
        if not PORTKEY_SDK_AVAILABLE:
            raise EmbeddingError(
                EMBEDDING_PROVIDER_FAILED,
                detail="Portkey SDK (portkey_ai) is not installed.",
            )
        
        if not base_url or not base_url.strip():
            raise EmbeddingError(
                EMBEDDING_CREDENTIALS_MISSING,
                detail="Portkey base URL is empty.",
            )
        
        if not credential or not credential.strip():
            raise EmbeddingError(
                EMBEDDING_CREDENTIALS_MISSING,
                detail="Portkey credential is empty.",
            )
        
        self._base_url = base_url
        self._credential = credential
    
    def embed(
        self, inputs: Sequence[EmbeddingInput], model: EmbeddingModelSpec
    ) -> Sequence[Sequence[float]]:
        """
        Generate embeddings using Portkey SDK.
        
        Args:
            inputs: Sequence of typed embedding inputs.
            model: Model specification.
            
        Returns:
            Sequence of embedding vectors.
            
        Raises:
            EmbeddingError: On modality mismatch or provider failure.
        """
        # Gate modalities before calling provider
        for item in inputs:
            if not isinstance(item, TextEmbeddingInput):
                raise EmbeddingError(
                    EMBEDDING_MODALITY_UNSUPPORTED,
                    detail=f"Portkey provider only supports text inputs, got {type(item).__name__}.",
                )
        
        try:
            # Create request-scoped Portkey client
            # Note: Portkey SDK may accept dimensions parameter, but we verify at service level
            portkey = Portkey(
                base_url=self._base_url,
                api_key=self._credential,
            )
            
            # Extract text from inputs
            texts = [item.text for item in inputs]
            
            # Call the embeddings API
            response = portkey.embeddings.create(
                model=model.model_name,
                input=texts,
            )
            
            # Extract embeddings from response
            embeddings = [item.embedding for item in response.data]
            
            # Validate count
            if len(embeddings) != len(inputs):
                raise EmbeddingError(
                    EMBEDDING_PROVIDER_FAILED,
                    detail=f"Embedding count mismatch: expected {len(inputs)}, got {len(embeddings)}.",
                )
            
            return embeddings
            
        except EmbeddingError:
            # Re-raise our own errors
            raise
        except Exception:
            # Sanitize all provider errors to stable code
            log.error("embedding_provider_failed provider=portkey model_id=%s", model.id)
            raise EmbeddingError(
                EMBEDDING_PROVIDER_FAILED,
                detail="Portkey embedding generation failed.",
            ) from None


class PortkeyEmbeddingProviderFactory:
    """Factory for creating Portkey embedding providers."""
    
    def create(self, model: EmbeddingModelSpec, credential: str) -> PortkeyEmbeddingProvider:
        """
        Create a Portkey embedding provider.
        
        Args:
            model: Model specification.
            credential: Portkey API key.
            
        Returns:
            PortkeyEmbeddingProvider instance.
        """
        return PortkeyEmbeddingProvider(
            base_url=self._resolve_base_url(model),
            credential=credential,
        )
    
    def _resolve_base_url(self, model: EmbeddingModelSpec) -> str:
        """
        Resolve the Portkey base URL.
        This is a placeholder - actual resolution happens in resolution.py.
        """
        # This should be overridden by the actual resolution logic
        return "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
