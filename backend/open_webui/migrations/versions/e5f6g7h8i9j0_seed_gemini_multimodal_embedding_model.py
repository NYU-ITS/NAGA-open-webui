"""Seed the approved Gemini multimodal embedding model.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9

The registry row reuses the existing 1536-dimensional vector space. This
revision deliberately does not alter any administrator's active or selected
model.
"""

import json
import time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODEL_ID = "embmdl-portkey-vertexai-gemini-embedding-2-1536"
MODEL_NAME = "@vertexai/gemini-embedding-2"


def upgrade() -> None:
    bind = op.get_bind()
    now = int(time.time())
    bind.execute(
        sa.text(
            """
            INSERT INTO embedding_models (
                id,
                provider,
                model_name,
                display_name,
                dimension,
                modalities,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                'portkey',
                :model_name,
                'Vertex AI Gemini Embedding 2',
                1536,
                CAST(:modalities AS jsonb),
                'enabled',
                :now,
                :now
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": MODEL_ID,
            "model_name": MODEL_NAME,
            "modalities": json.dumps(["text", "image"]),
            "now": now,
        },
    )


def downgrade() -> None:
    # Registry rows may already be referenced by admin state and vectors. An
    # expand-only seed must not remove one during rollback.
    pass
