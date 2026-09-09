"""Idempotent, additive repair of failed video-audio embedding leaves."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping

from open_webui.internal.db import get_db
from open_webui.models.embeddings import RagChunk
from open_webui.models.files import File, Files
from open_webui.models.users import Users
from open_webui.retrieval.embedding.errors import (
    AUDIO_REPAIR_NOT_REQUIRED,
    AUDIO_REPAIR_STATE_STALE,
    AUDIO_REPAIR_UNAVAILABLE,
    EmbeddingError,
    VIDEO_AUDIO_EMBEDDING_FAILED,
    VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
)
from open_webui.retrieval.embedding.file_processing import (
    AUDIO_REPAIR_STATE_META_KEY,
    _embed_audio_chunk_with_splitting,
    _make_vector_items,
    _read_source,
    _resolve_knowledge_projection_ids,
    _split_audio_prepared_chunk,
    resolve_authoritative_content_provenance,
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
# Longer than the maximum configured provider attempt sequence. A heartbeat is
# also written before each adaptive leaf request, so only abandoned work becomes
# reclaimable while a valid provider call remains protected from overlap.
REPAIR_LEASE_SECONDS = 4_500


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
    """Claim or join the current repair lease under the file row lock."""
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        state = _validated_state(row, admin_id, embedding_model_id, db=db)
        failed = state.get("failed_chunks")
        if not isinstance(failed, list) or not failed:
            raise EmbeddingError(AUDIO_REPAIR_NOT_REQUIRED)
        current_token = state.get("lease_token")
        heartbeat = state.get("lease_heartbeat_at")
        if (
            isinstance(current_token, str)
            and isinstance(heartbeat, int)
            and now - heartbeat < REPAIR_LEASE_SECONDS
        ):
            return AudioRepairClaim(current_token, "repairing", True)

        lease_token = str(uuid.uuid4())
        state.update(
            {
                "lease_token": lease_token,
                "lease_heartbeat_at": now,
                "repair_started_at": now,
                "updated_at": now,
            }
        )
        meta = dict(row.meta or {})
        meta[AUDIO_REPAIR_STATE_META_KEY] = state
        meta["audio_embedding"] = _public_summary(state, "repairing")
        row.meta = meta
        row.updated_at = now
        db.commit()
        add_metric_counter("retrieval.video.audio_repair_requests", {"outcome": "claimed"})
        return AudioRepairClaim(lease_token, "repairing", False)


def repair_audio_embeddings(
    *,
    config,
    knowledge_id: str,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
    lease_token: str,
    reliability_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Repair failed leaves and commit every success with an additive upsert."""
    started_at = time.monotonic()
    call_id = str(uuid.uuid4())
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
        for descriptor in requested:
            chunk = _reconstruct_failed_chunk(prepared, descriptor)
            successes, failures = _embed_audio_chunk_with_splitting(
                chunk=chunk,
                embedding_service=service,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                split_depth=int(descriptor.get("split_depth", 0)),
                split_path=str(descriptor.get("split_path", "")),
                heartbeat=lambda: _heartbeat_audio_repair(file_id, lease_token),
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
            )
        summary = _finish_repair(
            file_id=file_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            lease_token=lease_token,
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
        _release_failed_lease(file_id, lease_token)
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


def _validated_state(row: File, admin_id: str, embedding_model_id: str, *, db):
    state_view = AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
    if (
        state_view is None
        or state_view.active_embedding_model_id != embedding_model_id
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    state = dict((row.meta or {}).get(AUDIO_REPAIR_STATE_META_KEY) or {})
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
        state.get("source_sha256") != _source_sha256(row)
        or state.get("embedding_model_id") != embedding_model_id
    ):
        raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
    return state


def _heartbeat_audio_repair(file_id: str, lease_token: str) -> None:
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        meta = dict(row.meta or {})
        state = dict(meta.get(AUDIO_REPAIR_STATE_META_KEY) or {})
        if state.get("lease_token") != lease_token:
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        state["lease_heartbeat_at"] = now
        state["updated_at"] = now
        meta[AUDIO_REPAIR_STATE_META_KEY] = state
        row.meta = meta
        row.updated_at = now
        db.commit()


def _source_sha256(row: File) -> str:
    _, source_bytes = _read_source(row.path)
    return hashlib.sha256(source_bytes).hexdigest()


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
    if chunk.content_sha256 != descriptor.get("audio_sha256"):
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
    knowledge_id: str,
    admin_id: str,
    model,
    prepared: PreparedFile,
    descriptor: Mapping[str, Any],
    successes: list[tuple[PreparedChunk, tuple[float, ...]]],
    failures: list[dict[str, Any]],
    lease_token: str,
) -> None:
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        state = _validated_state(row, admin_id, model.id, db=db)
        if state.get("lease_token") != lease_token:
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)

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
            vector_repo.upsert_model_aware_many(
                projections=projections,
                model=model,
                session=db,
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
) -> dict[str, Any]:
    now = int(time.time())
    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(AUDIO_REPAIR_UNAVAILABLE)
        state = _validated_state(row, admin_id, embedding_model_id, db=db)
        if state.get("lease_token") != lease_token:
            raise EmbeddingError(AUDIO_REPAIR_STATE_STALE)
        state.pop("lease_token", None)
        state.pop("lease_heartbeat_at", None)
        state["updated_at"] = now
        failed = state.get("failed_chunks") or []
        status = "degraded" if failed else "complete"
        meta = dict(row.meta or {})
        if failed:
            meta[AUDIO_REPAIR_STATE_META_KEY] = state
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


def _release_failed_lease(file_id: str, lease_token: str) -> None:
    try:
        with get_db() as db:
            row = db.query(File).filter(File.id == file_id).with_for_update().first()
            if row is None:
                return
            meta = dict(row.meta or {})
            state = dict(meta.get(AUDIO_REPAIR_STATE_META_KEY) or {})
            if state.get("lease_token") != lease_token:
                return
            state.pop("lease_token", None)
            state.pop("lease_heartbeat_at", None)
            state["updated_at"] = int(time.time())
            meta[AUDIO_REPAIR_STATE_META_KEY] = state
            meta["audio_embedding"] = _public_summary(state, "degraded")
            row.meta = meta
            db.commit()
    except Exception:
        log.warning("Failed to release audio repair lease | file_id=%s", file_id)


def _public_summary(state: Mapping[str, Any], status: str) -> dict[str, Any]:
    failed = state.get("failed_chunks")
    failed_count = len(failed) if isinstance(failed, list) else 0
    embedded = max(0, int(state.get("embedded_chunks", 0) or 0))
    return {
        "status": status,
        "total_chunks": embedded + failed_count,
        "embedded_chunks": embedded,
        "failed_chunks": failed_count,
        "repairable": failed_count > 0,
        "updated_at": int(time.time()),
    }


__all__ = [
    "AudioRepairClaim",
    "claim_audio_repair",
    "ensure_legacy_audio_repair_state",
    "repair_audio_embeddings",
]
