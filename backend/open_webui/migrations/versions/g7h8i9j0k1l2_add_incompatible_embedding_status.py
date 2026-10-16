"""Track incompatible embedding files as successful terminal skips.

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1

PostgreSQL-only, expand-safe changes for multimodal reindex status. Existing
rows remain valid and receive an incompatible counter of zero.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _require_postgres(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Embedding incompatible status requires PostgreSQL with pgvector."
        )


def _replace_status_check(bind, table: str, allowed: str, name: str) -> None:
    constraints = list(
        bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c' "
                "AND pg_get_constraintdef(oid) ILIKE '%status%'"
            ),
            {"table": table},
        ).scalars()
    )
    for constraint_name in constraints:
        bind.execute(
            sa.text(
                f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint_name}"'
            )
        )
    bind.execute(
        sa.text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({allowed})'
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    bind.execute(
        sa.text(
            "ALTER TABLE embedding_jobs "
            "ADD COLUMN IF NOT EXISTS incompatible_files integer NOT NULL DEFAULT 0"
        )
    )
    _replace_status_check(
        bind,
        "embedding_jobs",
        "status IN ('queued', 'processing', 'completed', 'failed', 'partially_failed')",
        "embedding_jobs_status_check",
    )
    _replace_status_check(
        bind,
        "embedding_job_files",
        "status IN ('pending', 'processing', 'completed', 'failed', 'incompatible')",
        "embedding_job_files_status_check",
    )


def downgrade() -> None:
    # Expand-only: incompatible rows and their aggregate data must not be
    # discarded by a downgrade.
    pass
