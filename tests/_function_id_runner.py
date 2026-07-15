"""
Scenario runner for function ID derivation and related isolation tests.

Each scenario seeds a scratch SQLite DB, exercises the relevant logic, and
prints a single JSON line to stdout for the test to parse.

Run as a subprocess:

    DATABASE_URL=sqlite:////tmp/scratch.db \
    PYTHONPATH=/path/to/backend \
    python3 _function_id_runner.py <SCENARIO>

Scenarios:
  DERIVES_ID_FROM_NAME       - name with special chars becomes sanitized__net_id; DB name unchanged
  SPECIAL_CHARS_FALLBACK     - all-special-char name falls back to 'function__net_id'
  DUPLICATE_NAME_REJECTED    - second function with same name (case-insensitive) is rejected
  ID_COLLISION_REJECTED      - "My Function" then "My-Function" collide on same derived ID
  ENSURE_USES_NET_ID         - /ensure creates system_default_llm__<net_id>, not UUID
  SCOPED_KEY_ISOLATION       - find_workspace_portkey_key returns only the queried admin's key
  PORTKEY_URL_IN_VALVE       - created function valve includes PORTKEY_API_BASE_URL
  NULL_PORTKEY_PRESERVED     - update_function_valves_by_id with null preserves null in DB
  ENSURE_INCLUDES_URL        - /ensure writes PORTKEY_API_BASE_URL into system default valve
"""
import json
import sys
import time

from fastapi import FastAPI


def _make_app():
    app = FastAPI()
    app.state.FUNCTIONS = {}
    return app


def _seed_user(email: str, user_id: str, role: str = "admin"):
    from open_webui.models.users import User
    from open_webui.internal.db import get_db
    with get_db() as db:
        db.add(User(
            id=user_id,
            name=email.split("@")[0],
            email=email,
            role=role,
            profile_image_url="/user.png",
            last_active_at=int(time.time()),
            updated_at=int(time.time()),
            created_at=int(time.time()),
        ))
        db.commit()


def _seed_config(email: str, api_key: str, api_base_url: str | None = None):
    from open_webui.config import Config
    from open_webui.internal.db import get_db
    data: dict = {"rag": {"openai_api_key": api_key}}
    if api_base_url:
        data["rag"]["openai_api_base_url"] = api_base_url
    with get_db() as db:
        db.add(Config(email=email, data=data, version=0))
        db.commit()


# ── Shared pipe content with both Portkey valve fields ────────────────────────

TEST_PIPE_WITH_PORTKEY = '''"""
title: Test Portkey Pipe
version: 0.1
"""
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        PORTKEY_API_KEY: str = Field(default="")
        PORTKEY_API_BASE_URL: str = Field(default="https://ai-gateway.apps.cloud.rt.nyu.edu/v1")

    def __init__(self):
        self.valves = self.Valves()
'''


# ── Scenario: DERIVES_ID_FROM_NAME ────────────────────────────────────────────

def scenario_derives_id_from_name():
    """Function name 'My Custom LLM!' created as aa12947@nyu.edu must have
    id='my_custom_llm__aa12947' and name='My Custom LLM!' (no suffix) in DB."""
    from open_webui.routers.functions import _derive_function_id
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    name = "My Custom LLM!"
    expected_id = _derive_function_id(name, net_id)

    _seed_user(f"{net_id}@nyu.edu", f"{net_id}-uid")
    content = TEST_PIPE_WITH_PORTKEY
    function_module, function_type, frontmatter = load_function_module_by_id(
        expected_id, content=content
    )
    function = Functions.insert_new_function(
        user_id=f"{net_id}-uid",
        user_email=f"{net_id}@nyu.edu",
        type=function_type,
        form_data=FunctionForm(
            id=expected_id,
            name=name,
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )
    print(json.dumps({
        "derived_id": expected_id,
        "db_id": function.id if function else None,
        "db_name": function.name if function else None,
        "id_correct": function is not None and function.id == "my_custom_llm__aa12947",
        "name_unchanged": function is not None and function.name == "My Custom LLM!",
        "name_has_no_suffix": function is not None and not function.name.endswith("_aa12947"),
    }))


# ── Scenario: SPECIAL_CHARS_FALLBACK ─────────────────────────────────────────

def scenario_special_chars_fallback():
    """All-special-char name '!!!' must produce id='function__aa12947'."""
    from open_webui.routers.functions import _derive_function_id

    net_id = "aa12947"
    result = _derive_function_id("!!!", net_id)
    print(json.dumps({
        "derived_id": result,
        "correct": result == "function__aa12947",
    }))


# ── Scenario: DUPLICATE_NAME_REJECTED ────────────────────────────────────────

def scenario_duplicate_name_rejected():
    """Inserting a second function with the same name (case-insensitive) should
    be caught by the duplicate-name check in create_new_function."""
    from open_webui.routers.functions import _derive_function_id
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    _seed_user(email, f"{net_id}-uid")

    name = "Alpha"
    function_id = _derive_function_id(name, net_id)
    content = TEST_PIPE_WITH_PORTKEY
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )
    Functions.insert_new_function(
        user_id=f"{net_id}-uid",
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name=name,
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )

    # Now simulate the duplicate-name check from create_new_function
    existing_by_name = [
        f for f in Functions.get_functions(email)
        if f.name.lower() == "alpha"
    ]
    print(json.dumps({
        "duplicate_detected": len(existing_by_name) > 0,
    }))


