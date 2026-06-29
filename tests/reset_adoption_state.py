"""
Resets the one-time Pass-2 adoption state on the *live* DB so you can
re-trigger adopt_existing_llm_function() on the next container restart,
without touching any of your real functions.

What it does:
  - Deletes the `system_default_llm` row, if present (the Subcase-B / Case-1
    inserted row).
  - Clears `is_system_default` on any other row (e.g. an A1/A2-adopted
    function), restoring it to its pre-adoption state.
  - Sets `function.default_adoption_done` back to False in the config table.

Run inside the container:

    docker compose -f docker-compose.local.yaml exec -w /app/backend open-webui \
        python3 /app/tests/reset_adoption_state.py

Then `docker compose -f docker-compose.local.yaml restart open-webui` and
refresh the UI.
"""
from sqlalchemy.orm.attributes import flag_modified

from open_webui.config import Config
from open_webui.internal.db import get_db
from open_webui.models.functions import Function

with get_db() as db:
    deleted = db.query(Function).filter_by(id="system_default_llm").delete()

    adopted = (
        db.query(Function)
        .filter(Function.is_system_default == True, Function.id != "system_default_llm")
        .all()
    )
    for f in adopted:
        f.is_system_default = False

    entry = db.query(Config).filter_by(email="system@default").first()
    if entry and isinstance(entry.data, dict) and "function" in entry.data:
        entry.data["function"]["default_adoption_done"] = False
        flag_modified(entry, "data")

    db.commit()

print(f"Deleted system_default_llm rows: {deleted}")
print(f"Cleared is_system_default on: {[f.id for f in adopted]}")
print("default_adoption_done reset to False")
