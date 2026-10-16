"""Migration bridge for reverted document_chunk table migration

Revision ID: 817da597db81
Revises: b2c3d4e5f6a7
Create Date: 2025-12-03 16:41:09.171266

This is a no-op migration file that exists to handle the case where a
database was migrated using the original `add_document_chunk_table`
revision (merged 2025-12-03, reverted 2025-12-04) before that migration
file was removed from the codebase. Those databases have `alembic_version`
recorded as this revision id, but no file in the repo can resolve it.

This migration acts as a bridge so Alembic can recognize that database
state without requiring the original migration file.

IMPORTANT: This migration should NOT be applied if it hasn't already been
applied. If the database is at an earlier revision, Alembic will try to
upgrade to this revision, but since this is a no-op, it's safe.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "817da597db81"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """
    No-op upgrade function.

    This migration exists only to bridge the gap for databases that were
    briefly migrated to the original (later reverted) document_chunk table
    revision. We don't want to recreate that table here.

    If the database is already at this revision, this function does nothing.
    If the database is at b2c3d4e5f6a7, this function does nothing (no-op),
    but Alembic will mark the database as being at this revision.
    """
    # No operations needed - this is just a marker migration
    pass


def downgrade():
    """
    No-op downgrade function.

    This migration cannot be properly downgraded without the original
    migration file. However, since this is a no-op, downgrading is also
    a no-op.
    """
    # No operations needed
    pass
