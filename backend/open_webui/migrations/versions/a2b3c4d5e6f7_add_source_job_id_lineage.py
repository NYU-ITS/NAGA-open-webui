"""Add source_job_id lineage to embedding_jobs (Spec 11)

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1

Retry jobs record which job they were spawned from so chained retry
staleness checks can walk the full lineage.  The column is nullable:
original model-change jobs carry NULL; retry_failed jobs reference their
source.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "embedding_jobs",
        sa.Column("source_job_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "embedding_jobs_source_job_id_fkey",
        "embedding_jobs",
        "embedding_jobs",
        ["source_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_embedding_jobs_source_job_id",
        "embedding_jobs",
        ["source_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_embedding_jobs_source_job_id", table_name="embedding_jobs"
    )
    op.drop_constraint(
        "embedding_jobs_source_job_id_fkey",
        "embedding_jobs",
        type_="foreignkey",
    )
    op.drop_column("embedding_jobs", "source_job_id")
