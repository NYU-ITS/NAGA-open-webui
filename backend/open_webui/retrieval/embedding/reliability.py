"""Frozen operational policy for embedding-provider calls.

The policy is intentionally separate from :class:`PreparationRecipe`: changing
timeouts or retry limits changes execution reliability, not vector contents, and
therefore must never make an indexing recipe stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 10
DEFAULT_READ_TIMEOUT_SECONDS = 120
DEFAULT_AUDIO_SPLIT_MAX_DEPTH = 2
DEFAULT_AUDIO_SPLIT_MIN_DURATION_SECONDS = 5


def _config_value(config, name: str, default: Any) -> Any:
    value = getattr(config, name, default)
    return getattr(value, "value", value)


@dataclass(frozen=True)
class EmbeddingReliabilityPolicy:
    """Validated, JSON-safe snapshot used for one dispatched operation."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    connection_timeout_seconds: int = DEFAULT_CONNECTION_TIMEOUT_SECONDS
    read_timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS
    audio_split_max_depth: int = DEFAULT_AUDIO_SPLIT_MAX_DEPTH
    audio_split_min_duration_seconds: int = (
        DEFAULT_AUDIO_SPLIT_MIN_DURATION_SECONDS
    )
    backoff_base_seconds: float = 2.0
    jitter_ratio: float = 0.25
    retry_after_cap_seconds: int = 120

    def __post_init__(self) -> None:
        integer_fields = (
            self.max_attempts,
            self.connection_timeout_seconds,
            self.read_timeout_seconds,
            self.audio_split_max_depth,
            self.audio_split_min_duration_seconds,
            self.retry_after_cap_seconds,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_fields):
            raise ValueError("embedding reliability values must be integers")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("maximum attempts must be between 1 and 5")
        if not 1 <= self.connection_timeout_seconds <= 60:
            raise ValueError("connection timeout must be between 1 and 60 seconds")
        if not 30 <= self.read_timeout_seconds <= 600:
            raise ValueError("read timeout must be between 30 and 600 seconds")
        if not 0 <= self.audio_split_max_depth <= 4:
            raise ValueError("audio split depth must be between 0 and 4")
        if not 1 <= self.audio_split_min_duration_seconds <= 60:
            raise ValueError("audio split minimum duration must be between 1 and 60 seconds")
        if self.backoff_base_seconds <= 0:
            raise ValueError("backoff base must be positive")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter ratio must be between 0 and 1")
        if not 1 <= self.retry_after_cap_seconds <= 120:
            raise ValueError("Retry-After cap must be between 1 and 120 seconds")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_attempts": self.max_attempts,
            "connection_timeout_seconds": self.connection_timeout_seconds,
            "read_timeout_seconds": self.read_timeout_seconds,
            "audio_split_max_depth": self.audio_split_max_depth,
            "audio_split_min_duration_seconds": self.audio_split_min_duration_seconds,
            "backoff_base_seconds": self.backoff_base_seconds,
            "jitter_ratio": self.jitter_ratio,
            "retry_after_cap_seconds": self.retry_after_cap_seconds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "EmbeddingReliabilityPolicy":
        if not isinstance(value, Mapping):
            return cls()
        defaults = cls()
        return cls(
            max_attempts=value.get("max_attempts", defaults.max_attempts),
            connection_timeout_seconds=value.get(
                "connection_timeout_seconds", defaults.connection_timeout_seconds
            ),
            read_timeout_seconds=value.get(
                "read_timeout_seconds", defaults.read_timeout_seconds
            ),
            audio_split_max_depth=value.get(
                "audio_split_max_depth", defaults.audio_split_max_depth
            ),
            audio_split_min_duration_seconds=value.get(
                "audio_split_min_duration_seconds",
                defaults.audio_split_min_duration_seconds,
            ),
            backoff_base_seconds=value.get(
                "backoff_base_seconds", defaults.backoff_base_seconds
            ),
            jitter_ratio=value.get("jitter_ratio", defaults.jitter_ratio),
            retry_after_cap_seconds=value.get(
                "retry_after_cap_seconds", defaults.retry_after_cap_seconds
            ),
        )


def snapshot_reliability_policy(config) -> EmbeddingReliabilityPolicy:
    """Resolve mutable application settings into an immutable operation policy."""

    return EmbeddingReliabilityPolicy(
        max_attempts=int(
            _config_value(config, "RAG_EMBEDDING_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
        ),
        connection_timeout_seconds=int(
            _config_value(
                config,
                "RAG_EMBEDDING_CONNECTION_TIMEOUT",
                DEFAULT_CONNECTION_TIMEOUT_SECONDS,
            )
        ),
        read_timeout_seconds=int(
            _config_value(
                config,
                "RAG_EMBEDDING_READ_TIMEOUT",
                DEFAULT_READ_TIMEOUT_SECONDS,
            )
        ),
        audio_split_max_depth=int(
            _config_value(
                config,
                "RAG_EMBEDDING_AUDIO_SPLIT_MAX_DEPTH",
                DEFAULT_AUDIO_SPLIT_MAX_DEPTH,
            )
        ),
        audio_split_min_duration_seconds=int(
            _config_value(
                config,
                "RAG_EMBEDDING_AUDIO_SPLIT_MIN_DURATION",
                DEFAULT_AUDIO_SPLIT_MIN_DURATION_SECONDS,
            )
        ),
    )


__all__ = ["EmbeddingReliabilityPolicy", "snapshot_reliability_policy"]
