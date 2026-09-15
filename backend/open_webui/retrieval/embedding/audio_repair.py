"""Idempotent, additive repair of failed video-audio embedding leaves."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping
from concurrent.futures import ThreadPoolExecutor

from open_webui.internal.db import get_db
from open_webui.models.embeddings import AdminEmbeddingModelState, RagChunk
from open_webui.models.files import File, Files
from open_webui.models.users import Users
from open_webui.retrieval.embedding.errors import (
    AUDIO_REPAIR_NOT_REQUIRED,
    AUDIO_REPAIR_STATE_STALE,
    AUDIO_REPAIR_UNAVAILABLE,
    EmbeddingError,
    VIDEO_AUDIO_EMBEDDING_FAILED,
    VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
    VIDEO_AUDIO_ABSENT,
)
from open_webui.retrieval.embedding.file_processing import (
    AUDIO_REPAIR_STATE_META_KEY,
    _make_vector_items,
    _read_source,
    _resolve_knowledge_projection_ids,
    _split_audio_prepared_chunk,
    resolve_authoritative_content_provenance,
)
from open_webui.retrieval.embedding.execution_budget import (
    execution_budget,
    remaining_seconds,
)
from open_webui.retrieval.embedding.preparation import (
    PreparationRecipe,
    PreparedChunk,
    PreparedFile,
    build_persisted_chunks,
    build_preparation_recipe,
    prepare_file_for_embedding,
)
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.reliability import (
    EmbeddingReliabilityPolicy,
)
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.embedding.state import AdminEmbeddingModelStateRepository
from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository
from open_webui.utils.otel_instrumentation import (
    add_metric_counter,
    record_metric_histogram,
)


log = logging.getLogger(__name__)
REPAIR_LEASE_SECONDS = 120
REPAIR_HEARTBEAT_SECONDS = 30
AUDIO_EXECUTION_BUDGET_SECONDS = 300
_runtime_lock = threading.Lock()
_reconciler_stop = threading.Event()
_reconciler_thread: threading.Thread | None = None
_audio_executor: ThreadPoolExecutor | None = None
_background_dispatches: set[str] = set()
_background_capacity = threading.BoundedSemaphore(2)
_reconcile_cursor = ""


@dataclass(frozen=True)
class AudioRepairClaim:
    lease_token: str
    status: str
    already_active: bool


def ensure_legacy_audio_repair_state(
    *,
    config,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
) -> None:
    """Lazily reconstruct private state for legacy degraded video records."""
    file = Files.get_file_by_id(file_id)
    if file is None:
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    meta = file.meta if isinstance(file.meta, dict) else {}
    if isinstance(meta.get(AUDIO_REPAIR_STATE_META_KEY), dict):
        return
    warnings = meta.get("processing_warnings")
    if not isinstance(warnings, list) or VIDEO_AUDIO_EMBEDDING_FAILED not in warnings:
        raise EmbeddingError(AUDIO_REPAIR_NOT_REQUIRED)

    admin = Users.get_user_by_id(admin_id)
    if admin is None or not admin.email:
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    model = get_model_spec_by_id(embedding_model_id)
    source_path, source_bytes = _read_source(file.path)
    recipe = build_preparation_recipe(config, admin.email)
    provenance = resolve_authoritative_content_provenance(file, source_bytes)
    prepared = prepare_file_for_embedding(
        source_bytes=source_bytes,
        source_path=source_path,
        filename=file.filename,
        content_type=meta.get("content_type"),
        file_id=file.id,
        created_by=file.user_id,
        model=model,
        config=config,
        admin_email=admin.email,
        preparation_recipe=recipe,
        content_override=provenance.content_override,
    )
    audio_chunks = [chunk for chunk in prepared.chunks if chunk.modality == "audio"]
    if not audio_chunks:
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    # Legacy rows predate repair state, but their successful audio projections
    # still identify exactly which content hashes are already present.
    try:
        from open_webui.retrieval.vector.dbs.pgvector import DocumentChunk

        with get_db() as db:
            projection_rows = (
                db.query(
                    RagChunk.content_sha256,
                    RagChunk.content_type,
                    RagChunk.chunk_metadata,
                )
                .join(DocumentChunk, DocumentChunk.rag_chunk_id == RagChunk.id)
                .filter(
                    DocumentChunk.admin_id == admin_id,
                    DocumentChunk.embedding_model_id == embedding_model_id,
                    DocumentChunk.file_id == file_id,
                    DocumentChunk.embedding_status == "active",
                )
                .distinct()
                .all()
            )
    except Exception:
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE) from None
    if not projection_rows:
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    for _content_hash, _content_type, chunk_metadata in projection_rows:
        if (
            not isinstance(chunk_metadata, dict)
            or chunk_metadata.get("source_sha256") != prepared.source_sha256
            or chunk_metadata.get("preparation_recipe_sha256") != recipe.sha256
        ):
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    embedded_hashes = {
        content_hash
        for content_hash, content_type, _metadata in projection_rows
        if content_type == "audio"
    }
    missing_audio_chunks = [
        chunk for chunk in audio_chunks if chunk.content_sha256 not in embedded_hashes
    ]
    if not missing_audio_chunks:
        _mark_legacy_audio_complete(file_id, len(audio_chunks))
        raise EmbeddingError(AUDIO_REPAIR_NOT_REQUIRED)
    now = int(time.time())
    failed_chunks = [
        _descriptor_for_chunk(chunk, now=now) for chunk in missing_audio_chunks
    ]
    first_metadata = dict(audio_chunks[0].chunk_metadata)
    state = {
        "schema_version": 1,
        "source_sha256": prepared.source_sha256,
        "embedding_model_id": embedding_model_id,
        "extraction_version": prepared.extraction_version,
        "audio_extraction_version": first_metadata.get("audio_extraction_version"),
        "audio_chunking_version": first_metadata.get("chunking_version"),
        "failed_chunks": failed_chunks,
        "total_chunks": len(audio_chunks),
        "embedded_chunks": len(audio_chunks) - len(failed_chunks),
        "created_at": now,
        "updated_at": now,
        "preparation_recipe": recipe.to_dict(),
    }
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        row_meta = dict(row.meta or {})
        if not isinstance(row_meta.get(AUDIO_REPAIR_STATE_META_KEY), dict):
            row_meta[AUDIO_REPAIR_STATE_META_KEY] = state
            row_meta["audio_embedding"] = _public_summary(state, "degraded")
            row.meta = row_meta
            row.updated_at = now
            db.commit()


def _mark_legacy_audio_complete(file_id: str, audio_chunk_count: int) -> None:
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        meta = dict(row.meta or {})
        warnings = list(meta.get("processing_warnings") or [])
        meta["processing_warnings"] = [
            warning
            for warning in warnings
            if warning
            not in {VIDEO_AUDIO_EMBEDDING_FAILED, VIDEO_AUDIO_FALLBACK_VISUAL_ONLY}
        ]
        meta.pop(AUDIO_REPAIR_STATE_META_KEY, None)
        meta["audio_embedding"] = {
            "status": "complete",
            "total_chunks": audio_chunk_count,
            "embedded_chunks": audio_chunk_count,
            "failed_chunks": 0,
            "repairable": False,
            "updated_at": now,
        }
        visual_summary = dict(meta.get("visual_summary") or {})
        visual_summary["audio_chunk_count"] = audio_chunk_count
        meta["visual_summary"] = visual_summary
        row.meta = meta
        row.updated_at = now
        db.commit()


def claim_audio_repair(
    *,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
) -> AudioRepairClaim:
    """Create or join durable queued work; only a worker claims execution."""
    now = int(time.time())
    with get_db() as db:
        row = _lock_repair_file(db, admin_id, file_id)
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        if not isinstance((row.meta or {}).get(AUDIO_REPAIR_STATE_META_KEY), dict):
            raise EmbeddingError(AUDIO_REPAIR_NOT_REQUIRED)
        state = _validated_state(
            row, admin_id, embedding_model_id, db=db, validate_source=False
        )
        failed = state.get("failed_chunks")
        if not isinstance(failed, list) or not failed:
            raise EmbeddingError(AUDIO_REPAIR_NOT_REQUIRED)
        current_token = state.get("lease_token")
        if isinstance(current_token, str):
            phase = state.get("phase")
            heartbeat = state.get("lease_heartbeat_at", 0)
            if phase == "queued" or (
                phase == "running" and now - heartbeat < REPAIR_LEASE_SECONDS
            ):
                return AudioRepairClaim(
                    current_token, "queued" if phase == "queued" else "repairing", True
                )

        lease_token = str(uuid.uuid4())
        state.update(
            {
                "lease_token": lease_token,
                "phase": "queued",
                "admin_id": admin_id,
                "dispatch_id": f"audio_repair_{lease_token}",
                "updated_at": now,
            }
        )
        meta = dict(row.meta or {})
        meta[AUDIO_REPAIR_STATE_META_KEY] = state
        state.pop("execution_owner", None)
        state.pop("lease_heartbeat_at", None)
        state.pop("dispatch_mode", None)
        meta["audio_embedding"] = _public_summary(state, "queued")
        row.meta = meta
        row.updated_at = now
        db.commit()
        add_metric_counter("retrieval.video.audio_repair_requests", {"outcome": "claimed"})
        return AudioRepairClaim(lease_token, "queued", False)


def repair_audio_embeddings(
    *,
    config,
    knowledge_id: str | None,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
    lease_token: str,
    reliability_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Repair failed leaves and commit every success with an additive upsert."""
    started_at = time.monotonic()
    call_id = str(uuid.uuid4())
    owner = str(uuid.uuid4())
    if not _claim_execution(file_id, admin_id, embedding_model_id, lease_token, owner):
        return {"status": "already_active", "file_id": file_id}
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(heartbeat_stop, file_id, lease_token, owner),
        name="audio-repair-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        with execution_budget(
            AUDIO_EXECUTION_BUDGET_SECONDS - (time.monotonic() - started_at)
        ):
            return _execute_audio_repair(
                config=config,
                knowledge_id=knowledge_id,
                file_id=file_id,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                lease_token=lease_token,
                owner=owner,
                reliability_policy=reliability_policy,
                call_id=call_id,
                started_at=started_at,
            )
    except Exception as error:
        _release_failed_lease(file_id, lease_token, owner=owner)
        if (
            isinstance(error, EmbeddingError)
            and error.failure_reason == "budget_exhausted"
        ) or time.monotonic() - started_at >= AUDIO_EXECUTION_BUDGET_SECONDS - 5:
            add_metric_counter("retrieval.video.audio_budget_exhaustion")
        log.warning(
            "Audio repair stopped | file_id=%s type=%s", file_id, type(error).__name__
        )
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)


