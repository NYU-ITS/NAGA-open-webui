"""Provider protocol and provider-factory protocol."""

from typing import Protocol, Sequence

from .inputs import EmbeddingInput, EmbeddingModelSpec


class EmbeddingProvider(Protocol):
    """
    Protocol for embedding providers.
    Implementations must accept only typed inputs and model specs.
    They must not expose credentials, SDK clients, or raw responses.
    """

    def embed(
        self, inputs: Sequence[EmbeddingInput], model: EmbeddingModelSpec
    ) -> Sequence[Sequence[float]]:
        """
        Generate embeddings for the given inputs.

        Args:
            inputs: Sequence of typed embedding inputs (text or image).
            model: Model specification with provider, model_name, and dimension.

        Returns:
            Sequence of embedding vectors, one per input.

        Raises:
            EmbeddingError: On provider failure, modality mismatch, or validation errors.
        """
        ...


class EmbeddingProviderFactory(Protocol):
    """
    Protocol for creating request-scoped embedding providers.
    Factories receive a credential for the provider call only;
    they do not store or expose it beyond the provider construction.
    """

    def create(self, model: EmbeddingModelSpec, credential: str) -> EmbeddingProvider:
        """
        Create a request-scoped embedding provider.

        Args:
            model: Model specification.
            credential: Provider-specific credential (API key, token, etc.).

        Returns:
            An EmbeddingProvider instance.

        Raises:
            EmbeddingError: If the provider is unsupported or creation fails.
        """
        ...
