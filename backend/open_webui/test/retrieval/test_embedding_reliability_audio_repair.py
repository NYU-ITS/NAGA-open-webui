import hashlib
import io
import logging
import wave
from types import SimpleNamespace

import pytest
import requests
from fastapi import BackgroundTasks, HTTPException

from open_webui.models.files import sanitize_public_file_metadata
from open_webui.retrieval.embedding import audio_repair as audio_repair_module
from open_webui.retrieval.embedding.errors import (
    AUDIO_REPAIR_STATE_STALE,
    EMBEDDING_PROVIDER_FAILED,
    EmbeddingError,
)
from open_webui.retrieval.embedding.file_processing import (
    AUDIO_REPAIR_STATE_META_KEY,
    embed_prepared_file_best_effort_audio,
)
from open_webui.retrieval.embedding.inputs import (
    AudioEmbeddingInput,
    EmbeddingModelSpec,
    ImageEmbeddingInput,
    TextEmbeddingInput,
    VideoEmbeddingInput,
)
from open_webui.retrieval.embedding.preparation import (
    PreparedChunk,
    PreparedFile,
    build_preparation_recipe,
)
from open_webui.retrieval.embedding.providers import portkey as portkey_module
from open_webui.retrieval.embedding.providers.portkey import PortkeyEmbeddingProvider
from open_webui.retrieval.embedding.reliability import EmbeddingReliabilityPolicy
from open_webui.retrieval.embedding import resolution as resolution_module
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.embedding import gate as gate_module
from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository
from open_webui.routers import knowledge as knowledge_router
from open_webui.utils import job_queue as job_queue_module


def _model(*modalities: str) -> EmbeddingModelSpec:
    return EmbeddingModelSpec(
        id="model-id",
        provider="portkey",
        model_name="provider-model",
        dimension=1536,
        modalities=frozenset(modalities),
        status="enabled",
    )


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": [{"embedding": [0.5]}]}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError()

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(monkeypatch, outcomes, policy=None):
    session = _Session(outcomes)
    monkeypatch.setattr(portkey_module, "PORTKEY_SDK_AVAILABLE", True)
    monkeypatch.setattr(portkey_module.requests, "Session", lambda: session)
    return (
        PortkeyEmbeddingProvider(
            "https://gateway.example/v1",
            "secret",
            reliability_policy=policy or EmbeddingReliabilityPolicy(max_attempts=1),
        ),
        session,
    )


def test_portkey_retries_timeout_with_frozen_timeouts_and_backoff(monkeypatch):
    provider, session = _provider(
        monkeypatch,
        [requests.Timeout(), _Response()],
        EmbeddingReliabilityPolicy(
            max_attempts=2,
            connection_timeout_seconds=7,
            read_timeout_seconds=90,
            jitter_ratio=0,
        ),
    )
    sleeps = []
    monkeypatch.setattr(portkey_module.time, "sleep", sleeps.append)

    vectors = provider.embed((TextEmbeddingInput("hello"),), _model("text"))

    assert vectors == [[0.5]]
    assert len(session.calls) == 2
    assert session.calls[0][1]["timeout"] == (7, 90)
    assert sleeps == [2.0]


@pytest.mark.parametrize("status_code", [401, 400, 404])
def test_portkey_does_not_retry_permanent_client_failures(monkeypatch, status_code):
    provider, session = _provider(
        monkeypatch,
        [_Response(status_code), _Response()],
        EmbeddingReliabilityPolicy(max_attempts=3),
    )

    with pytest.raises(EmbeddingError) as caught:
        provider.embed((TextEmbeddingInput("hello"),), _model("text"))

    assert caught.value.code == EMBEDDING_PROVIDER_FAILED
    assert caught.value.retryable is False
    assert len(session.calls) == 1


def test_portkey_does_not_retry_malformed_response(monkeypatch):
    provider, session = _provider(
        monkeypatch,
        [_Response(payload=ValueError("invalid json")), _Response()],
        EmbeddingReliabilityPolicy(max_attempts=3),
    )

    with pytest.raises(EmbeddingError) as caught:
        provider.embed((TextEmbeddingInput("hello"),), _model("text"))

    assert caught.value.failure_reason == "malformed_response"
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "embedding_input,modality",
    [
        (TextEmbeddingInput("hello"), "text"),
        (ImageEmbeddingInput(b"image", "image/png"), "image"),
        (AudioEmbeddingInput(b"audio"), "audio"),
        (VideoEmbeddingInput(b"video", "video/mp4", 0, 1, 1), "video"),
    ],
)
def test_all_modalities_use_the_retrying_http_path(monkeypatch, embedding_input, modality):
    response_payload = (
        {"predictions": [{"videoEmbeddings": [{"embedding": [0.5]}]}]}
        if modality == "video"
        else {"data": [{"embedding": [0.5]}]}
    )
    provider, session = _provider(
        monkeypatch,
        [requests.Timeout(), _Response(payload=response_payload)],
        EmbeddingReliabilityPolicy(max_attempts=2, jitter_ratio=0),
    )
    monkeypatch.setattr(portkey_module.time, "sleep", lambda _delay: None)

    assert provider.embed((embedding_input,), _model("text", "image", "audio", "video")) == [[0.5]]
    assert len(session.calls) == 2


