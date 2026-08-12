"""Immutable typed inputs, registry model view, and non-secret result types."""

from dataclasses import dataclass
from typing import Literal, Union


@dataclass(frozen=True)
class TextEmbeddingInput:
    """Text input for embedding generation."""

    text: str
    modality: Literal["text"] = "text"


@dataclass(frozen=True)
class ImageEmbeddingInput:
    """Image input for embedding generation."""

    image: bytes
    mime_type: Literal["image/png", "image/jpeg"]
    modality: Literal["image"] = "image"

    def __post_init__(self) -> None:
        if not isinstance(self.image, bytes):
            raise TypeError("image must be bytes")
        if self.mime_type not in ("image/png", "image/jpeg"):
            raise ValueError("mime_type must be image/png or image/jpeg")


# Union type for all embedding inputs
EmbeddingInput = Union[TextEmbeddingInput, ImageEmbeddingInput]


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """
    Detached view of an embedding model registry row.
    Contains no credentials, API keys, or connection details.
    """

    id: str
    provider: str
    model_name: str
    dimension: int
    modalities: frozenset[str]
    status: str


@dataclass(frozen=True)
class EmbeddingBatch:
    """
    Validated embedding result with non-secret provenance only.
    Contains no credentials, API keys, base URLs, or input text.
    """

    model_id: str
    provider: str
    dimension: int
    vectors: tuple[tuple[float, ...], ...]
