"""Shared, model-aware ingestion for stored files.

This module owns the normal file-ingestion transaction boundary used by both
FastAPI background tasks and RQ workers. It resolves the frozen execution
context, prepares and embeds required text/image/video chunks, publishes their
vectors atomically, and leaves optional audio descriptors for independent repair
execution. No caller is
allowed to rebuild parallel text, modality, hash, or metadata lists independently.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from open_webui.internal.db import get_db
from open_webui.models.files import File, Files
from open_webui.models.knowledge import Knowledge
from open_webui.models.users import Users
from open_webui.retrieval.embedding.errors import (
    EMBEDDING_FILE_NOT_FOUND,
    FILE_PROCESSING_FAILED,
    EmbeddingError,
    safe_file_processing_error_message,
)
from open_webui.retrieval.embedding.preparation import (
    PreparationRecipe,
    PreparedChunk,
    PreparedFile,
    prepare_file_for_embedding,
)
from open_webui.retrieval.embedding.inputs import AudioEmbeddingInput
from open_webui.retrieval.embedding.reliability import (
    EmbeddingReliabilityPolicy,
    snapshot_reliability_policy,
)
from open_webui.retrieval.embedding.resolution import (
    resolve_frozen,
)
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository
from open_webui.storage.provider import Storage
from open_webui.retrieval.video_audio import split_pcm_wav


log = logging.getLogger(__name__)

AUDIO_REPAIR_STATE_META_KEY = "audio_embedding_repair_state"


@dataclass(frozen=True)
class FileProcessingResult:
    """Safe completion data shared by background and RQ callers."""

    file_id: str
    collection_names: tuple[str, ...]
    chunk_count: int
    text_chunk_count: int
    image_chunk_count: int
    video_chunk_count: int
    audio_chunk_count: int
    source_sha256: str
    extraction_version: str | None
    processing_warnings: tuple[str, ...]
    visual_summary: Mapping[str, int]
    audio_embedding: Mapping[str, Any]


def embed_prepared_file_best_effort_audio(
    *,
    prepared: PreparedFile,
    embedding_service: EmbeddingService,
    admin_id: str,
    embedding_model_id: str,
    preparation_recipe: PreparationRecipe | None = None,
    index_generation_id: str | None = None,
) -> tuple[PreparedFile, tuple[tuple[float, ...], ...]]:
    """Embed required evidence and durably describe optional audio for later work."""

    required = tuple(chunk for chunk in prepared.chunks if chunk.modality != "audio")
    batch = (
        embedding_service.embed_for_frozen_context(
            inputs=tuple(chunk.embedding_input for chunk in required),
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        if required
        else None
    )
    now = int(time.time())
    pending = list(prepared.audio_repair_state.get("failed_chunks") or [])
    for chunk in prepared.chunks:
        if chunk.modality != "audio":
            continue
        metadata = chunk.chunk_metadata
        pending.append(
            {
                "chunk_index": metadata.get("chunkIndex"),
                "start_seconds": metadata.get("segment_start_s"),
                "end_seconds": metadata.get("segment_end_s"),
                "audio_sha256": chunk.content_sha256,
                "split_depth": 0,
                "split_path": "",
                "failure_reason": "pending",
            }
        )
    state = {}
    if pending:
        state = {
            **dict(prepared.audio_repair_state),
            "schema_version": 2,
            "admin_id": admin_id,
            "index_generation_id": index_generation_id,
            "source_sha256": prepared.source_sha256,
            "embedding_model_id": embedding_model_id,
            "extraction_version": prepared.extraction_version,
            "failed_chunks": pending,
            "total_chunks": len(pending),
            "embedded_chunks": 0,
            "phase": "queued",
            "created_at": now,
            "updated_at": now,
            "reliability_policy": embedding_service.reliability_policy.to_dict(),
            **(
                {"preparation_recipe": preparation_recipe.to_dict()}
                if preparation_recipe is not None
                else {}
            ),
        }
    return replace(
        prepared,
        chunks=required,
        visual_summary={**dict(prepared.visual_summary), "audio_chunk_count": 0},
        audio_embedding={
            "status": "queued" if pending else "not_applicable",
            "total_chunks": len(pending),
            "embedded_chunks": 0,
            "failed_chunks": 0,
            "pending_chunks": len(pending),
            "repairable": False,
            "updated_at": now,
        },
        audio_repair_state=state,
    ), (tuple(batch.vectors) if batch is not None else ())


def _split_audio_prepared_chunk(
    chunk: PreparedChunk,
    *,
    split_depth: int,
    split_path: str,
) -> tuple[PreparedChunk, PreparedChunk]:
    if not isinstance(chunk.embedding_input, AudioEmbeddingInput):
        raise TypeError("audio chunk is required")
    left_audio, right_audio = split_pcm_wav(chunk.embedding_input.audio)
    metadata = dict(chunk.chunk_metadata)
    start = float(metadata["segment_start_s"])
    end = float(metadata["segment_end_s"])
    midpoint = start + (end - start) / 2
    root_sha256 = str(metadata.get("audio_root_sha256") or chunk.content_sha256)
    children = []
    for child_index, (audio, child_start, child_end) in enumerate(
        (
            (left_audio, start, midpoint),
            (right_audio, midpoint, end),
        )
    ):
        audio_sha256 = hashlib.sha256(audio).hexdigest()
        child_path = f"{split_path}{child_index}"
        child_metadata = {
            **metadata,
            "startTimeSeconds": child_start,
            "endTimeSeconds": child_end,
            "segment_start_s": child_start,
            "segment_end_s": child_end,
            "audio_root_sha256": root_sha256,
            "audio_parent_sha256": chunk.content_sha256,
            "audio_split_depth": split_depth + 1,
            "audio_split_path": child_path,
            "audio_sha256": audio_sha256,
        }
        children.append(
            PreparedChunk(
                content="",
                content_type="audio",
                embedding_input=AudioEmbeddingInput(
                    audio=audio,
                    mime_type=chunk.embedding_input.mime_type,
                ),
                content_sha256=audio_sha256,
                modality="audio",
                chunk_metadata=child_metadata,
            )
        )
    return children[0], children[1]


CONTENT_ORIGIN_STORED_SOURCE = "stored_source"
CONTENT_ORIGIN_OVERRIDE = "content_override"


@dataclass(frozen=True)
class StoredContentProvenance:
    """Authoritative non-PDF text source persisted with a file."""

    origin: str
    content_override_sha256: str | None
    content_override: str | None


def persist_content_provenance_before_dispatch(
    file_id: str,
    content_override: str | None,
) -> StoredContentProvenance:
    """Persist the exact processing input before a background task is sent.

    The override itself lives in private file data while its origin and digest
    live in private metadata. PDFs always use their original stored bytes.
    """

    if content_override is not None and not isinstance(content_override, str):
        raise TypeError("content_override must be a string or None")

    with get_db() as db:
        row = db.query(File).filter(File.id == file_id).with_for_update().first()
        if row is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        _, source_bytes = _read_source(row.path)
        is_pdf = _is_pdf_source(
            source_bytes=source_bytes,
            filename=row.filename,
            content_type=(row.meta or {}).get("content_type"),
        )
        data = dict(row.data) if isinstance(row.data, dict) else {}
        meta = dict(row.meta) if isinstance(row.meta, dict) else {}
        if not is_pdf and content_override is not None:
            digest = hashlib.sha256(content_override.encode("utf-8")).hexdigest()
            data["content_override"] = content_override
            provenance = StoredContentProvenance(
                origin=CONTENT_ORIGIN_OVERRIDE,
                content_override_sha256=digest,
                content_override=content_override,
            )
        elif (
            not is_pdf
            and content_override is None
            and meta.get("content_origin") == CONTENT_ORIGIN_OVERRIDE
        ):
            # A generic retry carries no request body. Preserve an already
            # validated transcript/manual override rather than silently
            # switching the file back to its original binary source.
            provenance = read_stored_content_provenance(row)
        else:
            data.pop("content_override", None)
            provenance = StoredContentProvenance(
                origin=CONTENT_ORIGIN_STORED_SOURCE,
                content_override_sha256=None,
                content_override=None,
            )
        meta.update(
            {
                "content_origin": provenance.origin,
                "content_override_sha256": provenance.content_override_sha256,
                "processing_status": "pending",
            }
        )
        row.data = data
        row.meta = meta
        row.updated_at = int(time.time())
        db.commit()
        return provenance


def read_stored_content_provenance(file) -> StoredContentProvenance:
    """Validate and return a file's persisted override provenance."""

    meta = file.meta if isinstance(file.meta, dict) else {}
    origin = meta.get("content_origin")
    if origin is None:
        # Files written before this contract always re-read original storage;
        # cached ``data.content`` is processed output, never an implicit input.
        return StoredContentProvenance(
            origin=CONTENT_ORIGIN_STORED_SOURCE,
            content_override_sha256=None,
            content_override=None,
        )
    if origin == CONTENT_ORIGIN_STORED_SOURCE:
        if meta.get("content_override_sha256") is not None:
            raise ValueError("stored-source provenance cannot carry an override hash")
        return StoredContentProvenance(
            origin=CONTENT_ORIGIN_STORED_SOURCE,
            content_override_sha256=None,
            content_override=None,
        )
    if origin != CONTENT_ORIGIN_OVERRIDE:
        raise ValueError("unknown content origin")

    data = file.data if isinstance(file.data, dict) else {}
    content_override = data.get("content_override")
    digest = meta.get("content_override_sha256")
    if not isinstance(content_override, str) or not _is_sha256(digest):
        raise ValueError("invalid content override provenance")
    if hashlib.sha256(content_override.encode("utf-8")).hexdigest() != digest:
        raise ValueError("content override digest mismatch")
    return StoredContentProvenance(
        origin=CONTENT_ORIGIN_OVERRIDE,
        content_override_sha256=digest,
        content_override=content_override,
    )