def test_retry_after_is_capped_and_logs_never_include_payload_or_key(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    provider, _session = _provider(
        monkeypatch,
        [_Response(429, headers={"Retry-After": "999"}), _Response()],
        EmbeddingReliabilityPolicy(max_attempts=2),
    )
    sleeps = []
    monkeypatch.setattr(portkey_module.time, "sleep", sleeps.append)

    provider.embed((TextEmbeddingInput("TOP SECRET PAYLOAD"),), _model("text"))

    assert sleeps == [120.0]
    log_text = caplog.text
    assert "TOP SECRET PAYLOAD" not in log_text
    assert "secret" not in log_text
    assert "call_id=" in log_text


def test_invalid_vectors_are_rejected_after_one_provider_call(monkeypatch):
    service = EmbeddingService(
        SimpleNamespace(),
        reliability_policy=EmbeddingReliabilityPolicy(max_attempts=5),
    )
    provider = SimpleNamespace(calls=0)

    def embed(_inputs, _model_spec):
        provider.calls += 1
        return [[float("nan")]]

    provider.embed = embed
    monkeypatch.setattr(service, "_resolve_admin", lambda _admin_id: SimpleNamespace(email="admin@example"))
    monkeypatch.setattr(
        "open_webui.retrieval.embedding.service.resolve_credential_for_admin",
        lambda *_args: "key",
    )
    monkeypatch.setattr(
        "open_webui.retrieval.embedding.service.resolve_base_url_for_admin",
        lambda *_args: "https://gateway.example/v1",
    )
    monkeypatch.setattr(service, "_create_provider", lambda *_args: provider)

    with pytest.raises(EmbeddingError):
        service._embed(
            (TextEmbeddingInput("hello"),),
            SimpleNamespace(admin_id="admin", model=_model("text")),
        )

    assert provider.calls == 1


def _wav(duration_seconds: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000 * duration_seconds)
    return output.getvalue()


def _prepared_audio(duration_seconds=12) -> PreparedFile:
    audio = _wav(duration_seconds)
    return PreparedFile(
        chunks=(
            PreparedChunk(
                content="",
                content_type="audio",
                embedding_input=AudioEmbeddingInput(audio),
                content_sha256=hashlib.sha256(audio).hexdigest(),
                modality="audio",
                chunk_metadata={
                    "chunkIndex": 0,
                    "segment_start_s": 4.0,
                    "segment_end_s": 4.0 + duration_seconds,
                    "audio_extraction_version": "audio-v1",
                    "chunking_version": "chunks-v1",
                },
            ),
        ),
        text_content="",
        source_sha256="a" * 64,
        extraction_version="video-v1",
        warnings=(),
        visual_summary={"audio_chunk_count": 1},
    )


class _AdaptiveService:
    def __init__(self, failure_reason):
        self.failure_reason = failure_reason
        self.reliability_policy = EmbeddingReliabilityPolicy(
            max_attempts=1,
            audio_split_max_depth=2,
            audio_split_min_duration_seconds=5,
        )
        self.calls = 0
        self.audio_calls = 0

    def embed_for_frozen_context(self, inputs, **_kwargs):
        self.calls += 1
        item = inputs[0]
        if isinstance(item, AudioEmbeddingInput):
            self.audio_calls += 1
            if self.audio_calls == 1:
                raise EmbeddingError(
                    EMBEDDING_PROVIDER_FAILED,
                    failure_reason=self.failure_reason,
                )
            return SimpleNamespace(vectors=((float(len(item.audio)),),))
        return SimpleNamespace(vectors=((1.0,),))


@pytest.mark.parametrize("failure_reason", ["timeout", "payload_too_large"])
def test_audio_timeout_or_oversize_splits_and_preserves_offsets(failure_reason):
    service = _AdaptiveService(failure_reason)

    prepared, vectors = embed_prepared_file_best_effort_audio(
        prepared=_prepared_audio(),
        embedding_service=service,
        admin_id="admin",
        embedding_model_id="model",
    )

    assert len(prepared.chunks) == len(vectors) == 2
    assert [chunk.chunk_metadata["segment_start_s"] for chunk in prepared.chunks] == [4.0, 10.0]
    assert [chunk.chunk_metadata["segment_end_s"] for chunk in prepared.chunks] == [10.0, 16.0]
    assert all(chunk.chunk_metadata["audio_root_sha256"] for chunk in prepared.chunks)
    assert prepared.audio_embedding["status"] == "complete"


def test_permanent_audio_failure_stays_degraded_without_splitting():
    service = _AdaptiveService("authentication")

    prepared, vectors = embed_prepared_file_best_effort_audio(
        prepared=_prepared_audio(),
        embedding_service=service,
        admin_id="admin",
        embedding_model_id="model",
    )

    assert vectors == ()
    assert service.calls == 1
    assert prepared.audio_embedding["status"] == "degraded"
    assert prepared.audio_embedding["repairable"] is True
    assert len(prepared.audio_repair_state["failed_chunks"]) == 1


def test_degraded_audio_preserves_successful_visual_chunks():
    audio_prepared = _prepared_audio()
    image = b"image-bytes"
    prepared = PreparedFile(
        chunks=(
            PreparedChunk(
                content="",
                content_type="image",
                embedding_input=ImageEmbeddingInput(image, "image/png"),
                content_sha256=hashlib.sha256(image).hexdigest(),
                modality="image",
                chunk_metadata={"chunkIndex": 0},
            ),
            audio_prepared.chunks[0],
        ),
        text_content="",
        source_sha256=audio_prepared.source_sha256,
        extraction_version=audio_prepared.extraction_version,
        warnings=(),
        visual_summary={"image_chunk_count": 1, "audio_chunk_count": 1},
    )
    service = _AdaptiveService("authentication")

    processed, vectors = embed_prepared_file_best_effort_audio(
        prepared=prepared,
        embedding_service=service,
        admin_id="admin",
        embedding_model_id="model",
    )

    assert [chunk.modality for chunk in processed.chunks] == ["image"]
    assert len(vectors) == 1
    assert processed.visual_summary["image_chunk_count"] == 1
    assert processed.audio_embedding["status"] == "degraded"


def test_private_repair_state_never_crosses_file_api_boundary():
    public = sanitize_public_file_metadata(
        {
            AUDIO_REPAIR_STATE_META_KEY: {
                "source_sha256": "a" * 64,
                "failed_chunks": [{"audio_sha256": "b" * 64}],
            },
            "audio_embedding": {
                "status": "degraded",
                "total_chunks": 3,
                "embedded_chunks": 2,
                "failed_chunks": 1,
                "repairable": True,
                "unexpected": "private",
            },
        }
    )

    assert AUDIO_REPAIR_STATE_META_KEY not in public
    assert public["audio_embedding"] == {
        "status": "degraded",
        "total_chunks": 3,
        "embedded_chunks": 2,
        "failed_chunks": 1,
        "repairable": True,
    }


def test_audio_repair_repository_uses_additive_client_method_only():
    client = SimpleNamespace(calls=[])
    client.upsert_model_aware_many = lambda projections, session=None: client.calls.append(
        (projections, session)
    )
    repository = ModelAwareVectorRepository(vector_db_client=client)

    repository.upsert_model_aware_many(
        projections=(("knowledge", ()),),
        model=_model("audio"),
        session="transaction",
    )

    assert client.calls == [([("knowledge", [])], "transaction")]


def test_audio_repair_rejects_a_state_for_a_non_active_model(monkeypatch):
    monkeypatch.setattr(
        audio_repair_module.AdminEmbeddingModelStateRepository,
        "get_state",
        lambda *_args, **_kwargs: SimpleNamespace(
            active_embedding_model_id="different-model"
        ),
    )
    row = SimpleNamespace(
        meta={
            AUDIO_REPAIR_STATE_META_KEY: {
                "source_sha256": "a" * 64,
                "embedding_model_id": "requested-model",
            }
        }
    )

    with pytest.raises(EmbeddingError) as caught:
        audio_repair_module._validated_state(
            row,
            "admin",
            "requested-model",
            db=object(),
        )

    assert caught.value.code == AUDIO_REPAIR_STATE_STALE


def test_audio_repair_endpoint_requires_knowledge_write_access(monkeypatch):
    monkeypatch.setattr(
        knowledge_router.Knowledges,
        "get_knowledge_by_id",
        lambda **_kwargs: SimpleNamespace(
            user_id="owner",
            access_control=None,
            data={"file_ids": ["file-id"]},
        ),
    )

    with pytest.raises(HTTPException) as caught:
        knowledge_router.repair_knowledge_file_audio(
            request=SimpleNamespace(),
            knowledge_id="knowledge-id",
            file_id="file-id",
            background_tasks=BackgroundTasks(),
            user=SimpleNamespace(id="viewer", role="user"),
        )

    assert caught.value.status_code == 403


def test_repeated_audio_repair_request_joins_active_lease(monkeypatch):
    monkeypatch.setattr(
        knowledge_router.Knowledges,
        "get_knowledge_by_id",
        lambda **_kwargs: SimpleNamespace(
            user_id="admin",
            access_control=None,
            data={"file_ids": ["file-id"]},
        ),
    )
    monkeypatch.setattr(
        resolution_module,
        "resolve_admin_for_knowledge",
        lambda *_args, **_kwargs: SimpleNamespace(id="admin"),
    )
    monkeypatch.setattr(
        audio_repair_module,
        "ensure_legacy_audio_repair_state",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        audio_repair_module,
        "claim_audio_repair",
        lambda **_kwargs: audio_repair_module.AudioRepairClaim(
            lease_token="lease",
            status="repairing",
            already_active=True,
        ),
    )
    monkeypatch.setattr(
        audio_repair_module.AdminEmbeddingModelStateRepository,
        "ensure_state",
        lambda *_args, **_kwargs: SimpleNamespace(
            active_embedding_model_id="model-id"
        ),
    )
    enqueue_calls = []
    monkeypatch.setattr(
        job_queue_module,
        "enqueue_audio_repair_job",
        lambda **kwargs: enqueue_calls.append(kwargs),
    )
    background_tasks = BackgroundTasks()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace()))
    )

    result = knowledge_router.repair_knowledge_file_audio(
        request=request,
        knowledge_id="knowledge-id",
        file_id="file-id",
        background_tasks=background_tasks,
        user=SimpleNamespace(id="admin", role="admin"),
    )

    assert result["already_active"] is True
    assert result["dispatch_mode"] == "active"
    assert enqueue_calls == []
    assert background_tasks.tasks == []


