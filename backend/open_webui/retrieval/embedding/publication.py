"""One generation-fenced transaction for upload and reindex publication."""

import hashlib
import logging
import time
import uuid
import threading

from open_webui.internal.db import get_db
from open_webui.models.embeddings import (
    AdminEmbeddingModelState,
    EmbeddingJob,
    EmbeddingJobFile,
    RagChunk,
)
from open_webui.models.files import File
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_STALE_OPERATION,
    EMBEDDING_REINDEX_SOURCE_CHANGED,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_MODALITY_UNSUPPORTED,
    safe_file_processing_error_message,
)
from open_webui.retrieval.embedding.metrics import record_index_event

log = logging.getLogger(__name__)
_required_heartbeats = {}
_required_heartbeat_lock = threading.Lock()


def lock_generation(db, admin_id, model_id, generation_id):
    state = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin_id)
        .with_for_update()
        .first()
    )
    if (
        state is None
        or not generation_id
        or state.index_generation_id != generation_id
        or (state.target_embedding_model_id or state.active_embedding_model_id)
        != model_id
    ):
        record_index_event("publication_rejected")
        raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
    return state


def freeze_file_indexing(*, config, file_id, admin_id, embedding_model_id):
    """Freeze the generation, actual source and preparation settings at dispatch."""
    from open_webui.models.users import Users
    from open_webui.retrieval.embedding.file_processing import (
        read_stored_content_provenance,
    )
    from open_webui.retrieval.embedding.inventory import source_sha256_for_file
    from open_webui.retrieval.embedding.preparation import build_preparation_recipe
    from open_webui.retrieval.embedding.state import AdminEmbeddingModelStateRepository

    with get_db() as db:
        state = AdminEmbeddingModelStateRepository.ensure_state(admin_id, config, db=db)
        lock_generation(db, admin_id, embedding_model_id, state.index_generation_id)
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        admin = Users.get_user_by_id(admin_id)
        recipe = build_preparation_recipe(config, admin.email)
        provenance = read_stored_content_provenance(file)
        snapshot = {
            "file_id": file_id,
            "admin_id": admin_id,
            "index_generation_id": state.index_generation_id,
            "source_sha256": source_sha256_for_file(file),
            "content_origin": provenance.origin,
            "content_override_sha256": provenance.content_override_sha256,
            "preparation_recipe": recipe.to_dict(),
            "preparation_recipe_sha256": recipe.sha256,
        }
        db.commit()
        return snapshot


def validate_source(file, snapshot):
    from open_webui.retrieval.embedding.file_processing import (
        read_stored_content_provenance,
    )
    from open_webui.retrieval.embedding.inventory import source_sha256_for_file

    provenance = read_stored_content_provenance(file)
    if (
        source_sha256_for_file(file) != snapshot.get("source_sha256")
        or provenance.origin != snapshot.get("content_origin", "stored_source")
        or provenance.content_override_sha256 != snapshot.get("content_override_sha256")
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)


def claim_required_indexing(*, admin_id, model_id, snapshot, job_id=None):
    """Serialize same-file replacements and optional audio execution."""
    from open_webui.retrieval.embedding.file_processing import (
        AUDIO_REPAIR_STATE_META_KEY,
    )

    token = str(uuid.uuid4())
    now = int(time.time())
    with get_db() as db:
        lock_generation(db, admin_id, model_id, snapshot.get("index_generation_id"))
        if job_id:
            db.query(EmbeddingJob).filter_by(id=job_id).with_for_update().one()
        file = (
            db.query(File).filter_by(id=snapshot["file_id"]).with_for_update().first()
        )
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        meta = dict(file.meta or {})
        repair = meta.get(AUDIO_REPAIR_STATE_META_KEY) or {}
        running = repair.get("phase") == "running" and repair.get(
            "index_generation_id"
        ) == snapshot.get("index_generation_id")
        if (
            running
            and now
            - int(repair.get("lease_heartbeat_at") or repair.get("updated_at") or now)
            < 120
        ):
            raise EmbeddingError(
                EMBEDDING_MODEL_STATE_CONFLICT,
                detail="Audio repair is running for this file. Retry after it finishes.",
            )
        owner = meta.get("required_indexing") or {}
        if (
            owner.get("index_generation_id") == snapshot.get("index_generation_id")
            and now
            - int(owner.get("lease_heartbeat_at") or owner.get("started_at") or now)
            < 120
        ):
            raise EmbeddingError(
                EMBEDDING_MODEL_STATE_CONFLICT,
                detail="This file is already being indexed.",
            )
        validate_source(file, snapshot)
        meta["required_indexing"] = {
            "token": token,
            "index_generation_id": snapshot["index_generation_id"],
            "started_at": now,
            "lease_heartbeat_at": now,
        }
        file.meta = meta
        db.commit()
    stop = threading.Event()
    with _required_heartbeat_lock:
        _required_heartbeats[token] = stop
    threading.Thread(
        target=_heartbeat_required, args=(snapshot["file_id"], token, stop), daemon=True
    ).start()
    return token


