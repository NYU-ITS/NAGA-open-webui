"""Allow video content in RAG chunks.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3

The video embedding path stores one ``rag_chunks`` row per temporal range.
Application validation already accepts ``content_type='video'``, but the
original database check constraint only permits text and image chunks.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "rag_chunks_content_type_check"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "rag_chunks", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "rag_chunks",
        "content_type IN ('text', 'image', 'video')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "rag_chunks", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "rag_chunks",
        "content_type IN ('text', 'image')",
    )