def _execute_audio_repair(
    *,
    config,
    knowledge_id,
    file_id,
    admin_id,
    embedding_model_id,
    lease_token,
    owner,
    reliability_policy,
    call_id,
    started_at,
):
    try:
        file = Files.get_file_by_id(file_id)
        if file is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        meta = file.meta if isinstance(file.meta, dict) else {}
        state = meta.get(AUDIO_REPAIR_STATE_META_KEY)
        if not isinstance(state, dict) or state.get("lease_token") != lease_token:
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        admin = Users.get_user_by_id(admin_id)
        if admin is None or not admin.email:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        recipe = PreparationRecipe.from_dict(state.get("preparation_recipe"))
        model = get_model_spec_by_id(embedding_model_id)
        source_path, source_bytes = _read_source(file.path)
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if source_sha256 != state.get("source_sha256"):
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        provenance = resolve_authoritative_content_provenance(file, source_bytes)
        prepared = prepare_file_for_embedding(
            source_bytes=source_bytes,
            source_path=source_path,
            filename=file.filename,
            content_type=meta.get("content_type"),
            file_id=file.id,
            created_by=file.user_id,
            model=model,
            config=config,
            admin_email=admin.email,
            preparation_recipe=recipe,
            content_override=provenance.content_override,
        )
        service = EmbeddingService(
            config,
            reliability_policy=EmbeddingReliabilityPolicy.from_dict(
                reliability_policy
            ),
            call_context={
                "call_id": call_id,
                "operation": "repair",
                "file_id": file_id,
                "knowledge_id": knowledge_id,
            },
        )
        requested = list(state.get("failed_chunks") or [])
        while requested:
            remaining_seconds()
            descriptor = requested.pop(0)
            if VIDEO_AUDIO_ABSENT in prepared.warnings:
                _commit_repair_result(
                    file_id=file_id,
                    knowledge_id=knowledge_id,
                    admin_id=admin_id,
                    model=model,
                    prepared=prepared,
                    descriptor=descriptor,
                    successes=[],
                    failures=[],
                    lease_token=lease_token,
                    owner=owner,
                )
                continue
            chunk = _reconstruct_failed_chunk(prepared, descriptor)
            successes = []
            failures = []
            try:
                batch = service.embed_for_frozen_context(
                    inputs=(chunk.embedding_input,),
                    admin_id=admin_id,
                    embedding_model_id=embedding_model_id,
                )
                successes = [(chunk, batch.vectors[0])]
            except Exception as error:
                reason = (
                    error.failure_reason
                    if isinstance(error, EmbeddingError)
                    else "provider_failure"
                )
                if reason == "budget_exhausted":
                    raise
                depth = int(descriptor.get("split_depth", 0))
                duration = float(descriptor["end_seconds"]) - float(
                    descriptor["start_seconds"]
                )
                policy = service.reliability_policy
                children = ()
                if (
                    reason in {"timeout", "payload_too_large"}
                    and depth < policy.audio_split_max_depth
                    and duration >= 2 * policy.audio_split_min_duration_seconds
                ):
                    remaining_seconds()
                    children = _split_audio_prepared_chunk(
                        chunk,
                        split_depth=depth,
                        split_path=str(descriptor.get("split_path", "")),
                    )
                failures = (
                    [
                        {
                            **_descriptor_for_chunk(child, now=int(time.time())),
                            "failure_reason": reason,
                        }
                        for child in children
                    ]
                    if children
                    else [
                        {
                            **dict(descriptor),
                            "failure_reason": reason,
                            "failed_at": int(time.time()),
                        }
                    ]
                )
                # Commit the replacement before any child provider call. Each
                # subsequent leaf commits independently, surviving termination.
                if children:
                    requested[0:0] = failures
                    add_metric_counter(
                        "retrieval.video.audio_adaptive_splits", {"reason": reason}
                    )
            _commit_repair_result(
                file_id=file_id,
                knowledge_id=knowledge_id,
                admin_id=admin_id,
                model=model,
                prepared=prepared,
                descriptor=descriptor,
                successes=successes,
                failures=failures,
                lease_token=lease_token,
                owner=owner,
            )
        summary = _finish_repair(
            file_id=file_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            lease_token=lease_token,
            owner=owner,
        )
        add_metric_counter(
            "retrieval.video.audio_repairs",
            {"outcome": summary["status"]},
        )
        record_metric_histogram(
            "retrieval.video.audio_repair_duration_seconds",
            time.monotonic() - started_at,
            {"outcome": summary["status"]},
        )
        log.info(
            "audio_repair_outcome call_id=%s knowledge_id=%s file_id=%s "
            "model_id=%s status=%s duration_seconds=%.3f",
            call_id,
            knowledge_id,
            file_id,
            embedding_model_id,
            summary["status"],
            time.monotonic() - started_at,
        )
        return summary
    except Exception as error:
        _release_failed_lease(file_id, lease_token, owner=owner)
        log.error(
            "audio_repair_outcome call_id=%s knowledge_id=%s file_id=%s "
            "model_id=%s type=%s",
            call_id,
            knowledge_id,
            file_id,
            embedding_model_id,
            type(error).__name__,
        )
        raise