def release_required_indexing(file_id, token):
    with _required_heartbeat_lock:
        stop = _required_heartbeats.pop(token, None)
    if stop is not None:
        stop.set()
    try:
        with get_db() as db:
            file = db.query(File).filter_by(id=file_id).with_for_update().first()
            if file is not None:
                meta = dict(file.meta or {})
                if (meta.get("required_indexing") or {}).get("token") == token:
                    meta.pop("required_indexing", None)
                    file.meta = meta
                    db.commit()
    except Exception as error:
        # Publication has its own atomic outcome. Cleanup cannot undo a commit
        # or replace the original error; the heartbeat lease will expire.
        log.warning(
            "required_index_release_failed file=%s type=%s",
            file_id,
            type(error).__name__,
        )


def _heartbeat_required(file_id, token, stop):
    while not stop.wait(30):
        try:
            with get_db() as db:
                file = db.query(File).filter_by(id=file_id).with_for_update().first()
                meta = dict(file.meta or {}) if file is not None else {}
                owner = dict(meta.get("required_indexing") or {})
                if owner.get("token") != token:
                    break
                owner["lease_heartbeat_at"] = int(time.time())
                meta["required_indexing"] = owner
                file.meta = meta
                db.commit()
        except Exception as error:
            log.warning(
                "required_index_heartbeat_failed file=%s type=%s",
                file_id,
                type(error).__name__,
            )
    with _required_heartbeat_lock:
        _required_heartbeats.pop(token, None)


