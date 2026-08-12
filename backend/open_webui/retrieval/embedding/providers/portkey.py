"""Portkey request normalization and sanitized provider failure translation."""

import base64
import logging
from typing import Any, Sequence

import requests

from ..inputs import (
    EmbeddingInput,
    TextEmbeddingInput,
    ImageEmbeddingInput,
    EmbeddingModelSpec,
)
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
        if not inputs:
            return []

        if all(
            isinstance(item, TextEmbeddingInput) for item in inputs
        ) and model.modalities == frozenset({"text"}):
            return self._embed_text_with_sdk(inputs, model)

        return self._embed_multimodal(inputs, model)

    def _embed_text_with_sdk(
        self,
        inputs: Sequence[TextEmbeddingInput],
        model: EmbeddingModelSpec,
    ) -> Sequence[Sequence[float]]:
        """Preserve the existing SDK path for registered text-only models."""
        try:
            portkey = Portkey(
                base_url=self._base_url,
                api_key=self._credential,
            )
            texts = [item.text for item in inputs]
            response = portkey.embeddings.create(
                model=model.model_name,
                input=texts,
                encoding_format="float",
            )
            embeddings = [item.embedding for item in response.data]
            if len(embeddings) != len(inputs):
                raise EmbeddingError(
                    EMBEDDING_PROVIDER_FAILED,
                    detail="The embedding provider returned an unexpected number of vectors.",
                )
            return embeddings
        except EmbeddingError:
            raise
        except Exception as error:
            self._raise_provider_failure(model, error)

    def _embed_multimodal(
        self,
        inputs: Sequence[EmbeddingInput],
        model: EmbeddingModelSpec,
    ) -> Sequence[Sequence[float]]:
        """Embed mixed text/image inputs while preserving their logical order.

        Text inputs are sent in one request. Vertex multimodal embeddings accept
        one image instance per request, so images are deliberately serialized.
        Base64 encoding is confined to this adapter and never leaves it in an
        exception or durable record.
        """
        indexed_texts = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, TextEmbeddingInput)
        ]
        indexed_images = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, ImageEmbeddingInput)
        ]
        if len(indexed_texts) + len(indexed_images) != len(inputs):
            raise EmbeddingError(
                EMBEDDING_MODALITY_UNSUPPORTED,
                detail="The Portkey provider received an unsupported embedding input.",
            )

        ordered: list[Sequence[float] | None] = [None] * len(inputs)
        try:
            if indexed_texts:
                text_vectors = self._post_embeddings(
                    {
                        "model": model.model_name,
                        "input": [item.text for _, item in indexed_texts],
                        "dimensions": model.dimension,
                        "encoding_format": "float",
                    },
                    expected_modality="text",
                )
                if len(text_vectors) != len(indexed_texts):
                    raise EmbeddingError(
                        EMBEDDING_PROVIDER_FAILED,
                        detail="The embedding provider returned an unexpected number of vectors.",
                    )
                for (index, _), vector in zip(indexed_texts, text_vectors):
                    ordered[index] = vector

            for index, item in indexed_images:
                image_vectors = self._post_embeddings(
                    {
                        "model": model.model_name,
                        "input": [
                            {
                                "text": "",
                                "image": {
                                    "base64": base64.b64encode(item.image).decode(
                                        "ascii"
                                    ),
                                    "mimeType": item.mime_type,
                                },
                            }
                        ],
                        "dimensions": model.dimension,
                        "encoding_format": "float",
                    },
                    expected_modality="image",
                )
                if len(image_vectors) != 1:
                    raise EmbeddingError(
                        EMBEDDING_PROVIDER_FAILED,
                        detail="The embedding provider returned an unexpected number of vectors.",
                    )
                ordered[index] = image_vectors[0]

            if any(vector is None for vector in ordered):
                raise EmbeddingError(
                    EMBEDDING_PROVIDER_FAILED,
                    detail="The embedding provider returned an incomplete response.",
                )
            return [vector for vector in ordered if vector is not None]
        except EmbeddingError:
            raise
        except Exception as error:
            self._raise_provider_failure(model, error)

    def _post_embeddings(
        self,
        payload: dict[str, Any],
        *,
        expected_modality: str,
    ) -> list[Sequence[float]]:
        response = requests.post(
            f"{self._base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {self._credential}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        return self._parse_embedding_response(
            response.json(), expected_modality=expected_modality
        )

    @staticmethod
    def _parse_embedding_response(
        response: dict[str, Any],
        *,
        expected_modality: str,
    ) -> list[Sequence[float]]:
        data = response.get("data")
        if isinstance(data, list):
            vectors = [
                item.get("embedding")
                for item in data
                if isinstance(item, dict) and item.get("embedding") is not None
            ]
            if vectors:
                return vectors

        predictions = response.get("predictions")
        if isinstance(predictions, list):
            field = (
                "imageEmbedding" if expected_modality == "image" else "textEmbedding"
            )
            vectors = [
                item.get(field)
                for item in predictions
                if isinstance(item, dict) and item.get(field) is not None
            ]
            if vectors:
                return vectors

        raise EmbeddingError(
            EMBEDDING_PROVIDER_FAILED,
            detail="The embedding provider returned an unsupported response shape.",
        )

    @staticmethod
    def _raise_provider_failure(model: EmbeddingModelSpec, error: Exception):
        log.error(
            "embedding_provider_failed provider=portkey model_id=%s error_type=%s",
            model.id,
            type(error).__name__,
        )
        raise EmbeddingError(
            EMBEDDING_PROVIDER_FAILED,
            detail="Portkey embedding generation failed.",
        ) from None


class PortkeyEmbeddingProviderFactory:
    """Factory for creating Portkey embedding providers."""

    def create(
        self, model: EmbeddingModelSpec, credential: str
    ) -> PortkeyEmbeddingProvider:
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
