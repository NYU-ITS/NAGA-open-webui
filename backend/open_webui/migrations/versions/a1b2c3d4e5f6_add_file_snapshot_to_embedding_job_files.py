"""Add file_snapshot column to embedding_job_files

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2024-01-XX XX:XX:XX.XXXXXX

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add file_snapshot JSON column with server default for existing rows
    op.add_column(
        'embedding_job_files',
        sa.Column('file_snapshot', sa.JSON(), nullable=False, server_default='{}')
    )
    # Remove server default after column is added
    op.alter_column(
        'embedding_job_files',
        'file_snapshot',
        server_default=None
    )
    
    # Add partial unique index to prevent concurrent active jobs per admin
    # This provides final defense when row locks cannot serialize creators
    op.create_index(
        'uq_embedding_jobs_admin_active',
        'embedding_jobs',
        ['admin_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing')")
    )


def downgrade() -> None:
    op.drop_index('uq_embedding_jobs_admin_active', table_name='embedding_jobs')
    op.drop_column('embedding_job_files', 'file_snapshot')