def _validated_state(
    row: File, admin_id: str, embedding_model_id: str, *, db, validate_source=True
):
    state_view = AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
    if (
        state_view is None
        or state_view.active_embedding_model_id != embedding_model_id
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    state = dict((row.meta or {}).get(AUDIO_REPAIR_STATE_META_KEY) or {})
    meta = row.meta or {}
    required = meta.get("required_indexing") or {}
    # Existing repair descriptors may predate generation fencing. Adopt only
    # provenance already validated by baseline/publication reconciliation.
    if (
        state
        and not state.get("index_generation_id")
        and (
            meta.get("index_generation_id") == state_view.index_generation_id
            and meta.get("embedding_model_id") == embedding_model_id
            and meta.get("processing_status") == "completed"
        )
    ):
        state.update(
            index_generation_id=state_view.index_generation_id,
            admin_id=admin_id,
            base_manifest_id=meta.get("chunk_manifest_id"),
        )
    if (
        meta.get("processing_status") != "completed"
        or meta.get("index_generation_id") != state_view.index_generation_id
        or state.get("index_generation_id") != state_view.index_generation_id
        or meta.get("embedding_model_id") != embedding_model_id
        or (
            required.get("index_generation_id") == state_view.index_generation_id
            and int(time.time())
            - int(required.get("lease_heartbeat_at") or required.get("started_at") or 0)
            < REPAIR_LEASE_SECONDS
        )
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    if (
        not isinstance(state.get("source_sha256"), str)
        or not isinstance(state.get("embedding_model_id"), str)
        or not isinstance(state.get("preparation_recipe"), Mapping)
    ):
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
    try:
        PreparationRecipe.from_dict(state["preparation_recipe"])
    except (TypeError, ValueError):
        raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE) from None
    if (
        state.get("base_manifest_id") != meta.get("chunk_manifest_id")
        or PreparationRecipe.from_dict(state["preparation_recipe"]).sha256
        != meta.get("preparation_recipe_sha256")
        or state.get("embedding_model_id") != embedding_model_id
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    if not validate_source:
        return state
    _, current_bytes = _read_source(row.path)
    if (
        state.get("source_sha256") != hashlib.sha256(current_bytes).hexdigest()
        or state.get("embedding_model_id") != embedding_model_id
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    provenance = resolve_authoritative_content_provenance(row, current_bytes)
    if (
        state.get("base_manifest_id") != meta.get("chunk_manifest_id")
        or PreparationRecipe.from_dict(state["preparation_recipe"]).sha256
        != meta.get("preparation_recipe_sha256")
        or ("content_origin" in state and state["content_origin"] != provenance.origin)
        or (
            "content_override_sha256" in state
            and state["content_override_sha256"] != provenance.content_override_sha256
        )
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    return state


def _lock_repair_file(db, admin_id, file_id):
    # Publication and repair use the same admin -> file lock order.
    db.query(AdminEmbeddingModelState).filter_by(
        admin_id=admin_id
    ).with_for_update().first()
    return db.query(File).filter(File.id == file_id).with_for_update().first()


def _claim_execution(file_id, admin_id, model_id, lease_token, owner):
    with get_db() as db:
        row = _lock_repair_file(db, admin_id, file_id)
        if row is None:
            return False
        state = _validated_state(row, admin_id, model_id, db=db)
        if state.get("lease_token") != lease_token or state.get("phase") != "queued":
            return False
        now = int(time.time())
        state.update(
            phase="running",
            execution_owner=owner,
            lease_heartbeat_at=now,
            repair_started_at=now,
        )
        row.meta = {
            **dict(row.meta or {}),
            AUDIO_REPAIR_STATE_META_KEY: state,
            "audio_embedding": _public_summary(state, "repairing"),
        }
        db.commit()
        return True


def _heartbeat_loop(stop, file_id, lease_token, owner):
    while not stop.wait(REPAIR_HEARTBEAT_SECONDS):
        try:
            _heartbeat_audio_repair(file_id, lease_token, owner=owner)
        except Exception:
            log.warning("Audio heartbeat unavailable | file_id=%s", file_id)


def _heartbeat_audio_repair(
    file_id: str, lease_token: str, *, owner: str | None = None
) -> None:
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        meta = dict(row.meta or {})
        state = dict(meta.get(AUDIO_REPAIR_STATE_META_KEY) or {})
        if state.get("lease_token") != lease_token or (
            owner is not None and state.get("execution_owner") != owner
        ):
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        state["lease_heartbeat_at"] = now
        state["updated_at"] = now
        meta[AUDIO_REPAIR_STATE_META_KEY] = state
        row.meta = meta
        row.updated_at = now
        db.commit()


def _descriptor_for_chunk(chunk: PreparedChunk, *, now: int) -> dict[str, Any]:
    metadata = dict(chunk.chunk_metadata)
    return {
        "chunk_index": metadata.get("chunkIndex"),
        "start_seconds": metadata.get("segment_start_s"),
        "end_seconds": metadata.get("segment_end_s"),
        "audio_sha256": chunk.content_sha256,
        "split_depth": int(metadata.get("audio_split_depth", 0)),
        "split_path": str(metadata.get("audio_split_path", "")),
        "failure_reason": "legacy_failure",
        "failed_at": now,
    }


def _reconstruct_failed_chunk(
    prepared: PreparedFile,
    descriptor: Mapping[str, Any],
) -> PreparedChunk:
    candidates = [
        chunk
        for chunk in prepared.chunks
        if chunk.modality == "audio"
        and chunk.chunk_metadata.get("chunkIndex") == descriptor.get("chunk_index")
    ]
    if len(candidates) != 1:
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    chunk = candidates[0]
    prefix = ""
    for depth, direction in enumerate(str(descriptor.get("split_path", ""))):
        if direction not in {"0", "1"}:
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        children = _split_audio_prepared_chunk(
            chunk,
            split_depth=depth,
            split_path=prefix,
        )
        chunk = children[int(direction)]
        prefix += direction
    if descriptor.get(
        "audio_sha256"
    ) is not None and chunk.content_sha256 != descriptor.get("audio_sha256"):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    return chunk


def _descriptor_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("chunk_index"),
        value.get("split_path"),
        value.get("audio_sha256"),
    )


def _commit_repair_result(
    *,
    file_id: str,
    knowledge_id: str | None,
    admin_id: str,
    model,
    prepared: PreparedFile,
    descriptor: Mapping[str, Any],
    successes: list[tuple[PreparedChunk, tuple[float, ...]]],
    failures: list[dict[str, Any]],
    lease_token: str,
    owner: str | None = None,
) -> None:
    now = int(time.time())
    with get_db() as db:
        row = _lock_repair_file(db, admin_id, file_id)
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        state = _validated_state(row, admin_id, model.id, db=db)
        if state.get("lease_token") != lease_token or (
            owner is not None and state.get("execution_owner") != owner
        ):
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        if not any(
            _descriptor_key(value) == _descriptor_key(descriptor)
            for value in state.get("failed_chunks", [])
        ):
            return

        if successes:
            success_chunks = tuple(chunk for chunk, _ in successes)
            success_vectors = tuple(vector for _, vector in successes)
            fragment = replace(prepared, chunks=success_chunks)
            persisted = build_persisted_chunks(
                fragment,
                admin_id=admin_id,
                file_id=file_id,
            )
            manifest_id = RagChunk.build_manifest_id(
                persisted,
                source_sha256=prepared.source_sha256,
                extraction_version=prepared.extraction_version,
            )
            rag_chunk_ids = RagChunk.insert_chunks(
                admin_id,
                file_id,
                persisted,
                manifest_id=manifest_id,
                db=db,
            )
            vector_repo = ModelAwareVectorRepository()
            metadata = [item["chunk_metadata"] for item in persisted]
            knowledge_ids = _resolve_knowledge_projection_ids(
                file_id=file_id,
                admin_id=admin_id,
                requested_knowledge_id=knowledge_id,
                db=db,
            )
            projections = [
                (
                    f"file-{file_id}",
                    _make_vector_items(
                        vector_repo=vector_repo,
                        chunks=success_chunks,
                        vectors=success_vectors,
                        metadata=metadata,
                        rag_chunk_ids=rag_chunk_ids,
                        admin_id=admin_id,
                        model=model,
                        file_id=file_id,
                        knowledge_id=None,
                    ),
                )
            ]
            for current_knowledge_id in knowledge_ids:
                knowledge_metadata = [
                    {**item, "knowledge_id": current_knowledge_id}
                    for item in metadata
                ]
                projections.append(
                    (
                        current_knowledge_id,
                        _make_vector_items(
                            vector_repo=vector_repo,
                            chunks=success_chunks,
                            vectors=success_vectors,
                            metadata=knowledge_metadata,
                            rag_chunk_ids=rag_chunk_ids,
                            admin_id=admin_id,
                            model=model,
                            file_id=file_id,
                            knowledge_id=current_knowledge_id,
                        ),
                    )
                )
            for _, items in projections:
                for item in items:
                    item["index_generation_id"] = state["index_generation_id"]
            vector_repo.upsert_model_aware_many(
                projections=projections,
                model=model,
                session=db,
            )
            state["fragment_manifest_ids"] = list(
                dict.fromkeys(
                    [
                        *state.get("fragment_manifest_ids", []),
                        manifest_id,
                    ]
                )
            )

        remaining = [
            value
            for value in state.get("failed_chunks", [])
            if _descriptor_key(value) != _descriptor_key(descriptor)
        ]
        remaining.extend(failures)
        state["failed_chunks"] = remaining
        state["embedded_chunks"] = int(state.get("embedded_chunks", 0)) + len(
            successes
        )
        state["total_chunks"] = state["embedded_chunks"] + len(remaining)
        state["lease_heartbeat_at"] = now
        state["updated_at"] = now
        meta = dict(row.meta or {})
        meta[AUDIO_REPAIR_STATE_META_KEY] = state
        meta["audio_fragment_manifest_ids"] = list(
            state.get("fragment_manifest_ids", [])
        )
        if VIDEO_AUDIO_ABSENT in prepared.warnings:
            meta["processing_warnings"] = list(
                dict.fromkeys(
                    [
                        *meta.get("processing_warnings", []),
                        VIDEO_AUDIO_ABSENT,
                    ]
                )
            )
        meta["audio_embedding"] = _public_summary(state, "repairing")
        visual_summary = dict(meta.get("visual_summary") or {})
        visual_summary["audio_chunk_count"] = state["embedded_chunks"]
        meta["visual_summary"] = visual_summary
        row.meta = meta
        row.updated_at = now
        db.commit()
    for _ in successes:
        add_metric_counter("retrieval.video.audio_repaired_chunks")


def _finish_repair(
    *,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
    lease_token: str,
    owner: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    with get_db() as db:
        row = _lock_repair_file(db, admin_id, file_id)
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        state = _validated_state(row, admin_id, embedding_model_id, db=db)
        if state.get("lease_token") != lease_token or (
            owner is not None and state.get("execution_owner") != owner
        ):
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        state.pop("lease_token", None)
        state.pop("lease_heartbeat_at", None)
        state.pop("execution_owner", None)
        state["updated_at"] = now
        failed = state.get("failed_chunks") or []
        status = (
            "degraded"
            if failed
            else "complete" if state.get("embedded_chunks") else "not_applicable"
        )
        state["phase"] = status
        meta = dict(row.meta or {})
        if failed:
            meta[AUDIO_REPAIR_STATE_META_KEY] = state
            meta["processing_warnings"] = _degraded_warnings(meta, state)
        else:
            meta.pop(AUDIO_REPAIR_STATE_META_KEY, None)
            warnings = list(meta.get("processing_warnings") or [])
            meta["processing_warnings"] = [
                warning
                for warning in warnings
                if warning
                not in {VIDEO_AUDIO_EMBEDDING_FAILED, VIDEO_AUDIO_FALLBACK_VISUAL_ONLY}
            ]
        summary = _public_summary(state, status)
        meta["audio_embedding"] = summary
        row.meta = meta
        row.updated_at = now
        db.commit()
        return summary


def _release_failed_lease(
    file_id: str,
    lease_token: str,
    *,
    owner: str | None = None,
    abandoned_only: bool = False,
) -> bool:
    try:
        with get_db() as db:
            row = db.query(File).filter(File.id == file_id).with_for_update().first()
            if row is None:
                return False
            meta = dict(row.meta or {})
            state = dict(meta.get(AUDIO_REPAIR_STATE_META_KEY) or {})
            if state.get("lease_token") != lease_token or (
                owner is not None and state.get("execution_owner") != owner
            ):
                return False
            if (
                abandoned_only
                and int(time.time()) - int(state.get("lease_heartbeat_at", 0))
                < REPAIR_LEASE_SECONDS
            ):
                return False
            state.pop("lease_token", None)
            state.pop("lease_heartbeat_at", None)
            state.pop("execution_owner", None)
            state["phase"] = "degraded"
            state["updated_at"] = int(time.time())
            meta[AUDIO_REPAIR_STATE_META_KEY] = state
            meta["audio_embedding"] = _public_summary(state, "degraded")
            meta["processing_warnings"] = _degraded_warnings(meta, state)
            row.meta = meta
            db.commit()
            return True
    except Exception:
        log.warning("Failed to release audio repair lease | file_id=%s", file_id)
        return False


def _degraded_warnings(meta, state):
    warnings = [*meta.get("processing_warnings", []), VIDEO_AUDIO_EMBEDDING_FAILED]
    if not state.get("embedded_chunks"):
        warnings.append(VIDEO_AUDIO_FALLBACK_VISUAL_ONLY)
    return list(dict.fromkeys(warnings))


def _public_summary(state: Mapping[str, Any], status: str) -> dict[str, Any]:
    failed = state.get("failed_chunks")
    failed_count = len(failed) if isinstance(failed, list) else 0
    embedded = max(0, int(state.get("embedded_chunks", 0) or 0))
    return {
        "status": status,
        "total_chunks": embedded + failed_count,
        "embedded_chunks": embedded,
        "failed_chunks": failed_count if status == "degraded" else 0,
        "pending_chunks": failed_count if status in {"queued", "repairing"} else 0,
        "repairable": failed_count > 0 and status == "degraded",
        "updated_at": int(time.time()),
    }


def dispatch_pending_audio(
    *,
    config,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
    reliability_policy: Mapping[str, Any] | None = None,
    knowledge_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch only persisted audio work, preserving it if infrastructure fails."""
    from open_webui.env import ENABLE_JOB_QUEUE
    from open_webui.utils.job_queue import enqueue_audio_repair_job

    try:
        claim = claim_audio_repair(
            file_id=file_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        if claim.status == "repairing":
            return {"status": claim.status, "already_active": True}
        with get_db() as db:
            row = _lock_repair_file(db, admin_id, file_id)
            if row is None:
                raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
            state = _validated_state(
                row, admin_id, embedding_model_id, db=db, validate_source=False
            )
            if (
                state.get("lease_token") != claim.lease_token
                or state.get("phase") != "queued"
            ):
                return {"status": "repairing", "already_active": True}
            policy = dict(reliability_policy or state.get("reliability_policy") or {})
            state.update(
                reliability_policy=policy,
                knowledge_id=knowledge_id,
                dispatch_mode="queue" if ENABLE_JOB_QUEUE else "background",
                dispatch_id=f"audio_repair_{claim.lease_token}",
            )
            row.meta = {**dict(row.meta or {}), AUDIO_REPAIR_STATE_META_KEY: state}
            db.commit()
        payload = dict(
            knowledge_id=knowledge_id,
            file_id=file_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            lease_token=claim.lease_token,
            reliability_policy=policy,
        )
        dispatch_id = state["dispatch_id"]
        if ENABLE_JOB_QUEUE:
            queue_state = _queue_dispatch_state(dispatch_id)
            if queue_state == "missing":
                dispatch_id = enqueue_audio_repair_job(**payload)
            elif queue_state == "failed":
                _release_failed_lease(file_id, claim.lease_token)
                return {"status": "degraded", "already_active": False}
            # Unknown means unavailable infrastructure, never a missing job.
            return {
                "status": "queued",
                "already_active": claim.already_active,
                "dispatch_mode": "queue",
                "job_id": dispatch_id,
            }
        with _runtime_lock:
            global _audio_executor
            if dispatch_id in _background_dispatches:
                return {"status": "queued", "already_active": True}
            if not _background_capacity.acquire(blocking=False):
                return {"status": "queued", "already_active": claim.already_active}
            if _audio_executor is None:
                _audio_executor = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="audio-index"
                )
            _background_dispatches.add(dispatch_id)
            try:
                future = _audio_executor.submit(
                    repair_audio_embeddings, config=config, **payload
                )
            except Exception:
                _background_dispatches.discard(dispatch_id)
                _background_capacity.release()
                raise

        def completed(future):
            try:
                future.result()
            except Exception as error:
                log.warning(
                    "Background audio stopped | file_id=%s type=%s",
                    file_id,
                    type(error).__name__,
                )
            finally:
                with _runtime_lock:
                    _background_dispatches.discard(dispatch_id)
                _background_capacity.release()

        future.add_done_callback(completed)
        return {
            "status": "queued",
            "already_active": claim.already_active,
            "dispatch_mode": "background",
            "job_id": dispatch_id,
        }
    except EmbeddingError as error:
        if error.code == AUDIO_REPAIR_NOT_REQUIRED:
            return {"status": "not_applicable", "already_active": False}
        log.warning("Audio dispatch deferred | file_id=%s code=%s", file_id, error.code)
        return {"status": "queued", "dispatch_mode": "pending"}
    except Exception as error:
        log.warning(
            "Audio dispatch deferred | file_id=%s type=%s",
            file_id,
            type(error).__name__,
        )
        return {"status": "queued", "dispatch_mode": "pending"}


def _queue_dispatch_state(dispatch_id: str) -> str:
    from rq.exceptions import NoSuchJobError
    from rq.job import Job
    from open_webui.utils.job_queue import get_job_queue

    try:
        queue = get_job_queue()
        if queue is None:
            return "unavailable"
        try:
            job = Job.fetch(dispatch_id, connection=queue.connection)
        except NoSuchJobError:
            return "missing"
        status = job.get_status(refresh=True)
        status = getattr(status, "value", status)
        return (
            "failed"
            if status in {"failed", "stopped", "canceled", "finished"}
            else "queued"
        )
    except Exception:
        return "unavailable"


def reconcile_audio_repairs(config) -> None:
    """Recover a bounded page of persisted work without retrying provider failures."""
    global _reconcile_cursor
    with get_db() as db:
        rows = (
            db.query(File.id, File.meta)
            .filter(
                File.id > _reconcile_cursor,
                File.meta[AUDIO_REPAIR_STATE_META_KEY].as_string().isnot(None),
            )
            .order_by(File.id)
            .limit(100)
            .all()
        )
    _reconcile_cursor = str(rows[-1][0]) if len(rows) == 100 else ""
    now = int(time.time())
    for file_id, meta in rows:
        state = (meta or {}).get(AUDIO_REPAIR_STATE_META_KEY)
        if not isinstance(state, dict) or not state.get("failed_chunks"):
            continue
        phase = state.get("phase")
        token = state.get("lease_token")
        if (
            phase == "running"
            and now - int(state.get("lease_heartbeat_at", 0)) >= REPAIR_LEASE_SECONDS
        ):
            if _release_failed_lease(
                file_id, token, owner=state.get("execution_owner"), abandoned_only=True
            ):
                add_metric_counter(
                    "retrieval.video.audio_abandoned_recovery", {"phase": "running"}
                )
        elif (
            phase is None
            and token
            and now - int(state.get("lease_heartbeat_at", 0)) >= REPAIR_LEASE_SECONDS
        ):
            # Pre-upgrade execution leases have no independently renewed owner.
            if _release_failed_lease(file_id, token, abandoned_only=True):
                add_metric_counter(
                    "retrieval.video.audio_abandoned_recovery", {"phase": "legacy"}
                )
        elif phase == "queued" and state.get("admin_id"):
            dispatch_pending_audio(
                config=config,
                file_id=file_id,
                admin_id=state["admin_id"],
                embedding_model_id=state["embedding_model_id"],
                reliability_policy=state.get("reliability_policy"),
                knowledge_id=state.get("knowledge_id"),
            )


def start_audio_repair_reconciliation(config) -> None:
    global _reconciler_thread
    with _runtime_lock:
        if _reconciler_thread is not None and _reconciler_thread.is_alive():
            return
        _reconciler_stop.clear()

        def run():
            while not _reconciler_stop.is_set():
                try:
                    from open_webui.retrieval.embedding.reconciliation import (
                        reconcile_existing_publications,
                    )

                    reconcile_existing_publications(config)
                except Exception as error:
                    log.warning(
                        "Publication reconciliation unavailable | type=%s",
                        type(error).__name__,
                    )
                try:
                    reconcile_audio_repairs(config)
                except Exception as error:
                    log.warning(
                        "Audio reconciliation unavailable | type=%s",
                        type(error).__name__,
                    )
                _reconciler_stop.wait(REPAIR_HEARTBEAT_SECONDS)

        _reconciler_thread = threading.Thread(
            target=run, name="audio-reconciliation", daemon=True
        )
        _reconciler_thread.start()


def stop_audio_repair_reconciliation() -> None:
    global _audio_executor
    _reconciler_stop.set()
    if _reconciler_thread is not None:
        _reconciler_thread.join(timeout=1)
    with _runtime_lock:
        executor, _audio_executor = _audio_executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "AudioRepairClaim",
    "claim_audio_repair",
    "ensure_legacy_audio_repair_state",
    "repair_audio_embeddings",
    "dispatch_pending_audio",
    "reconcile_audio_repairs",
    "start_audio_repair_reconciliation",
    "stop_audio_repair_reconciliation",
]
