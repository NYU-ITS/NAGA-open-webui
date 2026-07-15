"""
Per-admin system default function key isolation tests.

Verifies that each admin's system default function has its own isolated
PORTKEY_API_KEY in the valve (no cross-admin leakage), and that visibility
scoping in get_functions() prevents admins from seeing each other's keys.

Run the same way as the other scenario tests:

    cd dev/NAGA-open-webui
    python3 -m pytest tests/test_system_default_key_isolation.py -v

Or inside the container after docker cp:

    docker cp backend/open_webui/config.py open-webui:/app/backend/open_webui/config.py
    docker cp backend/open_webui/models/functions.py open-webui:/app/backend/open_webui/models/functions.py
    docker cp backend/open_webui/routers/functions.py open-webui:/app/backend/open_webui/routers/functions.py
    docker cp backend/open_webui/main.py open-webui:/app/backend/open_webui/main.py
    docker cp tests open-webui:/app/tests
    docker compose -f docker-compose.local.yaml exec -e VECTOR_DB=chroma \\
        -e PYTHONPATH=/app/backend -w /app/backend open-webui \\
        python3 -m pytest /app/tests/test_system_default_key_isolation.py -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
RUNNER = Path(__file__).resolve().parent / "_key_isolation_runner.py"


def run_scenario(tmp_path, scenario):
    db_path = tmp_path / "scratch.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND_DIR),
        "VECTOR_DB": "chroma",
        # docker-compose.yaml sets WEBUI_SECRET_KEY='' (empty); env.py raises
        # ValueError when WEBUI_AUTH=True and the key is empty.
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


# ── A: /ensure creates a per-admin function with key in valve ─────────────────

def test_ensure_creates_per_admin_function(tmp_path):
    """/ensure creates a new is_system_default=True function for the admin and
    populates its PORTKEY_API_KEY valve. No key must leak to other rows."""
    data = run_scenario(tmp_path, "ENSURE_CREATES_FUNCTION")
    assert data["has_portkey_key"] is True, "valve must have PORTKEY_API_KEY after ensure"
    assert data["key_in_valve"] is True, "PORTKEY_API_KEY must be non-empty after ensure"
    assert data["is_system_default_count"] == 1, (
        "exactly one is_system_default function per admin"
    )


# ── B: second /ensure call updates valve, no duplicate rows ──────────────────

def test_ensure_updates_valve_without_duplicate(tmp_path):
    """Calling /ensure twice (key rotation) updates the valve in-place rather
    than creating a second system-default function row."""
    data = run_scenario(tmp_path, "ENSURE_UPDATES_VALVE")
    assert data["system_default_count"] == 1, (
        "must still have exactly one system-default function after two ensure calls"
    )
    assert data["valve_key_updated"] is True, (
        "valve must contain the newest key after the second ensure call"
    )


# ── C: admin A cannot see admin B's function via get_functions(user=admin) ────

def test_admin_cannot_see_other_admins_function(tmp_path):
    """RBAC isolation: when get_functions() is called with user.role='admin',
    each admin sees only their own functions. Admin A's per-admin copy must be
    invisible to admin B and vice versa."""
    data = run_scenario(tmp_path, "ADMIN_SEES_OWN_ONLY")
    assert data["a_sees_b_function"] is False, (
        "admin A must not see admin B's system default function"
    )
    assert data["b_sees_a_function"] is False, (
        "admin B must not see admin A's system default function"
    )


# ── D: non-admin user in admin A's group sees admin A's system default ────────

def test_non_admin_user_sees_group_admin_default(tmp_path):
    """A non-admin student in admin A's group must see admin A's system default
    function (so they can use the LLM), but must NOT see admin B's."""
    data = run_scenario(tmp_path, "USER_SEES_GROUP_ADMIN")
    assert data["student_sees_admin_a_default"] is True, (
        "student in admin A's group must see admin A's system default"
    )
    assert data["student_sees_admin_b_default"] is False, (
        "student must not see admin B's system default (different group)"
    )


# ── E: pipe() with no key configured returns actionable error ─────────────────

def test_pipe_returns_error_for_empty_key(tmp_path):
    """pipe() called with an empty PORTKEY_API_KEY valve must return a
    human-readable error string — never raise or attempt an API call."""
    data = run_scenario(tmp_path, "PIPE_NO_KEY_ERROR")
    assert data["is_error_string"] is True, (
        f"expected error string from pipe(), got type={data['result_type']}"
    )


# ── F: pipe() uses valve key directly (zero extra DB queries) ─────────────────

def test_pipe_uses_per_admin_valve_key(tmp_path):
    """CRITICAL RBAC: pipe() reads PORTKEY_API_KEY from self.valves directly
    (the per-admin function row). Admin A and admin B must use their own keys,
    never each other's."""
    data = run_scenario(tmp_path, "PIPE_USES_VALVE_KEY")
    assert data["a_used_own_key"] is True, "admin A's pipe used wrong key"
    assert data["b_used_own_key"] is True, "admin B's pipe used wrong key"
    assert data["keys_are_different"] is True, (
        "admin A and admin B used the same key — RBAC isolation broken"
    )


# ── G: Subcase B adoption does not write key to valve ────────────────────────

def test_subcase_b_adoption_leaves_valve_empty(tmp_path):
    """Subcase B (existing workspace, no Portkey pipe): the system default is
    inserted disabled with an empty valve. PORTKEY_API_KEY is only written when
    the admin saves their Workspace Settings via /ensure — never at startup."""
    data = run_scenario(tmp_path, "SUBCASE_B_NO_VALVE")
    assert data["has_portkey_key_in_valve"] is False, (
        f"PORTKEY_API_KEY must not appear in system default valve after Subcase B, "
        f"got: {data['valve']}"
    )
