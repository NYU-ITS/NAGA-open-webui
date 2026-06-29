"""
Seeds a scratch SQLite DB into one of the Pass-2 starting states (FRESH /
A1 / A2 / B), runs adopt_existing_llm_function() + seed_default_function(),
then dumps the resulting `function` table (and the adoption flag) as JSON.

Run as a subprocess with DATABASE_URL pointing at a fresh sqlite file, e.g.:

    DATABASE_URL=sqlite:////tmp/scratch.db python3 _scenario_runner.py A1

A second positional arg "RERUN" re-invokes adopt+seed a second time in the
same process, to test the one-time gating (idempotency).
"""
import json
import sys

from fastapi import FastAPI

# NYU Portkey gateway URL substring - the detection heuristic in
# _find_portkey_pipe_function() looks for this in a pipe function's content.
GATEWAY_MARKER = "ai-gateway.apps.cloud.rt.nyu.edu"


def seed(scenario):
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

    def make_pipe(id, name, content, is_active, version="0.1"):
        Functions.insert_new_function(
            user_id="admin-id",
            user_email="admin@nyu.edu",
            type="pipe",
            form_data=FunctionForm(
                id=id,
                name=name,
                content=content,
                meta=FunctionMeta(description=name, manifest={"version": version}),
            ),
            is_active=is_active,
        )

    if scenario == "FRESH":
        # Truly new workspace: no functions at all.
        pass

    elif scenario == "A1":
        # Admin already has the Portkey pipe, and it's the active function.
        make_pipe(
            "test_aa12947",
            "Test",
            f'"""\ntitle: Test\nversion: 0.1\n"""\n# {GATEWAY_MARKER}\n',
            is_active=True,
        )
        Functions.update_function_valves_by_id(
            "test_aa12947", {"PORTKEY_API_KEY": "existing-key-123"}
        )

    elif scenario == "A2":
        # Admin has the Portkey pipe, but it's off; another function is active.
        make_pipe(
            "test_aa12947",
            "Test",
            f'"""\ntitle: Test\nversion: 0.1\n"""\n# {GATEWAY_MARKER}\n',
            is_active=False,
        )
        Functions.update_function_valves_by_id(
            "test_aa12947", {"PORTKEY_API_KEY": "existing-key-123"}
        )
        make_pipe(
            "other_pipe",
            "Other",
            '"""\ntitle: Other\nversion: 0.1\n"""\n',
            is_active=True,
        )

    elif scenario == "B":
        # No Portkey pipe exists; some unrelated function is active.
        # Also seed a config row with a workspace Portkey API key.
        make_pipe(
            "other_pipe",
            "Other",
            '"""\ntitle: Other\nversion: 0.1\n"""\n',
            is_active=True,
        )

        from open_webui.config import Config
        from open_webui.internal.db import get_db

        with get_db() as db:
            db.add(
                Config(
                    email="admin@nyu.edu",
                    data={"rag": {"openai_api_key": "workspace-key-456"}},
                    version=0,
                )
            )
            db.commit()

    else:
        raise ValueError(f"Unknown scenario: {scenario}")


def run_adoption():
    from open_webui.main import adopt_existing_llm_function, seed_default_function

    app = FastAPI()
    app.state.FUNCTIONS = {}
    adopt_existing_llm_function(app)
    seed_default_function(app)


def dump():
    from open_webui.config import DEFAULT_FUNCTION_ADOPTION_DONE
    from open_webui.internal.db import get_db
    from open_webui.models.functions import Function, Functions

    with get_db() as db:
        rows = []
        for f in db.query(Function).all():
            rows.append(
                {
                    "id": f.id,
                    "type": f.type,
                    "is_active": f.is_active,
                    "is_system_default": f.is_system_default,
                    "created_by": f.created_by,
                    "version": (f.meta or {}).get("manifest", {}).get("version"),
                    "valves": f.valves,
                }
            )

    # Visibility check: a *different* admin (who didn't create anything)
    # should still see the system-default function via get_functions().
    visible_to_other_user = [
        f.id for f in Functions.get_functions("someone-else@nyu.edu")
    ]

    return {
        "functions": rows,
        "adoption_done": DEFAULT_FUNCTION_ADOPTION_DONE.value,
        "visible_to_other_user": visible_to_other_user,
    }


if __name__ == "__main__":
    scenario = sys.argv[1]
    seed(scenario)
    run_adoption()

    if len(sys.argv) > 2 and sys.argv[2] == "RERUN":
        run_adoption()

    print(json.dumps(dump()))
