"""Persistence models for the Phase 1 embedding registry and indexing ledger."""

import hashlib
import json
import time
import uuid

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from open_webui.internal.db import Base, JSONField


RAG_CHUNK_LEGACY_MANIFEST_ID = "0" * 64


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"

    id = Column(String, primary_key=True)
    provider = Column(String(64), nullable=False)
    model_name = Column(String, nullable=False, unique=True)
    display_name = Column(String, nullable=False)
    dimension = Column(Integer, nullable=False)
    modalities = Column(JSONField, nullable=False)
    status = Column(String(16), nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    @staticmethod
    def get_model_by_name(model_name: str):
        """Get an embedding model by its model_name."""
        from open_webui.internal.db import get_db
        with get_db() as db:
            return db.query(EmbeddingModel).filter(EmbeddingModel.model_name == model_name).first()

    @staticmethod
    def get_model_by_id(model_id: str):
        """Get an embedding model by its id."""
        from open_webui.internal.db import get_db
        with get_db() as db:
            return db.query(EmbeddingModel).filter(EmbeddingModel.id == model_id).first()

    @staticmethod
    def get_enabled_models():
        """Get all enabled embedding models."""
        from open_webui.internal.db import get_db
        with get_db() as db:
            return db.query(EmbeddingModel).filter(EmbeddingModel.status == "enabled").all()


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint(
            "admin_id",
            "file_id",
            "manifest_id",
            "chunk_index",
            name="uq_rag_chunks_admin_file_manifest_chunk",
        ),
    )

    id = Column(String, primary_key=True)
    admin_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String, ForeignKey("file.id", ondelete="CASCADE"), nullable=False)
    manifest_id = Column(
        String(64),
        nullable=False,
        default=RAG_CHUNK_LEGACY_MANIFEST_ID,
        server_default=RAG_CHUNK_LEGACY_MANIFEST_ID,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text)
    content_type = Column(String(16), nullable=False)
    chunk_metadata = Column(JSONField)
    content_sha256 = Column(String(64), nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    @staticmethod
    def build_manifest_id(
        chunks: list[dict],
        *,
        source_sha256: str | None = None,
        extraction_version: str | None = None,
    ) -> str:
        """Return the canonical ID for an exact, ordered chunk manifest.

        The source hash and extraction version are explicit inputs because the
        same text can be produced from different source bytes or extraction
        recipes. Chunk order, modality, content hash, and the complete JSON
        metadata payload are all covered by the digest.
        """
        records = RagChunk._normalize_chunks(chunks)
        if source_sha256 is not None:
            RagChunk._validate_sha256(source_sha256, "source_sha256")
        if extraction_version is not None and not isinstance(extraction_version, str):
            raise ValueError("extraction_version must be a string or None")
        payload = {
            "schema": "rag_chunk_manifest_v1",
            "source_sha256": source_sha256,
            "extraction_version": extraction_version,
            "chunks": [
                {
                    "chunk_index": index,
                    "content_type": record["content_type"],
                    "content_sha256": record["content_sha256"],
                    "chunk_metadata": record["chunk_metadata"],
                }
                for index, record in enumerate(records)
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def insert_chunks(
        admin_id: str,
        file_id: str,
        chunks: list[dict],
        *,
        manifest_id: str | None = None,
        db=None,
    ) -> list[str]:
        """Create or reuse one immutable, exact ordered chunk manifest.

        ``chunks`` is a list of dicts with ``content`` (str), ``content_type``
        (``"text"``/``"image"``), optional ``chunk_metadata`` (dict), and an
        optional caller-provided ``content_sha256``. Image chunks must provide
        the SHA-256 of their source/rendered bytes because their persisted text
        content is intentionally empty. The list order defines ``chunk_index``.

        ``manifest_id`` should be built with :meth:`build_manifest_id`. For
        compatibility, callers that omit it receive a deterministic ID derived
        from the ordered chunks alone. Existing rows are reused only when every
        persisted field matches. A reused ID with different content fails
        closed; prior manifests are never updated or deleted here.

        Returns rag_chunk IDs in chunk order. A concurrent creator of the same
        exact manifest is handled by re-reading after the uniqueness conflict.
        """
        from open_webui.internal.db import get_db

        records = RagChunk._normalize_chunks(chunks)
        resolved_manifest_id = manifest_id or RagChunk.build_manifest_id(chunks)
        RagChunk._validate_sha256(resolved_manifest_id, "manifest_id")
        now = int(time.time())

        def _insert(session, *, recover_concurrent_insert: bool) -> list[str]:
            existing = RagChunk._get_manifest_rows(
                session, admin_id, file_id, resolved_manifest_id
            )
            if existing:
                return RagChunk._exact_manifest_ids(existing, records)

            ids = [str(uuid.uuid4()) for _ in records]
            rows = [
                {
                    "id": chunk_id,
                    "admin_id": admin_id,
                    "file_id": file_id,
                    "manifest_id": resolved_manifest_id,
                    "chunk_index": index,
                    "content": record["content"],
                    "content_type": record["content_type"],
                    "chunk_metadata": record["chunk_metadata"],
                    "content_sha256": record["content_sha256"],
                    "created_at": now,
                    "updated_at": now,
                }
                for index, (chunk_id, record) in enumerate(zip(ids, records))
            ]
            try:
                bind = session.get_bind()
                if bind.dialect.name == "postgresql":
                    statement = (
                        pg_insert(RagChunk)
                        .values(rows)
                        .on_conflict_do_nothing(
                            constraint="uq_rag_chunks_admin_file_manifest_chunk"
                        )
                    )
                    session.execute(statement)
                    session.flush()
                    existing = RagChunk._get_manifest_rows(
                        session, admin_id, file_id, resolved_manifest_id
                    )
                    return RagChunk._exact_manifest_ids(existing, records)

                for row in rows:
                    session.add(RagChunk(**row))
                session.flush()
                return ids
            except IntegrityError:
                if not recover_concurrent_insert:
                    # The caller owns a wider transaction. Let it roll the
                    # transaction back rather than discarding unrelated work
                    # while attempting to recover this single insert.
                    raise
                session.rollback()
                existing = RagChunk._get_manifest_rows(
                    session, admin_id, file_id, resolved_manifest_id
                )
                if existing:
                    return RagChunk._exact_manifest_ids(existing, records)
                raise ValueError("chunk manifest could not be created") from None

        if db is not None:
            return _insert(db, recover_concurrent_insert=False)
        with get_db() as session:
            ids = _insert(session, recover_concurrent_insert=True)
            session.commit()
            return ids

    @staticmethod
    def get_ids_by_file(
        admin_id: str,
        file_id: str,
        manifest_id: str | None = None,
    ) -> list[str]:
        """Return IDs for one file manifest in chunk order.

        The optional form preserves legacy callers only while a file has zero
        or one manifest. Once multiple immutable generations exist, callers
        must select a ``manifest_id`` instead of receiving an arbitrary one.
        """
        from open_webui.internal.db import get_db

        with get_db() as db:
            if manifest_id is None:
                manifest_ids = [
                    value
                    for (value,) in (
                        db.query(RagChunk.manifest_id)
                        .filter(
                            RagChunk.admin_id == admin_id,
                            RagChunk.file_id == file_id,
                        )
                        .distinct()
                        .limit(2)
                        .all()
                    )
                ]
                if not manifest_ids:
                    return []
                if len(manifest_ids) != 1:
                    raise ValueError(
                        "manifest_id is required when a file has multiple manifests"
                    )
                manifest_id = manifest_ids[0]
            RagChunk._validate_sha256(manifest_id, "manifest_id")
            rows = RagChunk._get_manifest_rows(db, admin_id, file_id, manifest_id)
            return [row.id for row in rows]

    @staticmethod
    def _normalize_chunks(chunks: list[dict]) -> list[dict]:
        records: list[dict] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ValueError("each chunk must be a dictionary")
            raw_content = chunk.get("content", "")
            content = "" if raw_content is None else raw_content
            if not isinstance(content, str):
                raise ValueError("chunk content must be a string")
            content_type = chunk.get("content_type") or "text"
            if content_type not in {"text", "image"}:
                raise ValueError("content_type must be text or image")
            if content_type == "image" and content:
                raise ValueError("image chunk content must be empty")

            chunk_metadata = chunk.get("chunk_metadata") or {}
            if not isinstance(chunk_metadata, dict):
                raise ValueError("chunk_metadata must be a dictionary")
            try:
                canonical_metadata = json.loads(
                    json.dumps(
                        chunk_metadata,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError):
                raise ValueError("chunk_metadata must contain JSON values") from None

            text_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            provided_digest = chunk.get("content_sha256")
            if provided_digest is not None:
                RagChunk._validate_sha256(provided_digest, "content_sha256")
                if content_type == "text" and provided_digest != text_digest:
                    raise ValueError("text content_sha256 does not match content")
                digest = provided_digest
            elif content_type == "image":
                raise ValueError("image chunks require content_sha256")
            else:
                digest = text_digest
            records.append(
                {
                    "content": content,
                    "content_type": content_type,
                    "chunk_metadata": canonical_metadata,
                    "content_sha256": digest,
                }
            )
        return records

    @staticmethod
    def _validate_sha256(value: str, field_name: str) -> None:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")

    @staticmethod
    def _get_manifest_rows(db, admin_id: str, file_id: str, manifest_id: str):
        return (
            db.query(RagChunk)
            .filter(
                RagChunk.admin_id == admin_id,
                RagChunk.file_id == file_id,
                RagChunk.manifest_id == manifest_id,
            )
            .order_by(RagChunk.chunk_index)
            .all()
        )

    @staticmethod
    def _exact_manifest_ids(rows, records: list[dict]) -> list[str]:
        if len(rows) != len(records):
            raise ValueError("manifest_id already exists with different chunks")
        for index, (row, record) in enumerate(zip(rows, records)):
            if (
                row.chunk_index != index
                or (row.content or "") != record["content"]
                or row.content_type != record["content_type"]
                or (row.chunk_metadata or {}) != record["chunk_metadata"]
                or row.content_sha256 != record["content_sha256"]
            ):
                raise ValueError("manifest_id already exists with different chunks")
        return [row.id for row in rows]

    @staticmethod
    def delete_by_file(admin_id: str, file_id: str) -> int:
        """Delete all manifests for a file. Returns the number deleted."""
        from open_webui.internal.db import get_db

        with get_db() as db:
            deleted = (
                db.query(RagChunk)
                .filter(RagChunk.admin_id == admin_id, RagChunk.file_id == file_id)
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted


class EmbeddingJob(Base):
    __tablename__ = "embedding_jobs"

    id = Column(String, primary_key=True)
    admin_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    embedding_model_id = Column(String, ForeignKey("embedding_models.id", ondelete="RESTRICT"), nullable=False)
    previous_embedding_model_id = Column(String, ForeignKey("embedding_models.id", ondelete="RESTRICT"))
    job_type = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False)
    total_files = Column(Integer, nullable=False, default=0)
    processed_files = Column(Integer, nullable=False, default=0)
    failed_files = Column(Integer, nullable=False, default=0)
    rq_job_id = Column(String, unique=True)
    created_by_user_id = Column(String, ForeignKey("user.id", ondelete="SET NULL"))
    source_job_id = Column(String, ForeignKey("embedding_jobs.id", ondelete="SET NULL"))
    error_code = Column(String(64))
    error_message = Column(Text)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger)
    completed_at = Column(BigInteger)


class EmbeddingJobFile(Base):
    __tablename__ = "embedding_job_files"

    job_id = Column(String, ForeignKey("embedding_jobs.id", ondelete="CASCADE"), primary_key=True)
    # Historical source identifier, intentionally not a foreign key. The job
    # inventory must survive deletion of the mutable source ``file`` row.
    file_id = Column(String, primary_key=True)
    status = Column(String(20), nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(64))
    error_message = Column(Text)
    file_snapshot = Column(JSONField, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger)
    completed_at = Column(BigInteger)


class AdminEmbeddingModelState(Base):
    """Durable, admin-scoped authority over embedding model spaces.

    One row per admin. ``active_embedding_model_id`` is the only model whose
    completed vectors may be retrieved. ``target_embedding_model_id`` is the
    model currently being built by a reindex operation (nullable). Stored IDs
    reference ``embedding_models`` registry rows; model names remain
    presentation/config compatibility data only.
    """

    __tablename__ = "admin_embedding_model_state"

    admin_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    active_embedding_model_id = Column(
        String, ForeignKey("embedding_models.id", ondelete="RESTRICT"), nullable=False
    )
    target_embedding_model_id = Column(
        String, ForeignKey("embedding_models.id", ondelete="RESTRICT")
    )
    latest_embedding_job_id = Column(
        String, ForeignKey("embedding_jobs.id", ondelete="SET NULL")
    )
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    @staticmethod
    def get_by_admin(admin_id: str):
        """Return the state row for an admin, or None if absent."""
        from open_webui.internal.db import get_db

        with get_db() as db:
            return (
                db.query(AdminEmbeddingModelState)
                .filter(AdminEmbeddingModelState.admin_id == admin_id)
                .first()
            )
