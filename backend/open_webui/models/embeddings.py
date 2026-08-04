"""Persistence models for the Phase 1 embedding registry and indexing ledger."""

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from open_webui.internal.db import Base, JSONField


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
    __table_args__ = (UniqueConstraint("admin_id", "file_id", "chunk_index"),)

    id = Column(String, primary_key=True)
    admin_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String, ForeignKey("file.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text)
    content_type = Column(String(16), nullable=False)
    chunk_metadata = Column(JSONField)
    content_sha256 = Column(String(64), nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    @staticmethod
    def insert_chunks(admin_id: str, file_id: str, chunks: list[dict]) -> list[str]:
        """Persist extracted content for one admin/file as ordered rag_chunks.

        ``chunks`` is a list of dicts with ``content`` (str), ``content_type``
        (``"text"``/``"image"``), and optional ``chunk_metadata`` (dict). The
        list order defines ``chunk_index``.

        Logical chunk identity is ``(admin_id, file_id, chunk_index)``. This is
        an upsert by that identity (Spec 07):

        1. Existing chunks for ``(admin_id, file_id)`` are loaded by index.
        2. Each incoming index updates the existing row in place, preserving its
           id (and original ``created_at``).
        3. A new row is inserted only for an index that does not yet exist.
        4. No rows are deleted here. Chunk rows are shared across collection
           memberships and vector models (``rag_chunk_id`` is ``ON DELETE
           CASCADE``), so deleting them during a target build would cascade
           away other collections' and the old active model's vectors. Stale
           target vectors are instead removed per projection by the vector
           repository reconcile, and chunk-row cleanup is deferred until no
           active or building vectors reference them (promotion/retirement).

        The content hash detects changed content; it is not treated as the sole
        identity because repeated text may occur at multiple positions.

        Returns the rag_chunk_ids for ``chunks`` in the same order so the caller
        can stamp each generated vector with its rag_chunk_id. Re-processing the
        same file yields the same ids for chunk positions that persist.
        """
        import hashlib
        import time
        import uuid

        from open_webui.internal.db import get_db

        now = int(time.time())

        with get_db() as db:
            existing = {
                row.chunk_index: row
                for row in (
                    db.query(RagChunk)
                    .filter(RagChunk.admin_id == admin_id, RagChunk.file_id == file_id)
                    .all()
                )
            }

            ids: list[str] = []
            for index, chunk in enumerate(chunks):
                content = chunk.get("content") or ""
                content_type = chunk.get("content_type") or "text"
                chunk_metadata = chunk.get("chunk_metadata") or {}
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

                row = existing.get(index)
                if row is None:
                    # New index: insert a fresh row.
                    chunk_id = str(uuid.uuid4())
                    ids.append(chunk_id)
                    db.add(
                        RagChunk(
                            id=chunk_id,
                            admin_id=admin_id,
                            file_id=file_id,
                            chunk_index=index,
                            content=content,
                            content_type=content_type,
                            chunk_metadata=chunk_metadata,
                            content_sha256=digest,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    # Existing index: update in place, preserving the id.
                    row.content = content
                    row.content_type = content_type
                    row.chunk_metadata = chunk_metadata
                    row.content_sha256 = digest
                    row.updated_at = now
                    ids.append(row.id)
            db.commit()
        return ids

    @staticmethod
    def get_ids_by_file(admin_id: str, file_id: str) -> list[str]:
        """Return rag_chunk_ids for a file in chunk_index order."""
        from open_webui.internal.db import get_db

        with get_db() as db:
            rows = (
                db.query(RagChunk)
                .filter(RagChunk.admin_id == admin_id, RagChunk.file_id == file_id)
                .order_by(RagChunk.chunk_index)
                .all()
            )
            return [row.id for row in rows]

    @staticmethod
    def delete_by_file(admin_id: str, file_id: str) -> int:
        """Delete all rag_chunks for a file. Returns the number deleted."""
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
    file_id = Column(String, ForeignKey("file.id", ondelete="CASCADE"), primary_key=True)
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