def resolve_authoritative_content_provenance(
    file,
    source_bytes: bytes,
) -> StoredContentProvenance:
    """Resolve persisted text authority, forcing every PDF to stored bytes."""

    if _is_pdf_source(
        source_bytes=source_bytes,
        filename=file.filename,
        content_type=(file.meta or {}).get("content_type"),
    ):
        return StoredContentProvenance(
            origin=CONTENT_ORIGIN_STORED_SOURCE,
            content_override_sha256=None,
            content_override=None,
        )
    return read_stored_content_provenance(file)


def load_authoritative_content_override(file_id: str) -> str | None:
    """Load the persisted override for legacy synchronous/RQ processors."""

    file = Files.get_file_by_id(file_id)
    if file is None:
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
    _, source_bytes = _read_source(file.path)
    return resolve_authoritative_content_provenance(
        file,
        source_bytes,
    ).content_override


def process_stored_file_for_embedding(
    *,
    config,
    file_id: str,
    admin_id: str,
    embedding_model_id: str,
    knowledge_id: str | None = None,
    collection_name: str | None = None,
    reliability_policy: Mapping[str, Any] | None = None,
    indexing_snapshot: dict | None = None,
) -> FileProcessingResult:
    """Prepare required evidence and publish it in one fenced transaction."""
    from open_webui.retrieval.embedding.publication import (
        freeze_file_indexing,
        claim_required_indexing,
        publish_prepared_file,
        release_required_indexing,
    )
    from open_webui.retrieval.embedding.preparation import (
        preparation_recipe_from_snapshot,
    )

    call_id = str(uuid.uuid4())
    owner_token = None
    snapshot = indexing_snapshot or freeze_file_indexing(
        config=config,
        file_id=file_id,
        admin_id=admin_id,
        embedding_model_id=embedding_model_id,
    )
    try:
        owner_token = claim_required_indexing(
            admin_id=admin_id,
            model_id=embedding_model_id,
            snapshot=snapshot,
        )
        file = Files.get_file_by_id(file_id)
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        context = resolve_frozen(admin_id, embedding_model_id)
        admin = Users.get_user_by_id(context.admin_id)
        if admin is None or not admin.email:
            raise EmbeddingError(FILE_PROCESSING_FAILED)
        path, source_bytes = _read_source(file.path)
        provenance = resolve_authoritative_content_provenance(file, source_bytes)
        recipe = preparation_recipe_from_snapshot(snapshot)
        policy = (
            EmbeddingReliabilityPolicy.from_dict(reliability_policy)
            if reliability_policy is not None
            else snapshot_reliability_policy(config)
        )
        prepared = prepare_file_for_embedding(
            source_bytes=source_bytes,
            source_path=path,
            filename=file.filename,
            content_type=str((file.meta or {}).get("content_type") or "") or None,
            file_id=file.id,
            created_by=file.user_id,
            model=context.model,
            config=config,
            admin_email=admin.email,
            preparation_recipe=recipe,
            content_override=provenance.content_override,
            defer_audio=True,
        )
        prepared, vectors = embed_prepared_file_best_effort_audio(
            prepared=prepared,
            embedding_service=EmbeddingService(
                config,
                reliability_policy=policy,
                call_context={
                    "call_id": call_id,
                    "operation": "initial",
                    "file_id": file_id,
                },
            ),
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            preparation_recipe=recipe,
            index_generation_id=snapshot["index_generation_id"],
        )
        collections = publish_prepared_file(
            admin_id=admin_id,
            model=context.model,
            snapshot=snapshot,
            prepared=prepared,
            vectors=vectors,
            owner_token=owner_token,
            requested_knowledge_id=_effective_knowledge_id(
                file_id=file_id,
                knowledge_id=knowledge_id,
                collection_name=collection_name,
            ),
        )
        release_required_indexing(file_id, owner_token)
        owner_token = None
        # Publication is already committed. A dispatch failure is recoverable
        # through the durable queued descriptors and never fails required work.
        try:
            from open_webui.retrieval.embedding.audio_repair import (
                dispatch_pending_audio,
            )

            dispatch_pending_audio(
                config=config,
                file_id=file_id,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                reliability_policy=policy.to_dict(),
                knowledge_id=knowledge_id,
            )
        except Exception as error:
            log.warning(
                "initial_audio_dispatch_pending file_id=%s type=%s",
                file_id,
                type(error).__name__,
            )
        return FileProcessingResult(
            file_id=file_id,
            collection_names=collections,
            chunk_count=len(prepared.chunks),
            text_chunk_count=sum(chunk.modality == "text" for chunk in prepared.chunks),
            image_chunk_count=sum(
                chunk.modality == "image" for chunk in prepared.chunks
            ),
            video_chunk_count=sum(
                chunk.modality == "video" for chunk in prepared.chunks
            ),
            audio_chunk_count=sum(
                chunk.modality == "audio" for chunk in prepared.chunks
            ),
            source_sha256=prepared.source_sha256,
            extraction_version=prepared.extraction_version,
            processing_warnings=tuple(dict.fromkeys(prepared.warnings)),
            visual_summary=dict(prepared.visual_summary),
            audio_embedding=dict(prepared.audio_embedding),
        )
    except Exception as error:
        # An obsolete worker must never overwrite a newer publication's state.
        if owner_token is not None:
            with get_db() as db:
                row = db.query(File).filter_by(id=file_id).with_for_update().first()
                if row is not None:
                    meta = dict(row.meta or {})
                    if (meta.get("required_indexing") or {}).get(
                        "token"
                    ) == owner_token:
                        code = _safe_error_code(error)
                        meta.pop("required_indexing", None)
                        if meta.get("processing_status") != "completed":
                            meta.update(
                                processing_status="error",
                                processing_error_code=code,
                                processing_error=safe_file_processing_error_message(
                                    code
                                ),
                            )
                        row.meta = meta
                        db.commit()
        raise
    finally:
        if owner_token is not None:
            release_required_indexing(file_id, owner_token)


