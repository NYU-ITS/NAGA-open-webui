"""
Pass 2 (existing-workspace adoption) tests.

These run the real adopt_existing_llm_function() / seed_default_function()
against a scratch SQLite DB - no Postgres needed, just `open_webui`'s deps.

Run from the repo root, inside the running container (no rebuild needed -
`docker cp` the updated source files in first if you've made local edits):

    docker cp backend/open_webui/main.py open-webui:/app/backend/open_webui/main.py
    docker cp backend/open_webui/config.py open-webui:/app/backend/open_webui/config.py
    docker cp backend/open_webui/models/functions.py open-webui:/app/backend/open_webui/models/functions.py
    docker cp tests open-webui:/app/tests
    docker compose -f docker-compose.local.yaml exec -e VECTOR_DB=chroma \
        -e PYTHONPATH=/app/backend -w /app/backend open-webui \
        python3 -m pytest /app/tests -v

Or locally, if you have the backend's requirements installed:

    cd dev/NAGA-open-webui
    python3 -m pytest tests -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
RUNNER = Path(__file__).resolve().parent / "_scenario_runner.py"

DEFAULT_SYSTEM_FUNCTION_VERSION = "1.0 [BetaQA]"
DEFAULT_SYSTEM_FUNCTION_ID = "system_default_llm"


def run_scenario(tmp_path, scenario, rerun=False):
    db_path = tmp_path / "scratch.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND_DIR),
        # Avoid the global VECTOR_DB=pgvector requiring a Postgres DATABASE_URL.
        "VECTOR_DB": "chroma",
    }

    args = [sys.executable, str(RUNNER), scenario]
    if rerun:
        args.append("RERUN")

    result = subprocess.run(
        args,
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    # The runner prints exactly one JSON line; ignore any log noise before it.
    last_line = result.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def by_id(functions, id):
    return next(f for f in functions if f["id"] == id)


def test_fresh_workspace_gets_active_default(tmp_path):
    """Case 1: zero functions exist -> single active system_default_llm."""
    data = run_scenario(tmp_path, "FRESH")
    functions = data["functions"]

    assert len(functions) == 1
    f = functions[0]
    assert f["id"] == DEFAULT_SYSTEM_FUNCTION_ID
    assert f["is_active"] is True
    assert f["is_system_default"] is True
    assert f["version"] == DEFAULT_SYSTEM_FUNCTION_VERSION
    assert data["adoption_done"] is True


def test_a1_active_portkey_pipe_adopted_in_place(tmp_path):
    """Subcase A1: existing active Portkey pipe is adopted, no new row."""
    data = run_scenario(tmp_path, "A1")
    functions = data["functions"]

    assert len(functions) == 1
    f = functions[0]
    assert f["id"] == "test_aa12947"
    assert f["is_active"] is True
    assert f["is_system_default"] is True
    assert f["version"] == DEFAULT_SYSTEM_FUNCTION_VERSION
    # Existing API key preserved through the content sync.
    assert f["valves"] == {"PORTKEY_API_KEY": "existing-key-123"}
    assert data["adoption_done"] is True


def test_a2_inactive_portkey_pipe_adopted_other_untouched(tmp_path):
    """Subcase A2: off Portkey pipe is adopted (stays off); other active
    function is left untouched, no new row."""
    data = run_scenario(tmp_path, "A2")
    functions = data["functions"]

    assert len(functions) == 2

    adopted = by_id(functions, "test_aa12947")
    assert adopted["is_active"] is False
    assert adopted["is_system_default"] is True
    assert adopted["version"] == DEFAULT_SYSTEM_FUNCTION_VERSION
    assert adopted["valves"] == {"PORTKEY_API_KEY": "existing-key-123"}

    other = by_id(functions, "other_pipe")
    assert other["is_active"] is True
    assert other["is_system_default"] is False

    assert data["adoption_done"] is True


def test_b_no_portkey_pipe_inserts_disabled_prekeyed(tmp_path):
    """Subcase B: no Portkey pipe -> new disabled system_default_llm,
    pre-keyed from the config table; other active function untouched."""
    data = run_scenario(tmp_path, "B")
    functions = data["functions"]

    assert len(functions) == 2

    inserted = by_id(functions, DEFAULT_SYSTEM_FUNCTION_ID)
    assert inserted["is_active"] is False
    assert inserted["is_system_default"] is True
    assert inserted["version"] == DEFAULT_SYSTEM_FUNCTION_VERSION
    assert inserted["valves"] == {"PORTKEY_API_KEY": "workspace-key-456"}

    other = by_id(functions, "other_pipe")
    assert other["is_active"] is True
    assert other["is_system_default"] is False

    assert data["adoption_done"] is True


def test_adoption_runs_only_once(tmp_path):
    """Re-running adopt+seed in the same process must not create duplicates
    or change the already-adopted state."""
    data = run_scenario(tmp_path, "A1", rerun=True)
    functions = data["functions"]

    assert len(functions) == 1
    f = functions[0]
    assert f["id"] == "test_aa12947"
    assert f["is_system_default"] is True
    assert f["is_active"] is True


@pytest.mark.parametrize("scenario", ["FRESH", "A1", "B"])
def test_system_default_visible_to_other_admins(tmp_path, scenario):
    """The system-default function (created_by="system" for FRESH/B, or an
    adopted admin's function for A1) must be visible to *every* admin via
    get_functions(), not just its creator."""
    data = run_scenario(tmp_path, scenario)
    system_default = next(f for f in data["functions"] if f["is_system_default"])
    assert system_default["id"] in data["visible_to_other_user"]
