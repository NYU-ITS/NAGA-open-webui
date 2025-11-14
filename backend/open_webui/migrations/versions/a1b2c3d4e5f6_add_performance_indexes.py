"""Add performance indexes

Revision ID: a1b2c3d4e5f6
Revises: ca81bd47c050
Create Date: 2024-12-20 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "ca81bd47c050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    
    # Get existing indexes to avoid duplicates
    existing_indexes = {}
    for table_name in ['user', 'model', 'knowledge', 'prompt', 'tool', 'group']:
        if table_name in inspector.get_table_names():
            existing_indexes[table_name] = [idx['name'] for idx in inspector.get_indexes(table_name)]
    
    # Indexes for user table
    if 'user' in inspector.get_table_names():
        if 'idx_user_created_at' not in existing_indexes.get('user', []):
            op.create_index('idx_user_created_at', 'user', ['created_at'], unique=False)
        if 'idx_user_email' not in existing_indexes.get('user', []):
            op.create_index('idx_user_email', 'user', ['email'], unique=False)
    
    # Indexes for model table
    if 'model' in inspector.get_table_names():
        if 'idx_model_user_id' not in existing_indexes.get('model', []):
            op.create_index('idx_model_user_id', 'model', ['user_id'], unique=False)
        if 'idx_model_base_model_id' not in existing_indexes.get('model', []):
            op.create_index('idx_model_base_model_id', 'model', ['base_model_id'], unique=False)
        if 'idx_model_created_at' not in existing_indexes.get('model', []):
            op.create_index('idx_model_created_at', 'model', ['created_at'], unique=False)
        if 'idx_model_is_active' not in existing_indexes.get('model', []):
            op.create_index('idx_model_is_active', 'model', ['is_active'], unique=False)
        if 'idx_model_created_by' not in existing_indexes.get('model', []):
            op.create_index('idx_model_created_by', 'model', ['created_by'], unique=False)
    
    # Indexes for knowledge table
    if 'knowledge' in inspector.get_table_names():
        if 'idx_knowledge_user_id' not in existing_indexes.get('knowledge', []):
            op.create_index('idx_knowledge_user_id', 'knowledge', ['user_id'], unique=False)
        if 'idx_knowledge_updated_at' not in existing_indexes.get('knowledge', []):
            op.create_index('idx_knowledge_updated_at', 'knowledge', ['updated_at'], unique=False)
    
    # Indexes for prompt table
    if 'prompt' in inspector.get_table_names():
        if 'idx_prompt_user_id' not in existing_indexes.get('prompt', []):
            op.create_index('idx_prompt_user_id', 'prompt', ['user_id'], unique=False)
        if 'idx_prompt_timestamp' not in existing_indexes.get('prompt', []):
            op.create_index('idx_prompt_timestamp', 'prompt', ['timestamp'], unique=False)
    
    # Indexes for tool table
    if 'tool' in inspector.get_table_names():
        if 'idx_tool_user_id' not in existing_indexes.get('tool', []):
            op.create_index('idx_tool_user_id', 'tool', ['user_id'], unique=False)
        if 'idx_tool_updated_at' not in existing_indexes.get('tool', []):
            op.create_index('idx_tool_updated_at', 'tool', ['updated_at'], unique=False)
        if 'idx_tool_created_by' not in existing_indexes.get('tool', []):
            op.create_index('idx_tool_created_by', 'tool', ['created_by'], unique=False)
    
    # Indexes for group table
    if 'group' in inspector.get_table_names():
        if 'idx_group_user_id' not in existing_indexes.get('group', []):
            op.create_index('idx_group_user_id', 'group', ['user_id'], unique=False)
        if 'idx_group_updated_at' not in existing_indexes.get('group', []):
            op.create_index('idx_group_updated_at', 'group', ['updated_at'], unique=False)


def downgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    
    # Drop indexes in reverse order
    indexes_to_drop = [
        ('group', 'idx_group_updated_at'),
        ('group', 'idx_group_user_id'),
        ('tool', 'idx_tool_created_by'),
        ('tool', 'idx_tool_updated_at'),
        ('tool', 'idx_tool_user_id'),
        ('prompt', 'idx_prompt_timestamp'),
        ('prompt', 'idx_prompt_user_id'),
        ('knowledge', 'idx_knowledge_updated_at'),
        ('knowledge', 'idx_knowledge_user_id'),
        ('model', 'idx_model_created_by'),
        ('model', 'idx_model_is_active'),
        ('model', 'idx_model_created_at'),
        ('model', 'idx_model_base_model_id'),
        ('model', 'idx_model_user_id'),
        ('user', 'idx_user_email'),
        ('user', 'idx_user_created_at'),
    ]
    
    for table_name, index_name in indexes_to_drop:
        if table_name in inspector.get_table_names():
            try:
                op.drop_index(index_name, table_name=table_name)
            except Exception:
                pass  # Index might not exist

