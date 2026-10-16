"""Persist file and storage cleanup retries across API restarts."""

from alembic import op
import sqlalchemy as sa

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_cleanup_task",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("file_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_file_cleanup_task_next_attempt_at", "file_cleanup_task", ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_file_cleanup_task_next_attempt_at", table_name="file_cleanup_task")
    op.drop_table("file_cleanup_task")