def publish_prepared_file(
    *,
    admin_id,
    model,
    snapshot,
    prepared,
    vectors,
    owner_token,
    job_id=None,
    incompatible_code=None,
    requested_knowledge_id=None,
):
    """Publish all required projections, readiness, ledger and first activation."""
    from open_webui.retrieval.embedding.file_processing import (
        _apply_completed_file_state,
        _resolve_knowledge_projection_ids,
    )
    from open_webui.retrieval.embedding.jobs import EmbeddingJobRepository
    from open_webui.retrieval.embedding.preparation import (
        build_persisted_chunks,
        preparation_recipe_from_snapshot,
    )
    from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository

    file_id = snapshot["file_id"]
    generation = snapshot.get("index_generation_id")
    recipe = preparation_recipe_from_snapshot(snapshot)
    if (
        prepared.source_sha256 != snapshot.get("source_sha256")
        or not prepared.chunks
        or len(vectors) != len(prepared.chunks)
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
    if any(
        chunk.chunk_metadata.get("preparation_recipe_sha256") != recipe.sha256
        for chunk in prepared.chunks
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
    chunks = build_persisted_chunks(prepared, admin_id=admin_id, file_id=file_id)
    manifest_id = RagChunk.build_manifest_id(
        chunks,
        source_sha256=prepared.source_sha256,
        extraction_version=prepared.extraction_version,
    )
    vector_repo = ModelAwareVectorRepository()
    with get_db() as db:
        state = lock_generation(db, admin_id, model.id, generation)
        job_file = None
        if job_id:
            job = (
                db.query(EmbeddingJob)
                .filter_by(id=job_id, admin_id=admin_id)
                .with_for_update()
                .one()
            )
            if (
                job.index_generation_id != generation
                or job.embedding_model_id != model.id
            ):
                raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
            job_file = (
                db.query(EmbeddingJobFile)
                .filter_by(job_id=job_id, file_id=file_id)
                .with_for_update()
                .one()
            )
            if job_file.status != "processing":
                raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
            if (
                preparation_recipe_from_snapshot(job_file.file_snapshot).sha256
                != recipe.sha256
            ):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        if ((file.meta or {}).get("required_indexing") or {}).get(
            "token"
        ) != owner_token:
            raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
        validate_source(file, snapshot)
        knowledge_ids = _resolve_knowledge_projection_ids(
            file_id=file_id,
            admin_id=admin_id,
            requested_knowledge_id=requested_knowledge_id,
            db=db,
        )
        if not job_id and not knowledge_ids:
            from open_webui.retrieval.embedding.inventory import (
                build_reindex_admin_resolver,
            )

            resolver = build_reindex_admin_resolver(db)
            if resolver.resolve_user(file.user_id) != admin_id:
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        # Job inventory members must still be in the administrator's scope.
        if job_id:
            from open_webui.retrieval.embedding.inventory import build_reindex_inventory

            if not build_reindex_inventory(
                admin_id, db=db, preparation_recipe=recipe, file_ids={file_id}
            ):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        ids = RagChunk.insert_chunks(
            admin_id, file_id, chunks, manifest_id=manifest_id, db=db
        )
        projection_ids = [f"file-{file_id}", *knowledge_ids]
        projections = []
        for collection in projection_ids:
            knowledge_id = None if collection == f"file-{file_id}" else collection
            items = vector_repo.make_items(
                texts=[chunk.content for chunk in prepared.chunks],
                vectors=vectors,
                metadata=[chunk["chunk_metadata"] for chunk in chunks],
                rag_chunk_ids=ids,
                admin_id=admin_id,
                model=model,
                file_id=file_id,
                knowledge_id=knowledge_id,
                modalities=[chunk.modality for chunk in prepared.chunks],
                embedding_status="active",
                embedding_job_id=job_id,
                index_generation_id=generation,
            )
            projections.append((collection, items))
        vector_repo.reconcile_model_aware_many(
            projections=projections, model=model, session=db
        )
        repair = dict(prepared.audio_repair_state)
        if repair:
            repair.update(
                admin_id=admin_id,
                index_generation_id=generation,
                base_manifest_id=manifest_id,
            )
            repair.update(
                content_origin=snapshot.get("content_origin"),
                content_override_sha256=snapshot.get("content_override_sha256"),
            )
        _apply_completed_file_state(
            row=file,
            extracted_text=prepared.text_content,
            source_sha256=prepared.source_sha256,
            extraction_version=prepared.extraction_version,
            manifest_id=manifest_id,
            processing_warnings=prepared.warnings,
            visual_summary=prepared.visual_summary,
            audio_embedding=prepared.audio_embedding,
            audio_repair_state=repair,
            collection_name=f"file-{file_id}",
        )
        meta = dict(file.meta or {})
        meta.pop("required_indexing", None)
        meta.update(
            index_generation_id=generation,
            embedding_model_id=model.id,
            preparation_recipe_sha256=recipe.sha256,
            published_projection_ids=projection_ids,
        )
        meta.update(
            published_content_origin=snapshot.get("content_origin", "stored_source"),
            published_content_override_sha256=snapshot.get("content_override_sha256"),
        )
        file.meta = meta
        if job_file is not None:
            summary = {
                "text_content": prepared.text_content,
                "content_hash": hashlib.sha256(
                    prepared.text_content.encode()
                ).hexdigest(),
                "source_sha256": prepared.source_sha256,
                "extraction_version": prepared.extraction_version,
                "manifest_id": manifest_id,
                "chunk_count": len(ids),
                "rag_chunk_ids": ids,
                "projection_ids": projection_ids,
                "processing_warnings": list(prepared.warnings),
                "visual_summary": dict(prepared.visual_summary),
                "audio_embedding": dict(prepared.audio_embedding),
                "audio_repair_state": repair,
            }
            job_file.file_snapshot = {
                **job_file.file_snapshot,
                "prepared_processing_summary": summary,
                "published_generation_id": generation,
            }
            if incompatible_code:
                EmbeddingJobRepository.mark_file_incompatible(
                    job_id, file_id, incompatible_code, db=db
                )
            else:
                EmbeddingJobRepository.mark_file_completed(job_id, file_id, db=db)
        activated = state.target_embedding_model_id is not None
        state.active_embedding_model_id = model.id
        state.target_embedding_model_id = None
        state.updated_at = int(time.time())
        db.commit()
    record_index_event("published")
    log.info(
        "index_file_published admin=%s generation=%s file=%s job=%s activated=%s",
        admin_id,
        generation,
        file_id,
        job_id,
        activated,
    )
    return tuple(projection_ids)


def publish_file_incompatibility(
    *, admin_id, model_id, snapshot, owner_token, job_id, error_code
):
    """Commit a complete modality rejection with the same fences as publication."""
    from open_webui.retrieval.embedding.file_processing import (
        _resolve_knowledge_projection_ids,
    )
    from open_webui.retrieval.embedding.inventory import build_reindex_inventory
    from open_webui.retrieval.embedding.jobs import EmbeddingJobRepository
    from open_webui.retrieval.embedding.preparation import (
        preparation_recipe_from_snapshot,
    )

    # PDF visual warnings belong to successful text publication, never here.
    if error_code != EMBEDDING_MODALITY_UNSUPPORTED:
        raise ValueError("only complete modality rejection can fail file processing")
    file_id = snapshot["file_id"]
    generation = snapshot.get("index_generation_id")
    recipe = preparation_recipe_from_snapshot(snapshot)
    with get_db() as db:
        lock_generation(db, admin_id, model_id, generation)
        job = (
            db.query(EmbeddingJob)
            .filter_by(id=job_id, admin_id=admin_id)
            .with_for_update()
            .first()
        )
        if (
            job is None
            or job.status != "processing"
            or job.index_generation_id != generation
            or job.embedding_model_id != model_id
        ):
            raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
        job_file = (
            db.query(EmbeddingJobFile)
            .filter_by(job_id=job_id, file_id=file_id)
            .with_for_update()
            .first()
        )
        if job_file is None or job_file.status != "processing":
            raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
        if (
            preparation_recipe_from_snapshot(job_file.file_snapshot).sha256
            != recipe.sha256
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        meta = dict(file.meta or {})
        owner = meta.get("required_indexing") or {}
        if (
            not owner_token
            or owner.get("token") != owner_token
            or owner.get("index_generation_id") != generation
        ):
            raise EmbeddingError(EMBEDDING_JOB_STALE_OPERATION)
        validate_source(file, snapshot)
        _resolve_knowledge_projection_ids(
            file_id=file_id,
            admin_id=admin_id,
            requested_knowledge_id=None,
            db=db,
        )
        if not build_reindex_inventory(
            admin_id, db=db, preparation_recipe=recipe, file_ids={file_id}
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        EmbeddingJobRepository.mark_file_incompatible(
            job_id, file_id, error_code, db=db
        )
        now = int(time.time())
        meta.pop("required_indexing", None)
        meta.update(
            processing_status="error",
            processing_completed_at=now,
            processing_error_code=error_code,
            processing_error=safe_file_processing_error_message(error_code),
        )
        file.meta = meta
        file.updated_at = now
        db.commit()


def reuse_current_publication(job_id, file_id):
    """Satisfy a queued file from a successful upload that finished meanwhile."""
    from open_webui.retrieval.embedding.gate import file_publication_is_current
    from open_webui.retrieval.embedding.jobs import EmbeddingJobRepository
    from open_webui.retrieval.embedding.file_processing import (
        _resolve_knowledge_projection_ids,
        read_stored_content_provenance,
    )
    from open_webui.retrieval.embedding.inventory import (
        build_reindex_inventory,
        source_sha256_for_file,
    )
    from open_webui.retrieval.embedding.preparation import (
        preparation_recipe_from_snapshot,
    )

    with get_db() as db:
        job = db.query(EmbeddingJob).filter_by(id=job_id).first()
        if job is None:
            return False
        state = lock_generation(
            db, job.admin_id, job.embedding_model_id, job.index_generation_id
        )
        db.query(EmbeddingJob).filter_by(id=job_id).with_for_update().one()
        job_file = (
            db.query(EmbeddingJobFile)
            .filter_by(job_id=job_id, file_id=file_id)
            .with_for_update()
            .first()
        )
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if (
            job_file is None
            or job_file.status != "pending"
            or not file_publication_is_current(file, state, f"file-{file_id}")
        ):
            return False
        meta = file.meta or {}
        provenance = read_stored_content_provenance(file)
        if (
            meta.get("source_sha256") != source_sha256_for_file(file)
            or meta.get("published_content_origin", "stored_source")
            != provenance.origin
            or meta.get("published_content_override_sha256")
            != provenance.content_override_sha256
        ):
            return False
        recipe = preparation_recipe_from_snapshot(job_file.file_snapshot)
        if not build_reindex_inventory(
            job.admin_id, db=db, preparation_recipe=recipe, file_ids={file_id}
        ):
            return False
        knowledge_ids = _resolve_knowledge_projection_ids(
            file_id=file_id,
            admin_id=job.admin_id,
            requested_knowledge_id=None,
            db=db,
        )
        if any(
            not file_publication_is_current(file, state, collection)
            for collection in knowledge_ids
        ):
            return False
        if EmbeddingJobRepository.claim_file(job_id, file_id, db=db) is None:
            return False
        EmbeddingJobRepository.mark_file_completed(job_id, file_id, db=db)
        job_file.file_snapshot = {
            **job_file.file_snapshot,
            "published_generation_id": state.index_generation_id,
            "satisfied_by_existing_publication": True,
        }
        db.commit()
        return True
