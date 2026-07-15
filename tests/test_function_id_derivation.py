"""
Function ID derivation and related isolation tests.

Verifies that:
- Function IDs are derived server-side from name + net_id
- Special-char names fall back to 'function__<net_id>'
- Duplicate names and ID collisions are detected
- /ensure creates system_default_llm__<net_id>, not a UUID-based ID
- find_workspace_portkey_key() is scoped per admin
- PORTKEY_API_BASE_URL is included in stored valves when the Valves class defines it
- Explicit null is preserved through the valve update route (not replaced by Pydantic default '')
- /ensure writes PORTKEY_API_BASE_URL alongside PORTKEY_API_KEY

Run locally (from project root):

    python3 -m pytest tests/test_function_id_derivation.py -v

Or inside the container after docker cp:

    docker cp backend/open_webui/config.py open-webui:/app/backend/open_webui/config.py
    docker cp backend/open_webui/utils/portkey.py open-webui:/app/backend/open_webui/utils/portkey.py
    docker cp backend/open_webui/routers/functions.py open-webui:/app/backend/open_webui/routers/functions.py
    docker cp tests open-webui:/app/tests
    docker compose -f docker-compose.local.yaml exec -e VECTOR_DB=chroma \\
        -e PYTHONPATH=/app/backend -w /app/backend open-webui \\
        python3 -m pytest /app/tests/test_function_id_derivation.py -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
RUNNER = Path(__file__).resolve().parent / "_function_id_runner.py"


def run_scenario(tmp_path, scenario):
    db_path = tmp_path / "scratch.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND_DIR),
        "VECTOR_DB": "chroma",
        "WEBUI_SECRET_KEY": os.environ.get("WEBUI_SECRET_KEY") or "test-secret-key-for-scenario-tests",
    }
    result = subprocess.run(
        [sys.executable, str(RUNNER), scenario],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    last_line = result.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


# ── 1: ID is derived from function name + net_id ─────────────────────────────

def test_derives_id_from_name(tmp_path):
    """Function 'My Custom LLM!' created by aa12947@nyu.edu must have
    id='my_custom_llm__aa12947' and name='My Custom LLM!' (no suffix appended)."""
    data = run_scenario(tmp_path, "DERIVES_ID_FROM_NAME")
    assert data["id_correct"] is True, (
        f"expected id='my_custom_llm__aa12947', got derived_id={data['derived_id']!r} / db_id={data['db_id']!r}"
    )
    assert data["name_unchanged"] is True, (
        f"function name must stay unchanged, got db_name={data['db_name']!r}"
    )
    assert data["name_has_no_suffix"] is True, (
        "function name must not have net_id suffix appended"
    )


# ── 2: All-special-char name falls back to 'function__<net_id>' ──────────────

def test_special_chars_fallback(tmp_path):
    """Name '!!!' sanitizes to empty string, so fallback 'function' must be used
    and the derived ID must be 'function__aa12947'."""
    data = run_scenario(tmp_path, "SPECIAL_CHARS_FALLBACK")
    assert data["correct"] is True, (
        f"expected derived_id='function__aa12947', got {data['derived_id']!r}"
    )


# ── 3: Duplicate name (case-insensitive) is detected ─────────────────────────

def test_duplicate_name_rejected(tmp_path):
    """Creating a second function named 'Alpha' (same admin, case-insensitive
    match) must be detected by the pre-insert name check."""
    data = run_scenario(tmp_path, "DUPLICATE_NAME_REJECTED")
    assert data["duplicate_detected"] is True, (
        "duplicate name check must flag a second function with the same name"
    )


# ── 4: ID collision between 'My Function' and 'My-Function' is detected ──────

def test_id_collision_rejected(tmp_path):
    """'My Function' and 'My-Function' both sanitize to the same ID
    'my_function__aa12947'. The second creation must be detected as a collision
    via the pre-insert ID check."""
    data = run_scenario(tmp_path, "ID_COLLISION_REJECTED")
    assert data["ids_are_same"] is True, (
        "both names must derive the same function ID"
    )
    assert data["collision_detected"] is True, (
        "second function with colliding ID must be detected before insert"
    )


# ── 5: /ensure uses net_id not UUID ──────────────────────────────────────────

def test_ensure_uses_net_id(tmp_path):
    """/ensure must derive the system default ID as
    system_default_llm__<net_id> (no UUID dashes), not system_default_llm__<user.id>."""
    data = run_scenario(tmp_path, "ENSURE_USES_NET_ID")
    assert data["id_uses_net_id"] is True, (
        f"expected system_default_llm__aa12947, got function_id={data['function_id']!r}"
    )
    assert data["id_has_no_uuid"] is True, (
        "function ID must not contain UUID dashes"
    )


# ── 6: find_workspace_portkey_key is scoped per admin ────────────────────────

def test_scoped_key_isolation(tmp_path):
    """find_workspace_portkey_key('admin_a@nyu.edu') must return admin A's key
    and not admin B's, even when both config rows are in the DB."""
    data = run_scenario(tmp_path, "SCOPED_KEY_ISOLATION")
    assert data["a_got_own_key"] is True, "admin A must receive their own Portkey key"
    assert data["b_got_own_key"] is True, "admin B must receive their own Portkey key"
    assert data["keys_isolated"] is True, "scoped lookups must not cross admin boundaries"
    assert data["unscoped_found_a_key"] is True, (
        "unscoped lookup (startup path) must return one of the available keys"
    )


