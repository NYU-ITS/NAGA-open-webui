"""Add Phase 1 multimodal embedding persistence.

Revision ID: d3e4f5a6b7c8
Revises: b2c3d4e5f6a7
"""

import os
import json
import time
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_MODEL_ID = "embmdl-portkey-openai-text-embedding-3-small-1536"
DEFAULT_MODEL_NAME = "@openai-embedding/text-embedding-3-small"
GLOBAL_EMAIL = "system@default"


def _require_postgres(bind):
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Multimodal embedding Phase 1 requires PostgreSQL with pgvector.")
    configured_vector_url = os.environ.get("PGVECTOR_DB_URL")
    database_url = os.environ.get("DATABASE_URL")
    if configured_vector_url and database_url and configured_vector_url != database_url:
        raise RuntimeError("PGVECTOR_DB_URL must be unset or equal to DATABASE_URL.")


def _reconcile_config(bind):
    default_row = bind.execute(sa.text("SELECT id, data FROM config WHERE email = :email AND version = 0"), {"email": GLOBAL_EMAIL}).mappings().first()
    if default_row is None:
        default_data = {"rag": {"embedding_model": DEFAULT_MODEL_NAME}}
        bind.execute(sa.text("INSERT INTO config (email, data, version, created_at) VALUES (:email, CAST(:data AS jsonb), 0, now())"), {"email": GLOBAL_EMAIL, "data": json.dumps(default_data)})
    else:
        default_data = default_row["data"] or {}
        rag = default_data.get("rag") if isinstance(default_data, dict) else None
        if not isinstance(rag, dict):
            rag = {}
            default_data["rag"] = rag
        if not rag.get("embedding_model"):
            rag["embedding_model"] = DEFAULT_MODEL_NAME
            bind.execute(sa.text("UPDATE config SET data = CAST(:data AS jsonb), updated_at = now() WHERE id = :id"), {"id": default_row["id"], "data": json.dumps(default_data)})

    enabled_models = set(bind.execute(sa.text("SELECT model_name FROM embedding_models WHERE status = 'enabled' ")).scalars())
    default_name = (default_data.get("rag") or {}).get("embedding_model") or DEFAULT_MODEL_NAME
    for row in bind.execute(sa.text("SELECT id, email FROM \"user\" WHERE role = 'admin'")).mappings():
        entry = bind.execute(sa.text("SELECT id, data FROM config WHERE email = :email AND version = 0"), {"email": row["email"]}).mappings().first()
        data = (entry["data"] if entry else {}) or {}
        rag = data.get("rag") if isinstance(data, dict) else None
        if not isinstance(rag, dict):
            rag = {}
            data["rag"] = rag
        if rag.get("embedding_model_user") not in enabled_models:
            rag["embedding_model_user"] = default_name
        if entry:
            bind.execute(sa.text("UPDATE config SET data = CAST(:data AS jsonb), updated_at = now() WHERE id = :id"), {"id": entry["id"], "data": json.dumps(data)})
        else:
            bind.execute(sa.text("INSERT INTO config (email, data, version, created_at) VALUES (:email, CAST(:data AS jsonb), 0, now())"), {"email": row["email"], "data": json.dumps(data)})


def _group_ids(access_control):
    if not isinstance(access_control, dict):
        return set()
    return {
        group_id
        for permission in ("read", "write")
        for group_id in (access_control.get(permission, {}) or {}).get("group_ids", [])
    }


def _files_in_chat(chat):
    messages = ((chat or {}).get("history") or {}).get("messages") or {}
    messages = messages.values() if isinstance(messages, dict) else messages
    for message in messages:
        for file in (message or {}).get("files", []) or []:
            if isinstance(file, dict) and file.get("id"):
                yield file["id"]


