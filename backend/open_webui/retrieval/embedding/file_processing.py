"""Shared, model-aware ingestion for stored files.

This module owns the normal file-ingestion transaction boundary used by both
FastAPI background tasks and RQ workers. It resolves the frozen execution
context, prepares every text/image chunk, embeds the complete ordered manifest,
persists the shared chunk rows, and atomically reconciles all requested vector
projections. No caller is allowed to rebuild parallel text, modality, hash, or
metadata lists independently.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Mapping, Sequence

from open_webui.internal.db import get_db
from open_webui.models.embeddings import RagChunk
from open_webui.models.files import File, Files
from open_webui.models.knowledge import Knowledge
from open_webui.models.users import User, Users
from open_webui.retrieval.embedding.errors import (
    EMBEDDING_FILE_NOT_FOUND,
    FILE_PROCESSING_FAILED,
    EmbeddingError,
    safe_file_processing_error_message,
)
from open_webui.retrieval.embedding.preparation import (
    build_persisted_chunks,
    prepare_file_for_embedding,
)
from open_webui.retrieval.embedding.resolution import (
    resolve_admin_for_knowledge,
    resolve_frozen,
)
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository
from open_webui.storage.provider import Storage


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileProcessingResult:
    """Safe completion data shared by background and RQ callers."""

    file_id: str
    collection_names: tuple[str, ...]
    chunk_count: int
    text_chunk_count: int
    image_chunk_count: int
    source_sha256: str
    extraction_version: str | None
    processing_warnings: tuple[str, ...]
    visual_summary: Mapping[str, int]


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
) -> FileProcessingResult:
    """Prepare and index one stored file using a frozen admin/model context.

    Provider calls and validation finish before ``rag_chunks`` or vectors are
    changed. File and optional knowledge projections are reconciled together;
    an error cannot activate only a prefix of a multimodal PDF manifest.
    """

    _mark_processing(file_id)
    try:
        file = Files.get_file_by_id(file_id)
        if file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)

        context = resolve_frozen(admin_id, embedding_model_id)
        admin = Users.get_user_by_id(context.admin_id)
        if admin is None or not admin.email:
            raise EmbeddingError(FILE_PROCESSING_FAILED)
        resolved_path, source_bytes = _read_source(file.path)
        content_provenance = resolve_authoritative_content_provenance(
            file,
            source_bytes,
        )
        content_type = str((file.meta or {}).get("content_type") or "") or None
        requested_knowledge_id = _effective_knowledge_id(
            file_id=file.id,
            knowledge_id=knowledge_id,
            collection_name=collection_name,
        )
        knowledge_ids = _resolve_knowledge_projection_ids(
            file_id=file.id,
            admin_id=admin_id,
            requested_knowledge_id=requested_knowledge_id,
        )

        prepared = prepare_file_for_embedding(
            source_bytes=source_bytes,
            source_path=resolved_path,
            filename=file.filename,
            content_type=content_type,
            file_id=file.id,
            created_by=file.user_id,
            model=context.model,
            config=config,
            admin_email=admin.email,
            content_override=content_provenance.content_override,
        )
        if not prepared.chunks:
            raise EmbeddingError(FILE_PROCESSING_FAILED)

        # One ordered service operation must succeed and validate every vector
        # before the durable chunk manifest or active projections are touched.
        batch = EmbeddingService(config).embed_for_frozen_context(
            inputs=tuple(chunk.embedding_input for chunk in prepared.chunks),
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        if len(batch.vectors) != len(prepared.chunks):
            raise EmbeddingError(FILE_PROCESSING_FAILED)

        # Membership may change while provider calls are in flight. Re-read it
        # before writing any chunks or vectors so removed knowledge bases never
        # receive a stale/orphaned projection.
        knowledge_ids = _resolve_knowledge_projection_ids(
            file_id=file.id,
            admin_id=admin_id,
            requested_knowledge_id=requested_knowledge_id,
        )

        persisted_chunks = build_persisted_chunks(
            prepared,
            admin_id=admin_id,
            file_id=file.id,
        )
        chunk_metadata = [chunk["chunk_metadata"] for chunk in persisted_chunks]
        manifest_id = RagChunk.build_manifest_id(
            persisted_chunks,
            source_sha256=prepared.source_sha256,
            extraction_version=prepared.extraction_version,
        )
        file_collection = f"file-{file.id}"
        vector_repo = ModelAwareVectorRepository()
        warnings = tuple(
            dict.fromkeys(str(value) for value in prepared.warnings if value)
        )
        visual_summary = {
            str(key): int(value)
            for key, value in dict(prepared.visual_summary).items()
        }
        with get_db() as db:
            locked_file = (
                db.query(File).filter(File.id == file.id).with_for_update().first()
            )
            if locked_file is None:
                raise EmbeddingError(FILE_PROCESSING_FAILED)
            current_path, current_bytes = _read_source(locked_file.path)
            if (
                current_path != resolved_path
                or hashlib.sha256(current_bytes).hexdigest()
                != prepared.source_sha256
                or resolve_authoritative_content_provenance(
                    locked_file,
                    current_bytes,
                )
                != content_provenance
            ):
                raise EmbeddingError(FILE_PROCESSING_FAILED)
            knowledge_ids = _resolve_knowledge_projection_ids(
                file_id=file.id,
                admin_id=admin_id,
                requested_knowledge_id=requested_knowledge_id,
                db=db,
            )
            rag_chunk_ids = RagChunk.insert_chunks(
                admin_id,
                file.id,
                persisted_chunks,
                manifest_id=manifest_id,
                db=db,
            )
            if len(rag_chunk_ids) != len(prepared.chunks):
                raise EmbeddingError(FILE_PROCESSING_FAILED)
            file_items = _make_vector_items(
                vector_repo=vector_repo,
                chunks=prepared.chunks,
                vectors=batch.vectors,
                metadata=chunk_metadata,
                rag_chunk_ids=rag_chunk_ids,
                admin_id=admin_id,
                model=context.model,
                file_id=file.id,
                knowledge_id=None,
            )
            projections: list[tuple[str, Sequence[dict]]] = [
                (file_collection, file_items)
            ]
            for effective_knowledge_id in knowledge_ids:
                knowledge_metadata = [
                    {**metadata, "knowledge_id": effective_knowledge_id}
                    for metadata in chunk_metadata
                ]
                knowledge_items = _make_vector_items(
                    vector_repo=vector_repo,
                    chunks=prepared.chunks,
                    vectors=batch.vectors,
                    metadata=knowledge_metadata,
                    rag_chunk_ids=rag_chunk_ids,
                    admin_id=admin_id,
                    model=context.model,
                    file_id=file.id,
                    knowledge_id=effective_knowledge_id,
                )
                projections.append((effective_knowledge_id, knowledge_items))
            vector_repo.reconcile_model_aware_many(
                projections=projections,
                model=context.model,
                session=db,
            )
            _apply_completed_file_state(
                row=locked_file,
                extracted_text=prepared.text_content,
                source_sha256=prepared.source_sha256,
                extraction_version=prepared.extraction_version,
                manifest_id=manifest_id,
                processing_warnings=warnings,
                visual_summary=visual_summary,
                collection_name=file_collection,
            )
            db.commit()
        return FileProcessingResult(
            file_id=file.id,
            collection_names=tuple(name for name, _ in projections),
            chunk_count=len(prepared.chunks),
            text_chunk_count=sum(
                chunk.modality == "text" for chunk in prepared.chunks
            ),
            image_chunk_count=sum(
                chunk.modality == "image" for chunk in prepared.chunks
            ),
            source_sha256=prepared.source_sha256,
            extraction_version=prepared.extraction_version,
            processing_warnings=warnings,
            visual_summary=visual_summary,
        )
    except Exception as error:
        code = _safe_error_code(error)
        _mark_failed(file_id, code)
        log.error(
            "Stored file processing failed | file_id=%s | code=%s | type=%s",
            file_id,
            code,
            type(error).__name__,
        )
        raise


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
        owner_ids = {
            row.user_id for row in knowledge_rows if str(row.id) in knowledge_ids
        }
        owners = {
            row.id: row
            for row in session.query(User).filter(User.id.in_(owner_ids)).all()
        }
        for row in knowledge_rows:
            if str(row.id) not in knowledge_ids:
                continue
            owner = owners.get(row.user_id)
            if owner is None:
                raise EmbeddingError(FILE_PROCESSING_FAILED)
            if owner.role == "admin":
                governing_admin_id = owner.id
            else:
                # Non-admin ownership inherits through the existing stable-ID
                # resolver. The locked Knowledge row still protects membership.
                governing_admin_id = resolve_admin_for_knowledge(
                    str(row.id),
                    requesting_user_id=admin_id,
                ).id
            if governing_admin_id != admin_id:
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
    collection_name: str,
) -> None:
    now = int(time.time())
    row.data = {**(row.data or {}), "content": extracted_text}
    row.hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
    row.meta = {
        **(row.meta or {}),
        "collection_name": collection_name,
        "source_sha256": source_sha256,
        "extraction_version": extraction_version,
        "chunk_manifest_id": manifest_id,
        "processing_warnings": list(processing_warnings),
        "visual_summary": dict(visual_summary),
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
    "FILE_PROCESSING_FAILED",
    "FileProcessingResult",
    "StoredContentProvenance",
    "load_authoritative_content_override",
    "persist_content_provenance_before_dispatch",
    "process_stored_file_for_embedding",
    "read_stored_content_provenance",
    "resolve_authoritative_content_provenance",
]
