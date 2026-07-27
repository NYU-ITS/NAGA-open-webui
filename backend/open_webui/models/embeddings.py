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
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger)
    completed_at = Column(BigInteger)
