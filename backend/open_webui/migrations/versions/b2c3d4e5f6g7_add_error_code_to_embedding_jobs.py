"""Add error_code column to embedding_jobs

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2024-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add error_code column to embedding_jobs
    op.add_column(
        'embedding_jobs',
        sa.Column('error_code', sa.String(64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('embedding_jobs', 'error_code')
