"""Append video to Gemini multimodal embedding model modalities.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2

Expand-only migration: appends ``"video"`` to the modalities JSONB array for
the existing Gemini embedding model row. Idempotent — uses a SQL expression
that only adds the element when it is not already present. Does not alter
administrator model state.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODEL_ID = "embmdl-portkey-vertexai-gemini-embedding-2-1536"


def upgrade() -> None:
    bind = op.get_bind()
    # Append "video" to the modalities array only when it is not already
    # present. The jsonb @> operator checks containment; CASE ensures the
    # update is a no-op when "video" is already listed.
    bind.execute(
        sa.text(
            """
            UPDATE embedding_models
            SET modalities = modalities || '"video"'::jsonb,
                updated_at = EXTRACT(EPOCH FROM NOW())::integer
            WHERE id = :model_id
              AND NOT (modalities @> '"video"'::jsonb)
            """
        ),
        {"model_id": MODEL_ID},
    )


def downgrade() -> None:
    # Expand-only: removing "video" from modalities during rollback would
    # orphan any video vectors already stored in the shared vector space.
    pass
