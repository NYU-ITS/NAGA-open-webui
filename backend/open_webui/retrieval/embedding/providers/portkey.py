"""Portkey request normalization and sanitized provider failure translation."""

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import random
import time
import uuid
from typing import Any, Mapping, Sequence

import requests

from ..inputs import (
    EmbeddingInput,
    TextEmbeddingInput,
    AudioEmbeddingInput,
    ImageEmbeddingInput,
    VideoEmbeddingInput,
    EmbeddingModelSpec,
)
from ..errors import (
    EmbeddingError,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_CREDENTIALS_MISSING,
)
from ..reliability import EmbeddingReliabilityPolicy
from open_webui.utils.otel_instrumentation import (
    add_metric_counter,
    record_metric_histogram,
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

    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        reliability_policy: EmbeddingReliabilityPolicy | None = None,
        call_context: Mapping[str, Any] | None = None,
    ):
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
        self._policy = reliability_policy or EmbeddingReliabilityPolicy()
        self._call_context = dict(call_context or {})
        context_call_id = self._call_context.get("call_id")
        self._call_id = (
            self._safe_identifier(context_call_id)
            if isinstance(context_call_id, str)
            else None
        ) or str(uuid.uuid4())

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

        self._model_id = model.id
        self._payload_size_bytes = sum(self._input_size(item) for item in inputs)

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
        """Use the same bounded HTTP path as every other modality."""
        with requests.Session() as session:
            texts = [item.text for item in inputs]
            vectors = self._post_embeddings(
                {
                    "model": model.model_name,
                    "input": texts,
                    "dimensions": model.dimension,
                    "encoding_format": "float",
                },
                expected_modality="text",
                session=session,
            )
        if len(vectors) != len(inputs):
            raise EmbeddingError(
                EMBEDDING_PROVIDER_FAILED,
                detail="The embedding provider returned an unexpected number of vectors.",
            )
        return vectors

    def _embed_multimodal(
        self,
        inputs: Sequence[EmbeddingInput],
        model: EmbeddingModelSpec,
    ) -> Sequence[Sequence[float]]:
        """Embed mixed text/audio/image/video inputs in logical order.

        The approved Vertex multimodal gateway contract returns one embedding
        per request, even when ``input`` contains multiple text entries. Send
        every logical input separately and restore the caller's original order.
        Raw audio uses the same base64 media contract as image and video input.
        One HTTP session retains connection reuse without persisting credentials
        or provider responses.

        Base64 encoding is confined to this adapter and never leaves it in an
        exception or durable record.
        """
        indexed_texts = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, TextEmbeddingInput)
        ]
        indexed_audio = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, AudioEmbeddingInput)
        ]
        indexed_images = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, ImageEmbeddingInput)
        ]
        indexed_videos = [
            (index, item)
            for index, item in enumerate(inputs)
            if isinstance(item, VideoEmbeddingInput)
        ]
        if (
            len(indexed_texts)
            + len(indexed_audio)
            + len(indexed_images)
            + len(indexed_videos)
            != len(inputs)
        ):
            raise EmbeddingError(
                EMBEDDING_MODALITY_UNSUPPORTED,
                detail="The Portkey provider received an unsupported embedding input.",
            )

        ordered: list[Sequence[float] | None] = [None] * len(inputs)
        try:
            with requests.Session() as session:
                for index, item in indexed_texts:
                    self._payload_size_bytes = self._input_size(item)
                    ordered[index] = self._post_single_embedding(
                        session,
                        {
                            "model": model.model_name,
                            "input": [item.text],
                            "dimensions": model.dimension,
                            "encoding_format": "float",
                        },
                        expected_modality="text",
                    )

                for index, item in indexed_audio:
                    self._payload_size_bytes = self._input_size(item)
                    ordered[index] = self._post_single_embedding(
                        session,
                        {
                            "model": model.model_name,
                            "input": [
                                {
                                    "text": "",
                                    "audio": {
                                        "base64": base64.b64encode(
                                            item.audio
                                        ).decode("ascii"),
                                        "mimeType": item.mime_type,
                                    },
                                }
                            ],
                            "dimensions": model.dimension,
                            "encoding_format": "float",
                        },
                        expected_modality="audio",
                    )

                for index, item in indexed_images:
                    self._payload_size_bytes = self._input_size(item)
                    ordered[index] = self._post_single_embedding(
                        session,
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

                for index, item in indexed_videos:
                    self._payload_size_bytes = self._input_size(item)
                    ordered[index] = self._post_single_embedding(
                        session,
                        {
                            "model": model.model_name,
                            "input": [
                                {
                                    "text": "",
                                    "video": {
                                        "base64": base64.b64encode(
                                            item.video
                                        ).decode("ascii"),
                                        "start_offset": item.start_offset_seconds,
                                        "end_offset": item.end_offset_seconds,
                                        "interval": item.interval_seconds,
                                    },
                                }
                            ],
                            "dimensions": model.dimension,
                            "encoding_format": "float",
                        },
                        expected_modality="video",
                    )

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

    def _post_single_embedding(
        self,
        session: requests.Session,
        payload: dict[str, Any],
        *,
        expected_modality: str,
    ) -> Sequence[float]:
        vectors = self._post_embeddings(
            payload,
            expected_modality=expected_modality,
            session=session,
        )
        if len(vectors) != 1:
            raise EmbeddingError(
                EMBEDDING_PROVIDER_FAILED,
                detail="The embedding provider returned an unexpected number of vectors.",
            )
        return vectors[0]

    def _post_embeddings(
        self,
        payload: dict[str, Any],
        *,
        expected_modality: str,
        session: requests.Session | None = None,
    ) -> list[Sequence[float]]:
        requester = session or requests
        last_reason = "provider_failure"
        last_status: int | None = None
        last_request_id: str | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            started_at = time.monotonic()
            response: requests.Response | None = None
            retryable = False
            last_status = None
            last_request_id = None
            try:
                response = requester.post(
                    f"{self._base_url.rstrip('/')}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._credential}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=(
                        self._policy.connection_timeout_seconds,
                        self._policy.read_timeout_seconds,
                    ),
                )
                last_status = response.status_code
                last_request_id = self._safe_request_id(response)
                retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                last_reason = self._status_reason(response.status_code)
                response.raise_for_status()

                try:
                    response_json = response.json()
                except (TypeError, ValueError):
                    raise EmbeddingError(
                        EMBEDDING_PROVIDER_FAILED,
                        detail="The embedding provider returned malformed JSON.",
                        failure_reason="malformed_response",
                        http_status=response.status_code,
                        provider_request_id=last_request_id,
                    ) from None

                vectors = self._parse_embedding_response(
                    response_json, expected_modality=expected_modality
                )
                self._record_attempt(
                    expected_modality,
                    attempt,
                    started_at,
                    outcome="success",
                    status=response.status_code,
                    request_id=last_request_id,
                )
                return vectors
            except EmbeddingError as error:
                self._record_attempt(
                    expected_modality,
                    attempt,
                    started_at,
                    outcome="permanent_failure",
                    status=last_status,
                    request_id=last_request_id,
                    reason=error.failure_reason or last_reason,
                )
                raise
            except requests.Timeout:
                retryable = True
                last_reason = "timeout"
            except requests.ConnectionError:
                retryable = True
                last_reason = "connection_error"
            except requests.HTTPError:
                # HTTP status classification was captured above. Other 4xx
                # responses, including authentication failures, are permanent.
                pass
            except requests.RequestException:
                last_reason = "request_error"
            except Exception:
                # Unexpected response shapes or client adapter failures are
                # permanent and normalized without retaining provider data.
                last_reason = "malformed_response"

            exhausted = attempt >= self._policy.max_attempts
            outcome = "exhausted" if retryable and exhausted else (
                "retry" if retryable else "permanent_failure"
            )
            self._record_attempt(
                expected_modality,
                attempt,
                started_at,
                outcome=outcome,
                status=last_status,
                request_id=last_request_id,
                reason=last_reason,
            )
            if last_reason == "timeout":
                add_metric_counter(
                    "rag.embedding.provider_timeouts",
                    self._metric_attributes(
                        expected_modality,
                        outcome=outcome,
                        status=last_status,
                    ),
                )
            if not retryable or exhausted:
                log.error(
                    "embedding_provider_failed call_id=%s provider=portkey modality=%s "
                    "model_id=%s attempt=%s max_attempts=%s reason=%s status=%s "
                    "request_id=%s payload_size_bytes=%s operation=%s",
                    self._call_id,
                    expected_modality,
                    getattr(self, "_model_id", None),
                    attempt,
                    self._policy.max_attempts,
                    last_reason,
                    last_status,
                    last_request_id,
                    getattr(self, "_payload_size_bytes", None),
                    self._call_context.get("operation"),
                )
                raise EmbeddingError(
                    EMBEDDING_PROVIDER_FAILED,
                    detail="Portkey embedding generation failed.",
                    retryable=retryable,
                    failure_reason=last_reason,
                    http_status=last_status,
                    provider_request_id=last_request_id,
                ) from None

            delay = self._retry_delay(response, attempt)
            add_metric_counter(
                "rag.embedding.provider_retries",
                self._metric_attributes(
                    expected_modality,
                    outcome="retry",
                    status=last_status,
                ),
            )
            record_metric_histogram(
                "rag.embedding.provider_retry_delay_seconds",
                delay,
                self._metric_attributes(
                    expected_modality,
                    outcome="retry",
                    status=last_status,
                ),
            )
            log.info(
                "embedding_provider_retry call_id=%s provider=portkey model_id=%s "
                "modality=%s operation=%s attempt=%s retryable=true status=%s "
                "reason=%s retry_delay_seconds=%.3f request_id=%s",
                self._call_id,
                getattr(self, "_model_id", None),
                expected_modality,
                self._call_context.get("operation"),
                attempt,
                last_status,
                last_reason,
                delay,
                last_request_id,
            )
            time.sleep(delay)

        raise AssertionError("embedding attempt loop did not terminate")

    @staticmethod
    def _status_reason(status: int) -> str:
        if status == 413:
            return "payload_too_large"
        if status == 408:
            return "timeout"
        if status in {401, 403}:
            return "authentication"
        if status in {429, 500, 502, 503, 504}:
            return "retryable_http_status"
        if 400 <= status < 500:
            return "client_error"
        if status >= 500:
            return "server_error"
        return "provider_failure"

    def _retry_delay(
        self,
        response: requests.Response | None,
        attempt: int,
    ) -> float:
        retry_after = self._parse_retry_after(response)
        if retry_after is not None:
            return min(retry_after, float(self._policy.retry_after_cap_seconds))
        delay = self._policy.backoff_base_seconds * (2 ** (attempt - 1))
        jitter = delay * self._policy.jitter_ratio
        return max(0.0, delay + random.uniform(-jitter, jitter))

    def _parse_retry_after(self, response: requests.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _safe_request_id(response: requests.Response) -> str | None:
        value = response.headers.get("x-portkey-request-id") or response.headers.get(
            "x-request-id"
        )
        if not value:
            return None
        return PortkeyEmbeddingProvider._safe_identifier(value)

    @staticmethod
    def _safe_identifier(value: str) -> str | None:
        safe = "".join(char for char in value[:128] if char.isalnum() or char in "-_.")
        return safe or None

    def _metric_attributes(
        self,
        modality: str,
        *,
        outcome: str,
        status: int | None,
    ) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "call_id": self._call_id,
            "provider": "portkey",
            "model_id": getattr(self, "_model_id", None),
            "modality": modality,
            "outcome": outcome,
            "http_status": status,
            "payload_size_bytes": getattr(self, "_payload_size_bytes", None),
        }
        for key in (
            "operation",
            "file_id",
            "knowledge_id",
            "job_id",
            "chunk_index",
            "start_offset_seconds",
            "end_offset_seconds",
            "split_depth",
        ):
            value = self._call_context.get(key)
            if isinstance(value, (str, int, float, bool)):
                attrs[key] = value
        return attrs

    def _record_attempt(
        self,
        modality: str,
        attempt: int,
        started_at: float,
        *,
        outcome: str,
        status: int | None,
        request_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        attrs = self._metric_attributes(
            modality,
            outcome=outcome,
            status=status,
        )
        attrs["attempt"] = attempt
        elapsed = time.monotonic() - started_at
        add_metric_counter("rag.embedding.provider_attempts", attrs)
        record_metric_histogram(
            "rag.embedding.provider_duration_seconds",
            elapsed,
            attrs,
        )
        log.info(
            "embedding_provider_request call_id=%s provider=portkey model_id=%s "
            "modality=%s operation=%s file_id=%s job_id=%s chunk_index=%s "
            "start_offset_seconds=%s end_offset_seconds=%s payload_size_bytes=%s "
            "attempt=%s elapsed_seconds=%.3f retryable=%s status=%s "
            "request_id=%s reason=%s outcome=%s",
            self._call_id,
            getattr(self, "_model_id", None),
            modality,
            self._call_context.get("operation"),
            self._call_context.get("file_id"),
            self._call_context.get("job_id"),
            self._call_context.get("chunk_index"),
            self._call_context.get("start_offset_seconds"),
            self._call_context.get("end_offset_seconds"),
            getattr(self, "_payload_size_bytes", None),
            attempt,
            elapsed,
            outcome in {"retry", "exhausted"},
            status,
            request_id,
            reason,
            outcome,
        )

    @staticmethod
    def _input_size(item: EmbeddingInput) -> int:
        if isinstance(item, TextEmbeddingInput):
            return len(item.text.encode("utf-8"))
        if isinstance(item, AudioEmbeddingInput):
            return len(item.audio)
        if isinstance(item, ImageEmbeddingInput):
            return len(item.image)
        if isinstance(item, VideoEmbeddingInput):
            return len(item.video)
        return 0

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
            if expected_modality == "video":
                # Video responses use predictions[].videoEmbeddings[].embedding.
                # Require exactly one vector per prediction.
                all_vectors: list[Sequence[float]] = []
                for item in predictions:
                    if not isinstance(item, dict):
                        continue
                    video_embeddings = item.get("videoEmbeddings")
                    if not isinstance(video_embeddings, list):
                        continue
                    for ve in video_embeddings:
                        if isinstance(ve, dict) and ve.get("embedding") is not None:
                            all_vectors.append(ve["embedding"])
                if all_vectors:
                    return all_vectors
            else:
                field = {
                    "audio": "audioEmbedding",
                    "image": "imageEmbedding",
                    "text": "textEmbedding",
                }.get(expected_modality)
                if field is None:
                    raise EmbeddingError(
                        EMBEDDING_PROVIDER_FAILED,
                        detail="The embedding provider returned an unexpected modality.",
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
