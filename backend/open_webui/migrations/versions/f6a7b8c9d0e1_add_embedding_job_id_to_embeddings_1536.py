"""Add embedding_job_id provenance to embeddings_1536 vectors (Spec 07)

Revision ID: f6a7b8c9d0e1
Revises: a1b2c3d4e5f6

Vectors written by a reindex worker are stamped with the durable embedding job
that built them so a partially built target space is tied to its operation.
The column is nullable: ordinary ingestion and legacy rows carry NULL.

This is an expand-only migration; no existing rows are modified.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _require_postgres(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Spec 07 vector provenance requires PostgreSQL with pgvector."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    op.add_column(
        "embeddings_1536",
        sa.Column("embedding_job_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "embeddings_1536_embedding_job_id_fkey",
        "embeddings_1536",
        "embedding_jobs",
        ["embedding_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_embeddings_1536_embedding_job_id",
        "embeddings_1536",
        ["embedding_job_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    op.drop_index(
        "ix_embeddings_1536_embedding_job_id", table_name="embeddings_1536"
    )
    op.drop_constraint(
        "embeddings_1536_embedding_job_id_fkey",
        "embeddings_1536",
        type_="foreignkey",
    )
    op.drop_column("embeddings_1536", "embedding_job_id")
