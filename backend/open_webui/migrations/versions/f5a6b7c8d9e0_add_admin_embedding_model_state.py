"""Add admin_embedding_model_state table (Phase 4, Spec 01).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9

Creates the durable, admin-scoped authority over embedding model spaces. One
row per admin records the active (retrievable) model, the optional target model
being built by a reindex operation, and the latest model-change/retry job. Only
registry model IDs are stored; model names remain presentation/config data, so
no credentials are persisted here.

Rows are seeded lazily at runtime (Spec 01 ensures state from the admin's
configured model on first resolution), so this migration only creates the table
and its foreign keys.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _require_postgres(bind):
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "admin_embedding_model_state requires PostgreSQL (pgvector subsystem)."
        )


def upgrade():
    bind = op.get_bind()
    _require_postgres(bind)

    op.create_table(
        "admin_embedding_model_state",
        sa.Column(
            "admin_id",
            sa.String(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "active_embedding_model_id",
            sa.String(),
            sa.ForeignKey("embedding_models.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_embedding_model_id",
            sa.String(),
            sa.ForeignKey("embedding_models.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "latest_embedding_job_id",
            sa.String(),
            sa.ForeignKey("embedding_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_admin_embedding_model_state_target",
        "admin_embedding_model_state",
        ["target_embedding_model_id"],
    )
    op.create_index(
        "ix_admin_embedding_model_state_latest_job",
        "admin_embedding_model_state",
        ["latest_embedding_job_id"],
    )


def downgrade():
    op.drop_index(
        "ix_admin_embedding_model_state_latest_job",
        table_name="admin_embedding_model_state",
    )
    op.drop_index(
        "ix_admin_embedding_model_state_target",
        table_name="admin_embedding_model_state",
    )
    op.drop_table("admin_embedding_model_state")
