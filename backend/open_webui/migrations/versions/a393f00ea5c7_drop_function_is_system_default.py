"""Drop function.is_system_default

Rolls back migrations 019/020 (system-default-LLM-function feature,
reverted). Conditional on the column existing, so it's a no-op anywhere
the feature never ran.

Revision ID: a393f00ea5c7
Revises: 817da597db81
Create Date: 2026-08-18

"""

import json

import sqlalchemy as sa
from alembic import op

revision = "a393f00ea5c7"
down_revision = "817da597db81"
branch_labels = None
depends_on = None

_MIGRATEHISTORY_NAMES_TO_CLEAR = (
    "019_add_function_is_system_default",
    "020_reassign_system_default_ownership",
    "020_clear_system_default_portkey_valve",
)


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    return column_name in {c["name"] for c in inspector.get_columns(table_name)}


def _rename_sole_synthetic_functions(bind) -> None:
    """If a synthetic system_default_llm row is an admin's only function,
    rename it to llm_<net_id> instead of deleting it below, so they don't
    lose their only pipe. Must run before the delete step."""
    rows = bind.execute(
        sa.text(
            "SELECT f.id, f.created_by, f.meta FROM \"function\" f "
            "WHERE (f.id = 'system_default_llm' OR f.id LIKE 'system\\_default\\_llm\\_\\_%' ESCAPE '\\') "
            "AND f.is_system_default = TRUE "
            "AND (SELECT COUNT(*) FROM \"function\" f2 WHERE f2.created_by = f.created_by) = 1"
        )
    ).fetchall()

    for old_id, created_by, meta in rows:
        net_id = (
            created_by.split("@")[0]
            if created_by
            else old_id.replace("system_default_llm__", "").replace("system_default_llm", "")
        )
        new_id = f"llm_{net_id}".lower()

        collision = bind.execute(
            sa.text('SELECT 1 FROM "function" WHERE id = :new_id'),
            {"new_id": new_id},
        ).fetchone()
        if collision:
            continue

        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, ValueError):
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["description"] = "llm"

        bind.execute(
            sa.text(
                'UPDATE "function" SET id = :new_id, name = :new_name, meta = :new_meta '
                "WHERE id = :old_id"
            ),
            {"new_id": new_id, "new_name": "llm", "new_meta": json.dumps(meta), "old_id": old_id},
        )


def _reset_adoption_flags(bind) -> None:
    """Clear function.default_adoption_done in every config row that has it set."""
    rows = bind.execute(sa.text('SELECT id, data FROM "config"')).fetchall()

    for row_id, data in rows:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                continue
        if not isinstance(data, dict):
            continue

        function_cfg = data.get("function")
        if not isinstance(function_cfg, dict) or not function_cfg.get("default_adoption_done"):
            continue

        function_cfg["default_adoption_done"] = False
        bind.execute(
            sa.text('UPDATE "config" SET data = :data WHERE id = :id'),
            {"data": json.dumps(data), "id": row_id},
        )


def upgrade() -> None:
    bind = op.get_bind()

    if _column_exists(bind, "function", "is_system_default"):
        _rename_sole_synthetic_functions(bind)

        # is_system_default in the WHERE clause guards against a real
        # function that happens to share the id pattern.
        op.execute(
            sa.text(
                "DELETE FROM \"function\" WHERE "
                "(id = 'system_default_llm' OR id LIKE 'system\\_default\\_llm\\_\\_%' ESCAPE '\\') "
                "AND is_system_default = TRUE"
            )
        )

        op.drop_column("function", "is_system_default")
        _reset_adoption_flags(bind)

    op.execute(
        sa.text(
            "DELETE FROM migratehistory WHERE name IN "
            "('019_add_function_is_system_default', "
            "'020_reassign_system_default_ownership', "
            "'020_clear_system_default_portkey_valve')"
        )
    )


def downgrade() -> None:
    """No-op: nothing here is reconstructable."""
    pass
