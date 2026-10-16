"""Seed each admin's configured embedding model as active.

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8

The model-change workflow previously created admin model state lazily. Status
surfaces therefore could not identify the active model until an administrator
requested a model change. This migration snapshots each administrator's
current, enabled ``rag.embedding_model_user`` registry model into a missing
state row.

Existing state is authoritative and is never overwritten. Administrators with
no configured model, or with a model that is not currently enabled in the
registry, remain unseeded rather than receiving a guessed active model.
"""

import time
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _require_postgres(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Admin embedding model state requires PostgreSQL."
        )


def _configured_model_name(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    rag = data.get("rag")
    if not isinstance(rag, dict):
        return None
    model_name = rag.get("embedding_model_user")
    if not isinstance(model_name, str) or not model_name.strip():
        return None
    return model_name.strip()


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgres(bind)

    enabled_models = {
        row["model_name"]: row["id"]
        for row in bind.execute(
            sa.text(
                """
                SELECT id, model_name
                FROM embedding_models
                WHERE status = 'enabled'
                """
            )
        ).mappings()
    }
    admins = bind.execute(
        sa.text(
            """
            SELECT account.id, settings.data
            FROM "user" AS account
            LEFT JOIN config AS settings
              ON settings.email = account.email
             AND settings.version = 0
            WHERE account.role = 'admin'
            """
        )
    ).mappings()

    now = int(time.time())
    insert_state = sa.text(
        """
        INSERT INTO admin_embedding_model_state (
            admin_id,
            active_embedding_model_id,
            target_embedding_model_id,
            latest_embedding_job_id,
            created_at,
            updated_at
        )
        VALUES (:admin_id, :model_id, NULL, NULL, :now, :now)
        ON CONFLICT (admin_id) DO NOTHING
        """
    )
    for admin in admins:
        model_name = _configured_model_name(admin["data"])
        model_id = enabled_models.get(model_name) if model_name else None
        if model_id is None:
            continue
        bind.execute(
            insert_state,
            {
                "admin_id": admin["id"],
                "model_id": model_id,
                "now": now,
            },
        )


def downgrade() -> None:
    # State rows are indistinguishable from rows seeded by the runtime and may
    # already govern indexed vectors. Removing them would be destructive.
    pass