# ── 7: PORTKEY_API_BASE_URL is stored in valve when the Valves class defines it

def test_portkey_url_in_valve(tmp_path):
    """After _prepopulate_portkey_valves runs on a function whose Valves class
    defines PORTKEY_API_BASE_URL, the stored valve must contain that field."""
    data = run_scenario(tmp_path, "PORTKEY_URL_IN_VALVE")
    assert data["has_portkey_key"] is True, "valve must contain PORTKEY_API_KEY"
    assert data["has_portkey_url"] is True, "valve must contain PORTKEY_API_BASE_URL"
    assert data["key_is_set"] is True, "PORTKEY_API_KEY must be non-empty"


# ── 8: Explicit null is preserved, not replaced by Pydantic default '' ────────

def test_null_portkey_preserved(tmp_path):
    """Sending PORTKEY_API_KEY=null to the valve update route must store null in
    the DB — not the Pydantic default empty string ''. This is the signal for
    the frontend that the Workspace toggle should be active."""
    data = run_scenario(tmp_path, "NULL_PORTKEY_PRESERVED")
    assert data["portkey_key_is_null"] is True, (
        "PORTKEY_API_KEY=null must be preserved in the DB, not replaced by ''"
    )
    assert data["portkey_key_is_not_empty_string"] is True, (
        "PORTKEY_API_KEY must not be stored as empty string when null was sent"
    )
    assert data["url_preserved"] is True, (
        "PORTKEY_API_BASE_URL must be unaffected by a null update to PORTKEY_API_KEY"
    )


# ── 9: /ensure writes PORTKEY_API_BASE_URL into system default valve ──────────

def test_ensure_includes_url(tmp_path):
    """/ensure must write PORTKEY_API_BASE_URL alongside PORTKEY_API_KEY into
    the system default function's valve."""
    data = run_scenario(tmp_path, "ENSURE_INCLUDES_URL")
    assert data["has_portkey_key"] is True, "system default valve must have PORTKEY_API_KEY"
    assert data["has_portkey_url"] is True, "system default valve must have PORTKEY_API_BASE_URL"
    assert data["key_is_set"] is True, "PORTKEY_API_KEY must be non-empty"
    assert data["url_is_set"] is True, "PORTKEY_API_BASE_URL must be non-empty"