def _backfill_vector_provenance(bind, batch_size=500):
    """Backfill legacy vectors without choosing an arbitrary group owner."""
    users = dict(bind.execute(sa.text('SELECT id, role FROM "user"')).all())
    group_owners = {}
    member_group_owners = defaultdict(set)
    for row in bind.execute(sa.text('SELECT id, user_id, user_ids FROM "group"')).mappings():
        if users.get(row["user_id"]) != "admin":
            continue
        group_owners[row["id"]] = row["user_id"]
        for member_id in row["user_ids"] or []:
            member_group_owners[member_id].add(row["user_id"])

    def owner_for_user(user_id):
        if users.get(user_id) == "admin":
            return user_id
        candidates = member_group_owners.get(user_id, set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    knowledge_owners = defaultdict(set)
    ambiguous_files = set()
    for row in bind.execute(sa.text('SELECT user_id, data, access_control FROM knowledge')).mappings():
        file_ids = ((row["data"] or {}).get("file_ids") or [])
        group_ids = _group_ids(row["access_control"])
        group_admins = {group_owners[group_id] for group_id in group_ids if group_id in group_owners}
        owner = None
        if group_ids:
            if group_ids.issubset(group_owners) and len(group_admins) == 1:
                owner = next(iter(group_admins))
        else:
            owner = owner_for_user(row["user_id"])
        for file_id in file_ids:
            if owner:
                knowledge_owners[file_id].add(owner)
            else:
                ambiguous_files.add(file_id)

    chat_owners = defaultdict(set)
    for row in bind.execute(sa.text('SELECT user_id, group_id, chat FROM chat')).mappings():
        owner = group_owners.get(row["group_id"]) or owner_for_user(row["user_id"])
        for file_id in _files_in_chat(row["chat"]):
            if owner:
                chat_owners[file_id].add(owner)
            else:
                ambiguous_files.add(file_id)

    file_owners = {}
    file_ids = set()
    for row in bind.execute(sa.text('SELECT id, user_id FROM file')).mappings():
        file_id = row["id"]
        file_ids.add(file_id)
        candidates = knowledge_owners.get(file_id, set())
        if len(candidates) == 1:
            file_owners[file_id] = next(iter(candidates))
        elif len(candidates) > 1:
            ambiguous_files.add(file_id)
            continue
        else:
            candidates = chat_owners.get(file_id, set())
            if len(candidates) == 1:
                file_owners[file_id] = next(iter(candidates))
            elif len(candidates) > 1:
                ambiguous_files.add(file_id)
            else:
                owner = owner_for_user(row["user_id"])
                if owner:
                    file_owners[file_id] = owner

    knowledge_ids = set(bind.execute(sa.text('SELECT id FROM knowledge')).scalars())
    now = int(time.time())
    rows = bind.execute(sa.text("SELECT id, collection_name, vmetadata FROM document_chunk WHERE provenance_status = 'unattributed' ORDER BY id")).mappings()
    while batch := rows.fetchmany(batch_size):
        for row in batch:
            metadata = row["vmetadata"] or {}
            file_id = metadata.get("file_id")
            if not file_id and row["collection_name"].startswith("file-"):
                collection_file_id = row["collection_name"][len("file-"):]
                file_id = collection_file_id if collection_file_id in file_ids else None
            if file_id in ambiguous_files or (file_id and file_id not in file_ids):
                continue
            if file_id and file_id in file_owners:
                bind.execute(
                    sa.text("UPDATE document_chunk SET admin_id = :admin_id, embedding_model_id = :model_id, file_id = :file_id, knowledge_id = :knowledge_id, modality = 'text', embedding_status = 'active', provenance_status = 'attributed', created_at = COALESCE(created_at, :now), updated_at = :now WHERE id = :id AND provenance_status = 'unattributed'"),
                    {"id": row["id"], "admin_id": file_owners[file_id], "model_id": DEFAULT_MODEL_ID, "file_id": file_id, "knowledge_id": row["collection_name"] if row["collection_name"] in knowledge_ids else None, "now": now},
                )
            elif not file_id:
                bind.execute(
                    sa.text("UPDATE document_chunk SET provenance_status = 'out_of_scope', created_at = COALESCE(created_at, :now), updated_at = :now WHERE id = :id AND provenance_status = 'unattributed'"),
                    {"id": row["id"], "now": now},
                )


def upgrade():
    bind = op.get_bind()
    _require_postgres(bind)
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    duplicate = bind.execute(sa.text("SELECT email, version FROM config GROUP BY email, version HAVING count(*) > 1 LIMIT 1")).first()
    if duplicate:
        raise RuntimeError("Cannot add ux_config_email_version: duplicate config email/version rows exist.")
    op.create_index("ux_config_email_version", "config", ["email", "version"], unique=True, if_not_exists=True)

    op.create_table(
        "embedding_models",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("modalities", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("dimension > 0"),
        sa.CheckConstraint("status IN ('enabled', 'disabled', 'deprecated')"),
    )
    now = int(time.time())
    op.bulk_insert(sa.table("embedding_models", sa.column("id"), sa.column("provider"), sa.column("model_name"), sa.column("display_name"), sa.column("dimension"), sa.column("modalities", JSONB()), sa.column("status"), sa.column("created_at"), sa.column("updated_at")), [{"id": DEFAULT_MODEL_ID, "provider": "portkey", "model_name": DEFAULT_MODEL_NAME, "display_name": "OpenAI text-embedding-3-small", "dimension": 1536, "modalities": ["text"], "status": "enabled", "created_at": now, "updated_at": now}])

    op.create_table("rag_chunks", sa.Column("id", sa.Text(), primary_key=True), sa.Column("admin_id", sa.Text(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False), sa.Column("file_id", sa.Text(), sa.ForeignKey("file.id", ondelete="CASCADE"), nullable=False), sa.Column("chunk_index", sa.Integer(), nullable=False), sa.Column("content", sa.Text()), sa.Column("content_type", sa.String(16), nullable=False), sa.Column("chunk_metadata", JSONB()), sa.Column("content_sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.BigInteger(), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.UniqueConstraint("admin_id", "file_id", "chunk_index"), sa.CheckConstraint("chunk_index >= 0"), sa.CheckConstraint("content_type IN ('text', 'image')"))
    op.create_index("ix_rag_chunks_admin_file", "rag_chunks", ["admin_id", "file_id"])
    op.create_index("ix_rag_chunks_file_hash", "rag_chunks", ["file_id", "content_sha256"])

    op.create_table("embedding_jobs", sa.Column("id", sa.Text(), primary_key=True), sa.Column("admin_id", sa.Text(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False), sa.Column("embedding_model_id", sa.Text(), sa.ForeignKey("embedding_models.id", ondelete="RESTRICT"), nullable=False), sa.Column("previous_embedding_model_id", sa.Text(), sa.ForeignKey("embedding_models.id", ondelete="RESTRICT")), sa.Column("job_type", sa.String(32), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("rq_job_id", sa.Text(), unique=True), sa.Column("created_by_user_id", sa.Text(), sa.ForeignKey("user.id", ondelete="SET NULL")), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.BigInteger(), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.Column("started_at", sa.BigInteger()), sa.Column("completed_at", sa.BigInteger()), sa.CheckConstraint("job_type IN ('initial_index', 'reindex_model_change', 'retry_failed')"), sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed', 'partially_failed')"), sa.CheckConstraint("total_files >= 0 AND processed_files >= 0 AND failed_files >= 0"))
    op.create_index("ux_embedding_jobs_admin_active", "embedding_jobs", ["admin_id"], unique=True, postgresql_where=sa.text("status IN ('queued', 'processing')"))
    op.create_index("ix_embedding_jobs_admin_created", "embedding_jobs", ["admin_id", sa.text("created_at DESC")])

    op.create_table("embedding_job_files", sa.Column("job_id", sa.Text(), sa.ForeignKey("embedding_jobs.id", ondelete="CASCADE"), primary_key=True), sa.Column("file_id", sa.Text(), sa.ForeignKey("file.id", ondelete="CASCADE"), primary_key=True), sa.Column("status", sa.String(20), nullable=False), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.BigInteger(), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.Column("started_at", sa.BigInteger()), sa.Column("completed_at", sa.BigInteger()), sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')"), sa.CheckConstraint("attempt_count >= 0"))
    op.create_index("ix_embedding_job_files_status", "embedding_job_files", ["job_id", "status"])

    bind.execute(sa.text("CREATE TABLE IF NOT EXISTS document_chunk (id text PRIMARY KEY, vector vector(1536), collection_name text NOT NULL, text text, vmetadata jsonb)"))
    vector_type = bind.execute(sa.text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = 'document_chunk'::regclass AND attname = 'vector' AND NOT attisdropped")).scalar_one()
    if vector_type != "vector(1536)":
        raise RuntimeError(f"document_chunk.vector must be vector(1536), found {vector_type}.")
    for column, sql_type in [("admin_id", "text"), ("embedding_model_id", "text"), ("file_id", "text"), ("knowledge_id", "text"), ("rag_chunk_id", "text"), ("modality", "varchar(16)"), ("embedding_status", "varchar(16)"), ("provenance_status", "varchar(20) NOT NULL DEFAULT 'unattributed'"), ("created_at", "bigint"), ("updated_at", "bigint")]:
        bind.execute(sa.text(f"ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS {column} {sql_type}"))
    for name, definition in [("document_chunk_admin_id_fkey", "FOREIGN KEY (admin_id) REFERENCES \"user\"(id) ON DELETE SET NULL"), ("document_chunk_embedding_model_id_fkey", "FOREIGN KEY (embedding_model_id) REFERENCES embedding_models(id) ON DELETE RESTRICT"), ("document_chunk_file_id_fkey", "FOREIGN KEY (file_id) REFERENCES file(id) ON DELETE SET NULL"), ("document_chunk_knowledge_id_fkey", "FOREIGN KEY (knowledge_id) REFERENCES knowledge(id) ON DELETE SET NULL"), ("document_chunk_rag_chunk_id_fkey", "FOREIGN KEY (rag_chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE")]:
        bind.execute(sa.text(f"ALTER TABLE document_chunk ADD CONSTRAINT {name} {definition}"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_document_chunk_vector ON document_chunk USING ivfflat (vector vector_cosine_ops) WITH (lists = 100)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_document_chunk_collection_name ON document_chunk (collection_name)"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ux_document_chunk_model_chunk_collection ON document_chunk (admin_id, embedding_model_id, rag_chunk_id, collection_name) WHERE rag_chunk_id IS NOT NULL"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_document_chunk_admin_model_collection ON document_chunk (admin_id, embedding_model_id, collection_name, embedding_status) WHERE provenance_status = 'attributed'"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_document_chunk_file_id ON document_chunk (file_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_document_chunk_knowledge_id ON document_chunk (knowledge_id)"))
    _reconcile_config(bind)
    _backfill_vector_provenance(bind)


def downgrade():
    # Expand-only migration: provenance and indexing records must not be discarded.
    pass
