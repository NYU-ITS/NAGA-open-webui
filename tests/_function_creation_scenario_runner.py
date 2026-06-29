"""
Seeds a scratch SQLite DB into one of the Pass-3 starting states (WITH_KEY /
NO_KEY_IN_CONFIG / NO_VALVES_FIELD), exercises the same load-module +
insert-row + pre-populate sequence create_new_function() runs (without the
HTTP/FastAPI layer, same level Pass 2's scenarios are tested at), then dumps
the resulting function's valves as JSON.

Run as a subprocess with DATABASE_URL pointing at a fresh sqlite file, e.g.:

    DATABASE_URL=sqlite:////tmp/scratch.db python3 _function_creation_scenario_runner.py WITH_KEY
"""
import json
import sys

TEST_PIPE_WITH_KEY = '''"""
title: Test Pipe With Key
version: 0.1
"""
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        PORTKEY_API_KEY: str = Field(default="")

    def __init__(self):
        self.valves = self.Valves()
'''

TEST_PIPE_NO_KEY_FIELD = '''"""
title: Test Pipe No Key Field
version: 0.1
"""
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        SOME_OTHER_FIELD: str = Field(default="")

    def __init__(self):
        self.valves = self.Valves()
'''


def seed(scenario):
    if scenario in ("WITH_KEY", "NO_VALVES_FIELD"):
        from open_webui.config import Config
        from open_webui.internal.db import get_db

        with get_db() as db:
            db.add(
                Config(
                    email="admin@nyu.edu",
                    data={"rag": {"openai_api_key": "workspace-key-789"}},
                    version=0,
                )
            )
            db.commit()
    elif scenario == "NO_KEY_IN_CONFIG":
        pass  # no config row at all
    else:
        raise ValueError(f"Unknown scenario: {scenario}")


def create_function(scenario):
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.routers.functions import _prepopulate_portkey_valves
    from open_webui.utils.plugin import load_function_module_by_id

    content = (
        TEST_PIPE_NO_KEY_FIELD if scenario == "NO_VALVES_FIELD" else TEST_PIPE_WITH_KEY
    )
    function_id = "test_pass3_function"

    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )

    function = Functions.insert_new_function(
        user_id="admin-id",
        user_email="admin@nyu.edu",
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name="Test Pass 3 Function",
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )

    _prepopulate_portkey_valves(function.id, function_module)
    return function.id


def dump(function_id):
    from open_webui.models.functions import Functions

    return {"valves": Functions.get_function_valves_by_id(function_id)}


if __name__ == "__main__":
    scenario = sys.argv[1]
    seed(scenario)
    function_id = create_function(scenario)
    print(json.dumps(dump(function_id)))
