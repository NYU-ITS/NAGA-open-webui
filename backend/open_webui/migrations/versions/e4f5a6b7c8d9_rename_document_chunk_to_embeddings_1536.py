"""Rename document_chunk to embeddings_1536 (Phase 3, Option A).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8

Adopts the existing 1536-dimensional vector table as the canonical physical
store for the registered 1536 model (see the action plan's "Note on existing
vector db"). Existing vectors are retained as-is; no re-embedding is required.
The legacy columns (collection_name, vmetadata, text) are preserved so the
collection-name read path keeps working during the transition; the model-aware
read/write path layers provenance filtering on top of the same table.

This revision is expand-only at the data level: the table is renamed, its
indexes and foreign keys are renamed for clarity, and the rename is reversible
in the downgrade. No vectors are copied or regenerated.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (old_table_or_index_name, new_name) for indexes that follow the table rename.
_INDEX_RENAMES = [
    ("idx_document_chunk_vector", "idx_embeddings_1536_vector"),
    ("idx_document_chunk_collection_name", "idx_embeddings_1536_collection_name"),
    (
        "ux_document_chunk_model_chunk_collection",
        "ux_embeddings_1536_model_chunk_collection",
    ),
    (
        "ix_document_chunk_admin_model_collection",
        "ix_embeddings_1536_admin_model_collection",
    ),
    ("ix_document_chunk_file_id", "ix_embeddings_1536_file_id"),
    ("ix_document_chunk_knowledge_id", "ix_embeddings_1536_knowledge_id"),
]

# Explicitly-named foreign-key constraints from the Phase 1 migration.
_FK_RENAMES = [
    ("document_chunk_admin_id_fkey", "embeddings_1536_admin_id_fkey"),
    (
        "document_chunk_embedding_model_id_fkey",
        "embeddings_1536_embedding_model_id_fkey",
    ),
    ("document_chunk_file_id_fkey", "embeddings_1536_file_id_fkey"),
    ("document_chunk_knowledge_id_fkey", "embeddings_1536_knowledge_id_fkey"),
    ("document_chunk_rag_chunk_id_fkey", "embeddings_1536_rag_chunk_id_fkey"),
]


def _require_postgres(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Phase 3 vector-table rename requires PostgreSQL with pgvector."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    # Rename the physical table.
    op.execute(
        "ALTER TABLE IF EXISTS document_chunk RENAME TO embeddings_1536"
    )

    # Rename indexes that were created by the Phase 1 migration.
    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX IF EXISTS {old_name} RENAME TO {new_name}")

    # Rename explicitly-named foreign-key constraints for readability.
    for old_name, new_name in _FK_RENAMES:
        op.execute(
            f"ALTER TABLE embeddings_1536 RENAME CONSTRAINT {old_name} TO {new_name}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    for old_name, new_name in _FK_RENAMES:
        op.execute(
            f"ALTER TABLE embeddings_1536 RENAME CONSTRAINT {new_name} TO {old_name}"
        )

    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX IF EXISTS {new_name} RENAME TO {old_name}")

    op.execute(
        "ALTER TABLE IF EXISTS embeddings_1536 RENAME TO document_chunk"
    )