class _UserSetting:
    def __init__(self, value):
        self.value = value

    def get(self, _email):
        return self.value


def test_reliability_settings_are_not_part_of_the_embedding_recipe():
    config = SimpleNamespace(
        CHUNK_SIZE=_UserSetting(1000),
        CHUNK_OVERLAP=_UserSetting(200),
        RAG_EMBEDDING_MAX_ATTEMPTS=3,
        RAG_EMBEDDING_READ_TIMEOUT=120,
    )
    original = build_preparation_recipe(config, "admin@example.edu")

    config.RAG_EMBEDDING_MAX_ATTEMPTS = 5
    config.RAG_EMBEDDING_READ_TIMEOUT = 600
    reliability_only = build_preparation_recipe(config, "admin@example.edu")
    config.CHUNK_SIZE = _UserSetting(900)
    recipe_change = build_preparation_recipe(config, "admin@example.edu")

    assert reliability_only.sha256 == original.sha256
    assert recipe_change.sha256 != original.sha256


@pytest.mark.parametrize("active_model_id", ["old-model", None])
def test_partial_reindex_reports_target_as_effective_model(
    monkeypatch, active_model_id
):
    state = SimpleNamespace(
        active_embedding_model_id=active_model_id,
        target_embedding_model_id="new-model",
        latest_embedding_job_id="job-id",
    )
    job = SimpleNamespace(
        id="job-id",
        admin_id="admin",
        embedding_model_id="new-model",
        status="partially_failed",
    )
    monkeypatch.setattr(gate_module, "_get_app_config", lambda: object())
    monkeypatch.setattr(
        gate_module,
        "assert_single_model_space",
        lambda *_args: ("admin", "new-model"),
    )
    monkeypatch.setattr(
        gate_module.AdminEmbeddingModelStateRepository,
        "get_state",
        lambda _admin_id: state,
    )
    monkeypatch.setattr(
        gate_module.EmbeddingJobRepository,
        "get_job",
        lambda _job_id: job,
    )
    monkeypatch.setattr(
        gate_module,
        "_completed_files_for_partial_scope",
        lambda *_args, **_kwargs: ({"file-id"}, {("knowledge-id", "file-id")}),
    )
    monkeypatch.setattr(
        gate_module,
        "get_model_spec_by_id",
        lambda model_id: SimpleNamespace(id=model_id, status="enabled"),
    )

    result = gate_module.assert_embedding_retrieval_ready(
        "viewer",
        knowledge_ids=["knowledge-id"],
    )

    assert result.active_model_id == active_model_id
    assert result.effective_model_id == "new-model"
    assert result.staged_job_ids == ("job-id",)
