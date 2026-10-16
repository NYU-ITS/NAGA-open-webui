"""Merge the system-default rollback and video RAG migration branches.

Revision ID: c4d5e6f7g8h9
Revises: a393f00ea5c7, i9j0k1l2m3n4
Create Date: 2026-08-26

Both branches descend from the same migration history but were developed
independently. This no-op revision joins them so Alembic has one head.
"""

from typing import Sequence, Union


revision: str = "c4d5e6f7g8h9"
down_revision: Union[str, Sequence[str], None] = (
    "a393f00ea5c7",
    "i9j0k1l2m3n4",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
