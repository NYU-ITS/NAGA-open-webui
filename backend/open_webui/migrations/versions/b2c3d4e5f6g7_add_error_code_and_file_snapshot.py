"""Add error_code to embedding_jobs and file_snapshot to embedding_job_files

Revision ID: b2c3d4e5f6g7
Revises: a2b3c4d5e6f7
Create Date: 2024-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'embedding_jobs',
        sa.Column('error_code', sa.String(64), nullable=True)
    )
    op.add_column(
        'embedding_job_files',
        sa.Column('file_snapshot', sa.JSON(), nullable=False, server_default='{}')
    )


def downgrade() -> None:
    op.drop_column('embedding_job_files', 'file_snapshot')
    op.drop_column('embedding_jobs', 'error_code')
