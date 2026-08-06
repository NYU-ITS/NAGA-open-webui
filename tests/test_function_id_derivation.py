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
- /ensure is idempotent (safe to call on every workspace settings save)
- _prepopulate_portkey_valves finds Valves nested inside Pipe (not just top-level Valves)
- Step 1 returns immediately (no valve update) when is_system_default=True already exists
- Step 2 adopts an existing content-matched clone and marks is_system_default=True
- Step 3 creates a fresh function with is_active=False when no content match exists
- Step 3 skips creation and returns None when the derived ID is already taken by modified content

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


# ── 10: /ensure is idempotent (safe to call on every workspace settings save) ─

def test_ensure_idempotent(tmp_path):
    """WorkspaceSettings.svelte now calls ensureAdminSystemDefault on every save
    (not just when the key changes) so old admin accounts get their system default
    function without needing to change their key. The ensure logic must be
    idempotent: two consecutive calls with the same key must leave exactly one
    system default function with the correct valve."""
    data = run_scenario(tmp_path, "ENSURE_IDEMPOTENT")
    assert data["first_call_succeeded"] is True, "first ensure call must return a function"
    assert data["second_call_succeeded"] is True, "second ensure call must return a function"
    assert data["same_id"] is True, "both calls must return the same function ID"
    assert data["key_preserved"] is True, "PORTKEY_API_KEY must equal the key passed to ensure"
    assert data["exactly_one_system_default"] is True, (
        "ensure must not create a duplicate system default — exactly one must exist"
    )


# ── 11: _prepopulate_portkey_valves finds Valves nested inside Pipe ───────────

def test_pipe_nested_valves_prepopulated(tmp_path):
    """The system default source has Valves nested inside Pipe (not top-level).
    _prepopulate_portkey_valves must check Pipe.Valves as a fallback so clones
    of the system default get their PORTKEY_API_KEY pre-populated at creation."""
    data = run_scenario(tmp_path, "PIPE_NESTED_VALVES_PREPOPULATED")
    assert data["has_portkey_key"] is True, (
        "_prepopulate must find PORTKEY_API_KEY even when Valves is inside Pipe"
    )
    assert data["key_is_set"] is True, "PORTKEY_API_KEY must be non-empty after pre-population"
    assert data["key_value_correct"] is True, "pre-populated key must match workspace key"
    assert data["has_portkey_url"] is True, (
        "_prepopulate must also set PORTKEY_API_BASE_URL when defined in Pipe.Valves"
    )


# ── 12: Step 1 short-circuits without updating the valve ─────────────────────

def test_step1_returns_immediately(tmp_path):
    """When is_system_default=True already exists, ensure must detect it in Step 1
    and return immediately without updating the valve. The cascade owns the valve
    after first setup; ensure must not overwrite it on every admin login."""
    data = run_scenario(tmp_path, "STEP1_RETURNS_IMMEDIATELY")
    assert data["step1_detected"] is True, (
        "ensure must detect the existing is_system_default=True function in Step 1"
    )
    assert data["function_returned"] is True, (
        "Step 1 must return the existing system default function"
    )
    assert data["valve_not_updated"] is True, (
        "Step 1 must not update PORTKEY_API_KEY — valve must retain original value"
    )
    assert data["url_not_updated"] is True, (
        "Step 1 must not update PORTKEY_API_BASE_URL — valve must retain original value"
    )


# ── 13: Step 2 adopts existing content-matched clone ─────────────────────────

def test_content_match_adopted(tmp_path):
    """When the admin has a function with matching content (same as system default)
    but not marked is_system_default=True, ensure Step 2 must adopt it: mark
    is_system_default=True, write canonical content, and set the valve.
    No new function must be created."""
    data = run_scenario(tmp_path, "CONTENT_MATCH_ADOPTED")
    assert data["adopted"] is True, (
        "Step 2 must find the content-matched clone and adopt it"
    )
    assert data["adopted_id_is_clone"] is True, (
        "adopted function must be the original clone, not a new function"
    )
    assert data["no_new_function_created"] is True, (
        "Step 2 must not create a new function — exactly one system default must exist"
    )
    assert data["valve_key_set"] is True, (
        "adopted function valve must have PORTKEY_API_KEY set to the provided key"
    )
    assert data["valve_url_set"] is True, (
        "adopted function valve must have PORTKEY_API_BASE_URL set"
    )


# ── 14: Step 3 creates fresh function with is_active=False ───────────────────

def test_content_mismatch_fresh_inactive(tmp_path):
    """When the admin has no function with matching content, ensure Step 3 must
    create a fresh system default function with is_active=False so the admin's
    existing active function continues running undisturbed."""
    data = run_scenario(tmp_path, "CONTENT_MISMATCH_FRESH_INACTIVE")
    assert data["new_function_created"] is True, (
        "Step 3 must create a new system default function when no content match exists"
    )
    assert data["new_function_inactive"] is True, (
        "freshly created system default must start with is_active=False"
    )
    assert data["new_function_is_system_default"] is True, (
        "freshly created function must have is_system_default=True"
    )
    assert data["original_function_still_active"] is True, (
        "admin's original active function must remain active — ensure must not touch it"
    )
    assert data["valve_key_set"] is True, (
        "fresh system default valve must have PORTKEY_API_KEY set"
    )


# ── 15: Step 3 skips when derived ID is taken by modified content ─────────────

def test_id_collision_skip(tmp_path):
    """When the derived system default ID (system_default_llm__<net_id>) is
    already taken by a function with different content, ensure must skip creation
    and return None. The admin's modified function must remain completely untouched."""
    data = run_scenario(tmp_path, "ID_COLLISION_SKIP")
    assert data["step1_no_system_default"] is True, (
        "Step 1 must find no is_system_default=True function"
    )
    assert data["step2_no_content_match"] is True, (
        "Step 2 must find no content match for the modified function"
    )
    assert data["id_collision_detected"] is True, (
        "Step 3 must detect that the derived ID is already occupied"
    )
    assert data["no_duplicate_created"] is True, (
        "ensure must not create a second function when ID collision is detected"
    )
    assert data["original_content_intact"] is True, (
        "admin's modified function content must remain completely untouched"
    )
    assert data["original_still_active"] is True, (
        "admin's modified function must remain active after the collision skip"
    )
