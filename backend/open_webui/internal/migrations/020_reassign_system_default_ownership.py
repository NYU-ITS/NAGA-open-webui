"""Peewee migrations -- 020_reassign_system_default_ownership.py.

Transitions the shared system_default_llm function row from generic
("system") ownership to the specific admin who owns the Portkey key stored
in its valve. This is a prerequisite for per-admin function copies: once
created_by is set to a real admin email, the visibility filter
(`created_by == user_email`) can correctly scope it.

Logic:
  1. Read the PORTKEY_API_KEY from system_default_llm.valves.
  2. Find the admin whose config row contains that key (rag.openai_api_key
     or audio portkey paths).
  3. If no match is found (valve is empty or key not in any config row),
     pick the first admin with any Portkey key configured.
  4. UPDATE function SET created_by = <email>, user_id = <user_id>
     WHERE id = 'system_default_llm' AND is_system_default = TRUE.
  5. No-op if system_default_llm does not exist or already has a real
     admin as created_by.

Rollback: no-op (safe to leave as-is; re-running the migration is idempotent).
"""

import json
from contextlib import suppress

import peewee as pw
from peewee_migrate import Migrator

with suppress(ImportError):
    import playhouse.postgres_ext as pw_pext


def _get_valve_key(database: pw.Database) -> str:
    """Return the PORTKEY_API_KEY stored in system_default_llm.valves, or ''."""
    try:
        cursor = database.execute_sql(
            "SELECT valves FROM function WHERE id = 'system_default_llm'"
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return ""
        valves = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        return valves.get("PORTKEY_API_KEY", "") if isinstance(valves, dict) else ""
    except Exception:
        return ""


def _find_admin_by_key(database: pw.Database, valve_key: str) -> tuple:
    """Return (email, user_id) for the admin whose config key matches valve_key.
    Falls back to the first admin with any Portkey key if no exact match.
    Returns (None, None) if nothing can be found."""
    is_postgres = not isinstance(database, pw.SqliteDatabase)

    if valve_key:
        # Exact-match search
        if is_postgres:
            sql = """
                SELECT c.email, u.id
                FROM config c
                JOIN "user" u ON u.email = c.email
                WHERE u.role = 'admin'
                  AND (
                        c.data::jsonb->'rag'->>'openai_api_key' = %(key)s
                     OR c.data::jsonb->'audio'->'stt'->'portkey'->>'api_key' = %(key)s
                     OR c.data::jsonb->'audio'->'tts'->'portkey'->>'api_key' = %(key)s
                  )
                LIMIT 1
            """
            params = {"key": valve_key}
        else:
            sql = """
                SELECT c.email, u.id
                FROM config c
                JOIN user u ON u.email = c.email
                WHERE u.role = 'admin'
                  AND (
                        json_extract(c.data, '$.rag.openai_api_key') = ?
                     OR json_extract(c.data, '$.audio.stt.portkey.api_key') = ?
                     OR json_extract(c.data, '$.audio.tts.portkey.api_key') = ?
                  )
                LIMIT 1
            """
            params = (valve_key, valve_key, valve_key)

        try:
            cursor = database.execute_sql(sql, params)
            row = cursor.fetchone()
            if row:
                return row[0], row[1]
        except Exception:
            pass

    # Fallback: first admin with any Portkey key
    if is_postgres:
        fallback_sql = """
            SELECT c.email, u.id
            FROM config c
            JOIN "user" u ON u.email = c.email
            WHERE u.role = 'admin'
              AND (
                    (c.data::jsonb->'rag'->>'openai_api_key' IS NOT NULL
                     AND c.data::jsonb->'rag'->>'openai_api_key' != '')
                 OR (c.data::jsonb->'audio'->'stt'->'portkey'->>'api_key' IS NOT NULL
                     AND c.data::jsonb->'audio'->'stt'->'portkey'->>'api_key' != '')
              )
            LIMIT 1
        """
        params = None
    else:
        fallback_sql = """
            SELECT c.email, u.id
            FROM config c
            JOIN user u ON u.email = c.email
            WHERE u.role = 'admin'
              AND (
                    (json_extract(c.data, '$.rag.openai_api_key') IS NOT NULL
                     AND json_extract(c.data, '$.rag.openai_api_key') != '')
                 OR (json_extract(c.data, '$.audio.stt.portkey.api_key') IS NOT NULL
                     AND json_extract(c.data, '$.audio.stt.portkey.api_key') != '')
              )
            LIMIT 1
        """
        params = None

    try:
        cursor = database.execute_sql(fallback_sql, params)
        row = cursor.fetchone()
        if row:
            return row[0], row[1]
    except Exception:
        pass

    return None, None


def _already_owned_by_admin(database: pw.Database) -> bool:
    """Return True if system_default_llm already has a non-system created_by."""
    try:
        cursor = database.execute_sql(
            "SELECT created_by FROM function WHERE id = 'system_default_llm'"
        )
        row = cursor.fetchone()
        if not row:
            return True  # Row doesn't exist — nothing to do
        return row[0] not in (None, "", "system")
    except Exception:
        return True


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    """Reassign system_default_llm to the admin who owns its Portkey key."""
    if fake:
        return

    is_postgres = not isinstance(database, pw.SqliteDatabase)

    # In Postgres a failed SQL statement aborts the whole transaction, which
    # would prevent peewee_migrate from recording this migration as done.
    # Use a savepoint so any error inside rolls back cleanly and the outer
    # transaction (owned by peewee_migrate) stays usable.
    if is_postgres:
        database.execute_sql("SAVEPOINT mig_020")

    try:
        if _already_owned_by_admin(database):
            if is_postgres:
                database.execute_sql("RELEASE SAVEPOINT mig_020")
            return

        valve_key = _get_valve_key(database)
        admin_email, admin_user_id = _find_admin_by_key(database, valve_key)

        if not admin_email:
            # No admin with a configured key — leave as-is.
            # The /ensure endpoint sets ownership when the admin next saves
            # their Workspace Settings.
            if is_postgres:
                database.execute_sql("RELEASE SAVEPOINT mig_020")
            return

        if is_postgres:
            database.execute_sql(
                """
                UPDATE function
                   SET created_by = %s,
                       user_id    = %s
                 WHERE id = 'system_default_llm'
                   AND is_system_default = TRUE
                """,
                (admin_email, admin_user_id),
            )
            database.execute_sql("RELEASE SAVEPOINT mig_020")
        else:
            database.execute_sql(
                """
                UPDATE function
                   SET created_by = ?,
                       user_id    = ?
                 WHERE id = 'system_default_llm'
                   AND is_system_default = 1
                """,
                (admin_email, admin_user_id),
            )
    except Exception:
        if is_postgres:
            try:
                database.execute_sql("ROLLBACK TO SAVEPOINT mig_020")
                database.execute_sql("RELEASE SAVEPOINT mig_020")
            except Exception:
                pass


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    """No rollback — ownership reassignment is safe to leave as-is."""
    pass
