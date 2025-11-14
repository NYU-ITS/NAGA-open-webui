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
    
    # Helper to convert JSON column to JSONB if needed
    def convert_json_to_jsonb_if_needed(table_name, column_name):
        """Convert JSON column to JSONB for GIN index support"""
        if table_name not in inspector.get_table_names():
            print(f"Table {table_name} does not exist, skipping.")
            return False
        
        columns = inspector.get_columns(table_name)
        column_info = next((col for col in columns if col['name'] == column_name), None)
        
        if not column_info:
            print(f"Column {column_name} does not exist in {table_name}, skipping.")
            return False
        
        # Check if column is already JSONB
        col_type = str(column_info['type'])
        if 'jsonb' in col_type.lower():
            print(f"Column {table_name}.{column_name} is already JSONB, skipping conversion.")
            return True
        
        # Convert JSON to JSONB
        print(f"Converting {table_name}.{column_name} from JSON to JSONB...")
        try:
            op.execute(
                sa.text(f'ALTER TABLE "{table_name}" ALTER COLUMN {column_name} TYPE jsonb USING {column_name}::jsonb')
            )
            print(f"Successfully converted {table_name}.{column_name} to JSONB")
            return True
        except Exception as e:
            print(f"Error converting {table_name}.{column_name} to JSONB: {e}")
            return False
    
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

    # Step 1: Convert JSON columns to JSONB (required for GIN indexes)
    print("Converting JSON columns to JSONB...")
    convert_json_to_jsonb_if_needed('model', 'access_control')
    convert_json_to_jsonb_if_needed('knowledge', 'access_control')
    convert_json_to_jsonb_if_needed('prompt', 'access_control')
    convert_json_to_jsonb_if_needed('tool', 'access_control')
    convert_json_to_jsonb_if_needed('group', 'user_ids')
    
    # Refresh inspector after column type changes
    inspector = Inspector.from_engine(conn)
    
    # Step 2: Create GIN indexes on access_control JSONB columns for faster JSON queries
    # These indexes significantly speed up access control checks using @> operator
    print("Creating GIN indexes...")
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

