"""Add error_code column to embedding_jobs

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2024-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('embedding_jobs', sa.Column('error_code', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('embedding_jobs', 'error_code')