def _read_source(source_path: str | None) -> tuple[str, bytes]:
    if not source_path:
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
    try:
        resolved_path = Storage.get_file(source_path)
    except Exception:
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND) from None
    if not resolved_path or not os.path.isfile(resolved_path):
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
    try:
        with open(resolved_path, "rb") as source_file:
            source_bytes = source_file.read()
    except OSError:
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND) from None
    return resolved_path, source_bytes


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_pdf_source(
    *,
    source_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> bool:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    return (
        source_bytes[:1024].lstrip().startswith(b"%PDF-")
        or normalized_type == "application/pdf"
        or filename.lower().endswith(".pdf")
    )


def _make_vector_items(
    *,
    vector_repo: ModelAwareVectorRepository,
    chunks,
    vectors,
    metadata: Sequence[dict],
    rag_chunk_ids: Sequence[str],
    admin_id: str,
    model,
    file_id: str,
    knowledge_id: str | None,
) -> list[dict]:
    return vector_repo.make_items(
        texts=[chunk.content for chunk in chunks],
        vectors=vectors,
        metadata=metadata,
        rag_chunk_ids=rag_chunk_ids,
        admin_id=admin_id,
        model=model,
        file_id=file_id,
        knowledge_id=knowledge_id,
        modalities=[chunk.modality for chunk in chunks],
    )


def _effective_knowledge_id(
    *,
    file_id: str,
    knowledge_id: str | None,
    collection_name: str | None,
) -> str | None:
    if knowledge_id:
        return knowledge_id
    if collection_name and collection_name != f"file-{file_id}":
        return collection_name
    return None


def _resolve_knowledge_projection_ids(
    *,
    file_id: str,
    admin_id: str,
    requested_knowledge_id: str | None,
    db=None,
) -> tuple[str, ...]:
    """Return every current knowledge projection governed by ``admin_id``.

    Reprocessing a file must replace all of its active projections together.
    An explicitly requested knowledge base must already contain the file; upload
    routes persist that membership before dispatching work.
    """
    knowledge_ids: set[str] = set()

    def _load(session):
        query = session.query(Knowledge)
        if db is None:
            knowledge_rows = query.all()
        else:
            # The caller already holds the File row. Discover candidates from a
            # non-locking snapshot, then lock only those rows (plus an explicit
            # requested row) in stable order and recheck membership below.
            candidate_ids = {
                str(row.id)
                for row in query.all()
                if file_id in (
                    row.data.get("file_ids", [])
                    if isinstance(row.data, dict)
                    and isinstance(row.data.get("file_ids", []), list)
                    else []
                )
            }
            if requested_knowledge_id:
                candidate_ids.add(str(requested_knowledge_id))
            knowledge_rows = (
                query.filter(Knowledge.id.in_(sorted(candidate_ids)))
                .order_by(Knowledge.id)
                .with_for_update()
                .all()
                if candidate_ids
                else []
            )
        for row in knowledge_rows:
            data = row.data if isinstance(row.data, dict) else {}
            file_ids = data.get("file_ids", [])
            if isinstance(file_ids, list) and file_id in file_ids:
                knowledge_ids.add(str(row.id))

        if not knowledge_ids:
            return
        from open_webui.retrieval.embedding.inventory import (
            build_reindex_admin_resolver,
        )

        resolver = build_reindex_admin_resolver(session)
        for row in knowledge_rows:
            if (
                str(row.id) in knowledge_ids
                and resolver.resolve_knowledge(row) != admin_id
            ):
                raise EmbeddingError(FILE_PROCESSING_FAILED)

    if db is None:
        with get_db() as session:
            _load(session)
    else:
        _load(db)

    if requested_knowledge_id and requested_knowledge_id not in knowledge_ids:
        raise EmbeddingError(FILE_PROCESSING_FAILED)

    return tuple(sorted(knowledge_ids))


def _mark_processing(file_id: str) -> None:
    Files.update_file_metadata_by_id(
        file_id,
        {
            "processing_status": "processing",
            "processing_started_at": int(time.time()),
            "processing_completed_at": None,
            "processing_error": None,
            "processing_error_code": None,
        },
    )


def _apply_completed_file_state(
    *,
    row: File,
    extracted_text: str,
    source_sha256: str,
    extraction_version: str | None,
    manifest_id: str,
    processing_warnings: Sequence[str],
    visual_summary: Mapping[str, int],
    audio_embedding: Mapping[str, Any],
    audio_repair_state: Mapping[str, Any],
    collection_name: str,
) -> None:
    now = int(time.time())
    row.data = {**(row.data or {}), "content": extracted_text}
    row.hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
    metadata = dict(row.meta or {})
    metadata.pop("cache_video_audio_v1", None)
    metadata.pop("audio_fragment_manifest_ids", None)
    metadata.pop("publication_recovery_error", None)
    metadata.pop("publication_recovery_generation_id", None)
    if audio_repair_state:
        metadata[AUDIO_REPAIR_STATE_META_KEY] = dict(audio_repair_state)
    else:
        metadata.pop(AUDIO_REPAIR_STATE_META_KEY, None)
    row.meta = {
        **metadata,
        "collection_name": collection_name,
        "source_sha256": source_sha256,
        "extraction_version": extraction_version,
        "chunk_manifest_id": manifest_id,
        "processing_warnings": list(processing_warnings),
        "visual_summary": dict(visual_summary),
        "audio_embedding": dict(audio_embedding),
        "processing_status": "completed",
        "processing_completed_at": now,
        "processing_error": None,
        "processing_error_code": None,
    }
    row.updated_at = now


def _mark_failed(file_id: str, code: str) -> None:
    Files.update_file_metadata_by_id(
        file_id,
        {
            "processing_status": "error",
            "processing_completed_at": int(time.time()),
            "processing_error_code": code,
            "processing_error": safe_file_processing_error_message(code),
        },
    )


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, EmbeddingError):
        return error.code
    return FILE_PROCESSING_FAILED


__all__ = [
    "CONTENT_ORIGIN_OVERRIDE",
    "CONTENT_ORIGIN_STORED_SOURCE",
    "AUDIO_REPAIR_STATE_META_KEY",
    "FILE_PROCESSING_FAILED",
    "FileProcessingResult",
    "StoredContentProvenance",
    "embed_prepared_file_best_effort_audio",
    "load_authoritative_content_override",
    "persist_content_provenance_before_dispatch",
    "process_stored_file_for_embedding",
    "read_stored_content_provenance",
    "resolve_authoritative_content_provenance",
]
