"""Make rag chunk generations immutable with deterministic manifests.

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0

Existing rows are retained as one legacy manifest per admin/file. The old
position-only uniqueness constraint is replaced only after the expanded
manifest-aware constraint exists. No data is removed on upgrade or downgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_MANIFEST_ID = "0" * 64
MANIFEST_CONSTRAINT = "uq_rag_chunks_admin_file_manifest_chunk"
LEGACY_COLUMNS = ("admin_id", "file_id", "chunk_index")


def upgrade() -> None:
    op.add_column(
        "rag_chunks",
        sa.Column(
            "manifest_id",
            sa.String(length=64),
            nullable=True,
            server_default=LEGACY_MANIFEST_ID,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE rag_chunks "
            "SET manifest_id = :legacy_manifest_id "
            "WHERE manifest_id IS NULL"
        ).bindparams(legacy_manifest_id=LEGACY_MANIFEST_ID)
    )
    op.alter_column(
        "rag_chunks",
        "manifest_id",
        existing_type=sa.String(length=64),
        nullable=False,
        server_default=LEGACY_MANIFEST_ID,
    )

    bind = op.get_bind()
    legacy_constraints = [
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("rag_chunks")
        if tuple(constraint.get("column_names") or ()) == LEGACY_COLUMNS
        and constraint.get("name")
    ]
    op.create_unique_constraint(
        MANIFEST_CONSTRAINT,
        "rag_chunks",
        ["admin_id", "file_id", "manifest_id", "chunk_index"],
    )
    for constraint_name in legacy_constraints:
        op.drop_constraint(constraint_name, "rag_chunks", type_="unique")


def downgrade() -> None:
    # Expand-only: prior manifests may share a chunk position, so removing the
    # column or restoring the old constraint would discard valid generations.
    pass