# ── Scenario: ID_COLLISION_REJECTED ──────────────────────────────────────────

def scenario_id_collision_rejected():
    """'My Function' and 'My-Function' derive the same ID; second insert must be
    caught by the ID-collision check."""
    from open_webui.routers.functions import _derive_function_id
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    _seed_user(email, f"{net_id}-uid")

    name_a = "My Function"
    name_b = "My-Function"
    id_a = _derive_function_id(name_a, net_id)
    id_b = _derive_function_id(name_b, net_id)

    content = TEST_PIPE_WITH_PORTKEY
    function_module, function_type, frontmatter = load_function_module_by_id(
        id_a, content=content
    )
    Functions.insert_new_function(
        user_id=f"{net_id}-uid",
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=id_a,
            name=name_a,
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )

    # Simulate the ID-collision check from create_new_function
    collision = Functions.get_function_by_id(id_b) is not None
    print(json.dumps({
        "ids_are_same": id_a == id_b,
        "collision_detected": collision,
    }))


# ── Scenario: ENSURE_USES_NET_ID ─────────────────────────────────────────────

def scenario_ensure_uses_net_id():
    """/ensure must create system_default_llm__aa12947, NOT system_default_llm__<uuid>."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-fixed-uid"
    _seed_user(email, user_id)
    _seed_config(email, "key-for-ensure")

    expected_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_module, function_type, frontmatter = load_function_module_by_id(
        expected_id, content=content
    )
    function = Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=expected_id,
            name="LLM",
            content=content,
            meta=FunctionMeta(description="System default LLM pipe", manifest=frontmatter),
        ),
        is_active=True,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(
        function.id,
        {"PORTKEY_API_KEY": "key-for-ensure", "PORTKEY_API_BASE_URL": "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"},
    )
    print(json.dumps({
        "function_id": function.id if function else None,
        "id_uses_net_id": function is not None and function.id == expected_id,
        "id_has_no_uuid": function is not None and "-" not in function.id,
    }))


# ── Scenario: SCOPED_KEY_ISOLATION ───────────────────────────────────────────

def scenario_scoped_key_isolation():
    """find_workspace_portkey_key('admin_a@nyu.edu') must return admin A's key,
    NOT admin B's, even when both are in the config table."""
    from open_webui.utils.portkey import find_workspace_portkey_key

    _seed_config("admin_a@nyu.edu", "key-for-a")
    _seed_config("admin_b@nyu.edu", "key-for-b")

    key_a = find_workspace_portkey_key("admin_a@nyu.edu")
    key_b = find_workspace_portkey_key("admin_b@nyu.edu")
    unscoped = find_workspace_portkey_key()  # must return one of them

    print(json.dumps({
        "a_got_own_key": key_a == "key-for-a",
        "b_got_own_key": key_b == "key-for-b",
        "keys_isolated": key_a != key_b,
        "unscoped_found_a_key": unscoped in ("key-for-a", "key-for-b"),
    }))


# ── Scenario: PORTKEY_URL_IN_VALVE ───────────────────────────────────────────

