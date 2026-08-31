"""Allow audio content in RAG chunks and the Gemini embedding model.

Revision ID: j0k1l2m3n4o5
Revises: c4d5e6f7g8h9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "c4d5e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "rag_chunks_content_type_check"
MODEL_ID = "embmdl-portkey-vertexai-gemini-embedding-2-1536"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "rag_chunks", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "rag_chunks",
        "content_type IN ('text', 'image', 'video', 'audio')",
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE embedding_models
            SET modalities = modalities || '"audio"'::jsonb,
                updated_at = EXTRACT(EPOCH FROM NOW())::integer
            WHERE id = :model_id
              AND NOT (modalities @> '"audio"'::jsonb)
            """
        ),
        {"model_id": MODEL_ID},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE embedding_models
            SET modalities = modalities - 'audio',
                updated_at = EXTRACT(EPOCH FROM NOW())::integer
            WHERE id = :model_id
              AND modalities @> '"audio"'::jsonb
            """
        ),
        {"model_id": MODEL_ID},
    )

    op.drop_constraint(CONSTRAINT_NAME, "rag_chunks", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "rag_chunks",
        "content_type IN ('text', 'image', 'video')",
    )
