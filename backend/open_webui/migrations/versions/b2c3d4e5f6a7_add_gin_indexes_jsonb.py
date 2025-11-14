"""Add GIN indexes on JSONB access_control columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2024-12-20 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    dialect_name = conn.dialect.name
    
    # Only create GIN indexes for PostgreSQL (JSONB support)
    if dialect_name != "postgresql":
        print(f"Skipping GIN indexes - not PostgreSQL (dialect: {dialect_name})")
        return
    
    # Helper to create GIN index only if it doesn't exist
    def create_gin_idx_if_not_exists(table_name, index_name, column_name):
        if table_name in inspector.get_table_names():
            indexes = inspector.get_indexes(table_name)
            if not any(idx['name'] == index_name for idx in indexes):
                # Create GIN index on JSONB column for faster JSON queries
                op.execute(
                    sa.text(f'CREATE INDEX {index_name} ON "{table_name}" USING GIN ({column_name})')
                )
                print(f"Created GIN index {index_name} on {table_name}({column_name})")
            else:
                print(f"GIN index {index_name} on {table_name}({column_name}) already exists, skipping.")
        else:
            print(f"Table {table_name} does not exist, skipping GIN index creation for {index_name}.")

    # Create GIN indexes on access_control JSONB columns for faster JSON queries
    # These indexes significantly speed up access control checks using @> operator
    create_gin_idx_if_not_exists('model', 'idx_model_access_control_gin', 'access_control')
    create_gin_idx_if_not_exists('knowledge', 'idx_knowledge_access_control_gin', 'access_control')
    create_gin_idx_if_not_exists('prompt', 'idx_prompt_access_control_gin', 'access_control')
    create_gin_idx_if_not_exists('tool', 'idx_tool_access_control_gin', 'access_control')
    
    # Also create GIN index on group.user_ids JSON array for faster group membership checks
    create_gin_idx_if_not_exists('group', 'idx_group_user_ids_gin', 'user_ids')


def downgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    dialect_name = conn.dialect.name
    
    if dialect_name != "postgresql":
        print(f"Skipping GIN index removal - not PostgreSQL (dialect: {dialect_name})")
        return
    
    # Drop GIN indexes
    indexes_to_drop = [
        ('group', 'idx_group_user_ids_gin'),
        ('tool', 'idx_tool_access_control_gin'),
        ('prompt', 'idx_prompt_access_control_gin'),
        ('knowledge', 'idx_knowledge_access_control_gin'),
        ('model', 'idx_model_access_control_gin'),
    ]
    
    for table_name, index_name in indexes_to_drop:
        if table_name in inspector.get_table_names():
            indexes = inspector.get_indexes(table_name)
            if any(idx['name'] == index_name for idx in indexes):
                op.drop_index(index_name, table_name=table_name)
                print(f"Dropped GIN index {index_name} from {table_name}")

