"""Resume pre-generation publications without calling embedding providers."""

import logging
import time

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
    EMBEDDING_REINDEX_SOURCE_CHANGED,
)
from open_webui.retrieval.embedding.metrics import record_index_event
from open_webui.retrieval.embedding.publication import lock_generation, validate_source

log = logging.getLogger(__name__)
_cursor = ""


def reconcile_existing_publications(config=None):
    """Inspect a bounded page; each file recovery commits independently."""
    global _cursor
    from open_webui.retrieval.vector.dbs.pgvector import DocumentChunk

    with get_db() as db:
        file_ids = [
            row[0]
            for row in db.query(File.id)
            .filter(File.id > _cursor)
            .order_by(File.id)
            .limit(100)
            .all()
        ]
    _cursor = file_ids[-1] if len(file_ids) == 100 else ""
    for file_id in file_ids:
        with get_db() as db:
            file = db.query(File).filter_by(id=file_id).first()
            if file is None:
                continue
            candidate_admins = {
                row[0]
                for row in db.query(DocumentChunk.admin_id)
                .filter_by(file_id=file_id)
                .distinct()
                .all()
                if row[0]
            }
            candidate_admins.update(
                row[0]
                for row in db.query(EmbeddingJob.admin_id)
                .join(EmbeddingJobFile, EmbeddingJobFile.job_id == EmbeddingJob.id)
                .filter(
                    EmbeddingJobFile.file_id == file_id,
                    EmbeddingJobFile.status.in_(["completed", "incompatible"]),
                )
                .distinct()
                .all()
            )
        for admin_id in sorted(candidate_admins):
            with get_db() as db:
                expected_generation = (
                    db.query(AdminEmbeddingModelState.index_generation_id)
                    .filter_by(admin_id=admin_id)
                    .scalar()
                )
            try:
                _recover_file(admin_id, file_id)
            except (EmbeddingError, ValueError, TypeError, KeyError) as error:
                log.warning(
                    "index_publication_recovery_unavailable admin=%s file=%s type=%s",
                    admin_id,
                    file_id,
                    type(error).__name__,
                )
                try:
                    _mark_recovery_failure(admin_id, file_id, expected_generation)
                except Exception as failure_error:
                    log.warning(
                        "index_publication_recovery_deferred file=%s type=%s",
                        file_id,
                        type(failure_error).__name__,
                    )
            except Exception as error:
                # Infrastructure failures are retried on the next sweep.
                log.warning(
                    "index_publication_recovery_deferred file=%s type=%s",
                    file_id,
                    type(error).__name__,
                )