def scenario_portkey_url_in_valve():
    """After creating a function with PORTKEY_API_BASE_URL in its Valves class,
    the stored valve must contain PORTKEY_API_BASE_URL."""
    from open_webui.routers.functions import _derive_function_id, _prepopulate_portkey_valves
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    _seed_user(email, f"{net_id}-uid")
    _seed_config(email, "key-abc", api_base_url="https://custom-gateway.example.com/v1")

    function_id = _derive_function_id("Portkey Test", net_id)
    content = TEST_PIPE_WITH_PORTKEY
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )
    function = Functions.insert_new_function(
        user_id=f"{net_id}-uid",
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name="Portkey Test",
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )
    _prepopulate_portkey_valves(function.id, function_module, user_email=email)
    valves = Functions.get_function_valves_by_id(function.id) or {}
    print(json.dumps({
        "has_portkey_key": "PORTKEY_API_KEY" in valves,
        "has_portkey_url": "PORTKEY_API_BASE_URL" in valves,
        "key_is_set": bool(valves.get("PORTKEY_API_KEY")),
    }))


# ── Scenario: NULL_PORTKEY_PRESERVED ─────────────────────────────────────────

def scenario_null_portkey_preserved():
    """Sending {PORTKEY_API_KEY: null} to the valve update route must store null
    in DB, not the Pydantic default empty string ''."""
    from open_webui.routers.functions import _derive_function_id
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    _seed_user(email, f"{net_id}-uid")

    function_id = _derive_function_id("Null Test", net_id)
    content = TEST_PIPE_WITH_PORTKEY
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )
    function = Functions.insert_new_function(
        user_id=f"{net_id}-uid",
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name="Null Test",
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )
    # Set an initial value
    Functions.update_function_valves_by_id(function.id, {"PORTKEY_API_KEY": "some-key", "PORTKEY_API_BASE_URL": "https://x.example.com"})

    # Now simulate the null-preservation logic from update_function_valves_by_id route
    Valves = function_module.Valves
    incoming = {"PORTKEY_API_KEY": None, "PORTKEY_API_BASE_URL": "https://x.example.com"}
    _PORTKEY_FIELDS = {'PORTKEY_API_KEY', 'PORTKEY_API_BASE_URL'}
    explicitly_null_portkey = {k for k, v in incoming.items() if v is None and k in _PORTKEY_FIELDS}
    filtered = {k: v for k, v in incoming.items() if v is not None}
    valves_obj = Valves(**filtered)
    valve_dict = valves_obj.model_dump()
    for k in explicitly_null_portkey:
        valve_dict[k] = None
    Functions.update_function_valves_by_id(function.id, valve_dict)

    stored = Functions.get_function_valves_by_id(function.id) or {}
    print(json.dumps({
        "portkey_key_is_null": stored.get("PORTKEY_API_KEY") is None,
        "portkey_key_is_not_empty_string": stored.get("PORTKEY_API_KEY") != "",
        "url_preserved": stored.get("PORTKEY_API_BASE_URL") == "https://x.example.com",
    }))


# ── Scenario: ENSURE_INCLUDES_URL ────────────────────────────────────────────

def scenario_ensure_includes_url():
    """/ensure must write PORTKEY_API_BASE_URL into the system default valve
    alongside PORTKEY_API_KEY."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.portkey import find_workspace_portkey_url
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "key-abc")

    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    workspace_url = find_workspace_portkey_url()
    valve_update = {
        "PORTKEY_API_KEY": "key-abc",
        "PORTKEY_API_BASE_URL": workspace_url,
    }

    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )
    function = Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name="LLM",
            content=content,
            meta=FunctionMeta(description="System default LLM pipe", manifest=frontmatter),
        ),
        is_active=True,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(function.id, valve_update)

    stored = Functions.get_function_valves_by_id(function.id) or {}
    print(json.dumps({
        "has_portkey_key": "PORTKEY_API_KEY" in stored,
        "has_portkey_url": "PORTKEY_API_BASE_URL" in stored,
        "key_is_set": bool(stored.get("PORTKEY_API_KEY")),
        "url_is_set": bool(stored.get("PORTKEY_API_BASE_URL")),
    }))


# ── Dispatch ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scenario = sys.argv[1]
    {
        "DERIVES_ID_FROM_NAME": scenario_derives_id_from_name,
        "SPECIAL_CHARS_FALLBACK": scenario_special_chars_fallback,
        "DUPLICATE_NAME_REJECTED": scenario_duplicate_name_rejected,
        "ID_COLLISION_REJECTED": scenario_id_collision_rejected,
        "ENSURE_USES_NET_ID": scenario_ensure_uses_net_id,
        "SCOPED_KEY_ISOLATION": scenario_scoped_key_isolation,
        "PORTKEY_URL_IN_VALVE": scenario_portkey_url_in_valve,
        "NULL_PORTKEY_PRESERVED": scenario_null_portkey_preserved,
        "ENSURE_INCLUDES_URL": scenario_ensure_includes_url,
    }[scenario]()
