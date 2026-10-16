"""Preserve embedding job file rows after source-file deletion.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7

``embedding_job_files`` is an immutable inventory and audit ledger. Its
``file_id`` identifies the source captured when the job was created; it must
not disappear when the mutable ``file`` row is deleted. The persisted
``file_snapshot`` remains available to status and retry flows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _require_postgres(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "The multimodal embedding job ledger requires PostgreSQL."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    op.drop_constraint(
        "embedding_job_files_file_id_fkey",
        "embedding_job_files",
        type_="foreignkey",
    )


def downgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    orphan = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM embedding_job_files AS job_file
            LEFT JOIN "file" AS source_file ON source_file.id = job_file.file_id
            WHERE source_file.id IS NULL
            LIMIT 1
            """
        )
    ).first()
    if orphan is not None:
        raise RuntimeError(
            "Cannot restore the source-file foreign key while preserved "
            "embedding job ledger rows reference deleted files."
        )

    op.create_foreign_key(
        "embedding_job_files_file_id_fkey",
        "embedding_job_files",
        "file",
        ["file_id"],
        ["id"],
        ondelete="CASCADE",
    )