def _recover_file(admin_id, file_id):
    from open_webui.retrieval.embedding.file_processing import (
        _apply_completed_file_state,
        _resolve_knowledge_projection_ids,
        AUDIO_REPAIR_STATE_META_KEY,
    )
    from open_webui.retrieval.embedding.jobs import _generation_lineage
    from open_webui.retrieval.embedding.preparation import (
        preparation_recipe_from_snapshot,
    )
    from open_webui.retrieval.vector.dbs.pgvector import DocumentChunk

    with get_db() as db:
        state = (
            db.query(AdminEmbeddingModelState)
            .filter_by(admin_id=admin_id)
            .with_for_update()
            .first()
        )
        if state is None:
            return
        generation = state.index_generation_id
        model_id = state.target_embedding_model_id or state.active_embedding_model_id
        lock_generation(db, admin_id, model_id, generation)
        baseline = generation == f"baseline:{admin_id}"
        job_file = None
        if state.latest_embedding_job_id:
            lineage = _generation_lineage(db, state.latest_embedding_job_id)
            jobs = {
                job.id: job
                for job in db.query(EmbeddingJob)
                .filter(
                    EmbeddingJob.id.in_(lineage),
                    EmbeddingJob.admin_id == admin_id,
                    EmbeddingJob.index_generation_id == generation,
                )
                .order_by(EmbeddingJob.id)
                .with_for_update()
                .all()
            }
            rows = {
                row.job_id: row
                for row in db.query(EmbeddingJobFile)
                .filter(
                    EmbeddingJobFile.job_id.in_(list(jobs)),
                    EmbeddingJobFile.file_id == file_id,
                )
                .with_for_update()
                .all()
            }
            job_file = next(
                (rows[job_id] for job_id in lineage if job_id in rows), None
            )
            if job_file is not None and (
                job_file.status not in {"completed", "incompatible"}
                or jobs[job_file.job_id].index_generation_id != generation
            ):
                return
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if file is None:
            return
        meta = dict(file.meta or {})
        if _has_current_publication(meta, generation, model_id):
            return
        owner = meta.get("required_indexing") or {}
        if (
            owner.get("index_generation_id") == generation
            and int(time.time())
            - int(owner.get("lease_heartbeat_at") or owner.get("started_at") or 0)
            < 120
        ):
            return
        if job_file is None:
            if (
                meta.get("processing_status", (file.data or {}).get("status"))
                != "completed"
            ):
                return
            if meta.get("publication_recovery_generation_id") == generation:
                return
            if not baseline and (
                state.target_embedding_model_id is not None
                or not db.query(DocumentChunk.id)
                .filter_by(
                    admin_id=admin_id,
                    file_id=file_id,
                    embedding_model_id=model_id,
                    index_generation_id=generation,
                    embedding_status="active",
                )
                .first()
            ):
                return
        if job_file is not None:
            snapshot = job_file.file_snapshot
            if not isinstance(snapshot, dict):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
            summary = snapshot.get("prepared_processing_summary")
            if job_file.status == "incompatible" and not isinstance(summary, dict):
                # Intentional unsupported-file outcomes are not failed indexes.
                return
            if not isinstance(summary, dict):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
            if summary.get("source_sha256") != snapshot.get("source_sha256"):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
            recipe_sha = preparation_recipe_from_snapshot(snapshot).sha256
            validate_source(file, snapshot)
            from open_webui.retrieval.embedding.inventory import build_reindex_inventory

            if not build_reindex_inventory(
                admin_id,
                db=db,
                preparation_recipe=preparation_recipe_from_snapshot(snapshot),
                file_ids={file_id},
            ):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        else:
            from open_webui.retrieval.embedding.inventory import source_sha256_for_file

            if meta.get("source_sha256") != source_sha256_for_file(
                file
            ) or not meta.get("source_sha256"):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
            summary = {
                "manifest_id": meta.get("chunk_manifest_id"),
                "source_sha256": meta.get("source_sha256"),
                "extraction_version": meta.get("extraction_version"),
                "text_content": (file.data or {}).get("content", ""),
                "processing_warnings": meta.get("processing_warnings", []),
                "visual_summary": meta.get("visual_summary", {}),
                "audio_embedding": meta.get("audio_embedding", {}),
                "audio_repair_state": meta.get(AUDIO_REPAIR_STATE_META_KEY, {}),
            }
            recipe_sha = meta.get("preparation_recipe_sha256")
        if not isinstance(summary.get("text_content"), str):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        manifest = summary.get("manifest_id")
        repair = dict(summary.get("audio_repair_state") or {})
        fragment_ids = list(repair.get("fragment_manifest_ids") or [])
        if (
            meta.get("chunk_manifest_id") == manifest
            and meta.get("source_sha256") == summary["source_sha256"]
            and meta.get("index_generation_id") in {None, generation}
            and meta.get("embedding_model_id") in {None, model_id}
        ):
            # Audio repair checkpoints update the file, not its frozen job row.
            fragment_ids.extend(meta.get("audio_fragment_manifest_ids") or [])
            repair = dict(meta.get(AUDIO_REPAIR_STATE_META_KEY) or repair)
            fragment_ids.extend(repair.get("fragment_manifest_ids") or [])
            summary = {
                **summary,
                "audio_embedding": meta.get(
                    "audio_embedding", summary.get("audio_embedding", {})
                ),
                "visual_summary": meta.get(
                    "visual_summary", summary.get("visual_summary", {})
                ),
            }
        fragment_ids = list(dict.fromkeys(fragment_ids))
        chunks = _validated_manifest(
            db, admin_id, file_id, manifest, summary, recipe_sha
        )
        if not recipe_sha:
            recipes = {
                (chunk.chunk_metadata or {}).get("preparation_recipe_sha256")
                for chunk in chunks
            }
            recipe_sha = next(iter(recipes)) if len(recipes) == 1 else None
        for fragment_id in fragment_ids:
            if fragment_id == manifest:
                continue
            fragment = _validated_manifest(
                db, admin_id, file_id, fragment_id, summary, recipe_sha
            )
            if any(chunk.content_type != "audio" for chunk in fragment):
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
            chunks.extend(fragment)
        knowledge_ids = _resolve_knowledge_projection_ids(
            file_id=file_id, admin_id=admin_id, requested_knowledge_id=None, db=db
        )
        if not knowledge_ids:
            from open_webui.retrieval.embedding.inventory import (
                build_reindex_admin_resolver,
            )

            if build_reindex_admin_resolver(db).resolve_user(file.user_id) != admin_id:
                raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        projection_ids = [f"file-{file_id}", *knowledge_ids]
        ids = {chunk.id for chunk in chunks}
        vectors = (
            db.query(DocumentChunk)
            .filter_by(
                admin_id=admin_id,
                file_id=file_id,
                embedding_model_id=model_id,
                index_generation_id=generation,
            )
            .filter(DocumentChunk.embedding_status.in_(["active", "building"]))
            .all()
        )
        actual = {}
        for vector in vectors:
            actual.setdefault(vector.collection_name, []).append(vector.rag_chunk_id)
        if any(
            set(actual.get(collection, [])) != ids
            or len(actual.get(collection, [])) != len(ids)
            for collection in projection_ids
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        if any(
            vector.vector is None
            for vector in vectors
            if vector.collection_name in projection_ids
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        if repair:
            from open_webui.retrieval.embedding.file_processing import (
                read_stored_content_provenance,
            )

            provenance = read_stored_content_provenance(file)
            repair.update(
                admin_id=admin_id,
                index_generation_id=generation,
                base_manifest_id=manifest,
                fragment_manifest_ids=fragment_ids,
                content_origin=provenance.origin,
                content_override_sha256=provenance.content_override_sha256,
            )
        _apply_completed_file_state(
            row=file,
            extracted_text=summary["text_content"],
            source_sha256=summary["source_sha256"],
            extraction_version=summary.get("extraction_version"),
            manifest_id=manifest,
            processing_warnings=summary.get("processing_warnings", []),
            visual_summary=summary.get("visual_summary", {}),
            audio_embedding=summary.get("audio_embedding", {}),
            audio_repair_state=repair,
            collection_name=f"file-{file_id}",
        )
        file.meta = {
            **file.meta,
            "index_generation_id": generation,
            "embedding_model_id": model_id,
            "published_projection_ids": projection_ids,
            "preparation_recipe_sha256": recipe_sha,
            "audio_fragment_manifest_ids": fragment_ids,
        }
        file.meta.pop("publication_recovery_error", None)
        file.meta.pop("publication_recovery_generation_id", None)
        file.meta.pop("required_indexing", None)
        for vector in vectors:
            if vector.collection_name in projection_ids:
                vector.embedding_status = "active"
        state.active_embedding_model_id = model_id
        state.target_embedding_model_id = None
        state.updated_at = int(time.time())
        if job_file is not None:
            job_file.file_snapshot = {
                **job_file.file_snapshot,
                "published_generation_id": generation,
            }
        db.commit()
    record_index_event("published")
    log.info(
        "index_publication_recovered admin=%s generation=%s file=%s",
        admin_id,
        generation,
        file_id,
    )


def _has_current_publication(meta, generation, model_id):
    return (
        meta.get("index_generation_id") == generation
        and meta.get("embedding_model_id") == model_id
        and meta.get("processing_status") == "completed"
        and isinstance(meta.get("published_projection_ids"), list)
        and bool(meta["published_projection_ids"])
    )


def _validated_manifest(db, admin_id, file_id, manifest_id, summary, recipe_sha):
    chunks = (
        db.query(RagChunk)
        .filter_by(
            admin_id=admin_id,
            file_id=file_id,
            manifest_id=manifest_id,
        )
        .order_by(RagChunk.chunk_index)
        .all()
    )
    records = [
        {
            "content": chunk.content or "",
            "content_type": chunk.content_type,
            "content_sha256": chunk.content_sha256,
            "chunk_metadata": chunk.chunk_metadata or {},
        }
        for chunk in chunks
    ]
    if (
        not chunks
        or RagChunk.build_manifest_id(
            records,
            source_sha256=summary["source_sha256"],
            extraction_version=summary.get("extraction_version"),
        )
        != manifest_id
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
    if any(
        (chunk.chunk_metadata or {}).get("source_sha256") != summary["source_sha256"]
        or (
            recipe_sha
            and (chunk.chunk_metadata or {}).get("preparation_recipe_sha256")
            != recipe_sha
        )
        for chunk in chunks
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
    return chunks


def _mark_recovery_failure(admin_id, file_id, expected_generation):
    """Make an unverifiable success retryable without overwriting newer work."""
    from open_webui.retrieval.embedding.jobs import (
        _generation_lineage,
        _recompute_counters,
    )

    with get_db() as db:
        state = (
            db.query(AdminEmbeddingModelState)
            .filter_by(admin_id=admin_id)
            .with_for_update()
            .first()
        )
        if state is None or state.index_generation_id != expected_generation:
            return
        model_id = state.target_embedding_model_id or state.active_embedding_model_id
        jobs, rows, lineage = {}, {}, []
        if state.latest_embedding_job_id:
            lineage = _generation_lineage(db, state.latest_embedding_job_id)
            jobs = {
                job.id: job
                for job in db.query(EmbeddingJob)
                .filter(
                    EmbeddingJob.id.in_(lineage),
                    EmbeddingJob.admin_id == admin_id,
                    EmbeddingJob.index_generation_id == expected_generation,
                )
                .order_by(EmbeddingJob.id)
                .with_for_update()
                .all()
            }
            rows = {
                row.job_id: row
                for row in db.query(EmbeddingJobFile)
                .filter(
                    EmbeddingJobFile.job_id.in_(list(jobs)),
                    EmbeddingJobFile.file_id == file_id,
                )
                .with_for_update()
                .all()
            }
        job_file = next((rows[job_id] for job_id in lineage if job_id in rows), None)
        file = db.query(File).filter_by(id=file_id).with_for_update().first()
        if file is None or _has_current_publication(
            file.meta or {}, expected_generation, model_id
        ):
            return
        now = int(time.time())
        owner = (file.meta or {}).get("required_indexing") or {}
        if (
            owner.get("index_generation_id") == expected_generation
            and now
            - int(owner.get("lease_heartbeat_at") or owner.get("started_at") or 0)
            < 120
        ):
            return
        if job_file is not None and job_file.status not in {
            "completed",
            "incompatible",
        }:
            return
        message = (
            "This file's saved index could not be verified. Retry indexing this file."
        )
        file.meta = {
            **dict(file.meta or {}),
            "publication_recovery_error": message,
            "publication_recovery_generation_id": expected_generation,
            "processing_status": "error",
            "processing_error_code": EMBEDDING_REINDEX_SOURCE_CHANGED,
            "processing_error": message,
        }
        if job_file is not None:
            job_file.status = "failed"
            job_file.error_code = EMBEDDING_REINDEX_SOURCE_CHANGED
            job_file.error_message = message
            job_file.updated_at = now
            job_file.completed_at = now
            db.flush()
            job = jobs[job_file.job_id]
            _recompute_counters(db, job.id)
            if job.status in {"completed", "failed", "partially_failed"}:
                job.status = (
                    "partially_failed"
                    if job.processed_files + job.incompatible_files
                    else "failed"
                )
            job.updated_at = now
        db.commit()
