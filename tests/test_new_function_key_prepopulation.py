"""
Pass 3 (new function key pre-population) tests.

These run the real _prepopulate_portkey_valves() against a scratch SQLite DB
- no Postgres needed, just `open_webui`'s deps.

Run from the repo root, inside the running container (no rebuild needed -
`docker cp` the updated source files in first if you've made local edits):

    docker cp backend/open_webui/utils/portkey.py open-webui:/app/backend/open_webui/utils/portkey.py
    docker cp backend/open_webui/main.py open-webui:/app/backend/open_webui/main.py
    docker cp backend/open_webui/routers/functions.py open-webui:/app/backend/open_webui/routers/functions.py
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

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
RUNNER = Path(__file__).resolve().parent / "_function_creation_scenario_runner.py"


def run_scenario(tmp_path, scenario):
    db_path = tmp_path / "scratch.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND_DIR),
        # Avoid the global VECTOR_DB=pgvector requiring a Postgres DATABASE_URL.
        "VECTOR_DB": "chroma",
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


def test_key_in_config_prepopulates_valve(tmp_path):
    """Workspace has a Portkey key on record -> new function's
    PORTKEY_API_KEY valve is pre-populated immediately at creation."""
    data = run_scenario(tmp_path, "WITH_KEY")
    assert data["valves"] == {"PORTKEY_API_KEY": "workspace-key-789"}


def test_no_key_in_config_leaves_valve_unset(tmp_path):
    """No Portkey key anywhere in the config table -> new function's valves
    are left exactly as today (empty), no pre-population attempted."""
    data = run_scenario(tmp_path, "NO_KEY_IN_CONFIG")
    assert data["valves"] in ({}, None)


def test_function_without_portkey_valve_is_untouched(tmp_path):
    """A function whose Valves class doesn't declare PORTKEY_API_KEY at all
    is a no-op - no error, no unexpected write."""
    data = run_scenario(tmp_path, "NO_VALVES_FIELD")
    assert data["valves"] in ({}, None)
