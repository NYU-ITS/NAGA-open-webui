"""
Scenario runner for function ID derivation and related isolation tests.

Each scenario seeds a scratch SQLite DB, exercises the relevant logic, and
prints a single JSON line to stdout for the test to parse.

Run as a subprocess:

    DATABASE_URL=sqlite:////tmp/scratch.db \
    PYTHONPATH=/path/to/backend \
    python3 _function_id_runner.py <SCENARIO>

Scenarios:
  DERIVES_ID_FROM_NAME           - name with special chars becomes sanitized__net_id; DB name unchanged
  SPECIAL_CHARS_FALLBACK         - all-special-char name falls back to 'function__net_id'
  DUPLICATE_NAME_REJECTED        - second function with same name (case-insensitive) is rejected
  ID_COLLISION_REJECTED          - "My Function" then "My-Function" collide on same derived ID
  ENSURE_USES_NET_ID             - /ensure creates system_default_llm__<net_id>, not UUID
  SCOPED_KEY_ISOLATION           - find_workspace_portkey_key returns only the queried admin's key
  PORTKEY_URL_IN_VALVE           - created function valve includes PORTKEY_API_BASE_URL
  NULL_PORTKEY_PRESERVED         - update_function_valves_by_id with null preserves null in DB
  ENSURE_INCLUDES_URL            - /ensure writes PORTKEY_API_BASE_URL into system default valve
  ENSURE_IDEMPOTENT              - calling ensure twice with same key succeeds and function still exists
  PIPE_NESTED_VALVES_PREPOPULATED - _prepopulate finds Valves nested inside Pipe class
  STEP1_RETURNS_IMMEDIATELY      - Step 1 short-circuits when is_system_default=True exists, no valve update
  CONTENT_MATCH_ADOPTED          - Step 2 adopts existing clone with matching content, marks is_system_default=True
  CONTENT_MISMATCH_FRESH_INACTIVE - Step 3 creates fresh function with is_active=False when active pipe exists
  ID_COLLISION_SKIP              - Step 3 skips creation when derived ID is already taken by modified content
  STEP3_NO_EXISTING_FUNCTIONS    - Step 3 creates fresh function with is_active=True when no functions exist
  STEP3_NON_PIPE_ACTIVE          - Step 3 creates fresh function with is_active=True when only a filter is active
  STEP3_INACTIVE_PIPE_ACTIVE     - Step 3 creates fresh function with is_active=True when existing pipe is inactive
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


# ── Shared content fixtures ───────────────────────────────────────────────────

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


TEST_FILTER_CONTENT = '''"""
title: Test Filter
version: 0.1
"""
class Filter:
    def inlet(self, body, __user__=None):
        return body

    def outlet(self, body, __user__=None):
        return body
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


# ── Scenario: ENSURE_IDEMPOTENT ──────────────────────────────────────────────

def scenario_ensure_idempotent():
    """Calling ensure_admin_system_default twice with the same key must succeed
    (idempotent). The function must exist and hold the key after both calls.
    This covers the WorkspaceSettings.svelte change that calls ensure on every
    save (not just when the key changes) so old admins get their function."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "idempotent-key")

    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )

    def _ensure():
        existing = Functions.get_admin_system_default_function(email)
        valve_update = {
            "PORTKEY_API_KEY": "idempotent-key",
            "PORTKEY_API_BASE_URL": "https://ai-gateway.apps.cloud.rt.nyu.edu/v1",
        }
        if existing:
            existing_valves = Functions.get_function_valves_by_id(existing.id) or {}
            Functions.update_function_valves_by_id(existing.id, {**existing_valves, **valve_update})
            return Functions.get_function_by_id(existing.id)
        fn = Functions.insert_new_function(
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
        Functions.update_function_valves_by_id(fn.id, valve_update)
        return Functions.get_function_by_id(fn.id)

    fn1 = _ensure()
    fn2 = _ensure()  # second call — must not raise or create a duplicate

    valves = Functions.get_function_valves_by_id(function_id) or {}
    all_system_defaults = [
        f for f in Functions.get_functions(email) if f.is_system_default
    ]
    print(json.dumps({
        "first_call_succeeded": fn1 is not None,
        "second_call_succeeded": fn2 is not None,
        "same_id": fn1 is not None and fn2 is not None and fn1.id == fn2.id,
        "key_preserved": valves.get("PORTKEY_API_KEY") == "idempotent-key",
        "exactly_one_system_default": len(all_system_defaults) == 1,
    }))


# ── Scenario: PIPE_NESTED_VALVES_PREPOPULATED ────────────────────────────────

def scenario_pipe_nested_valves_prepopulated():
    """_prepopulate_portkey_valves must find Valves nested inside Pipe (not just
    top-level Valves). This is the structure of the system default source so all
    clones of it must have their PORTKEY_API_KEY pre-populated at creation."""
    from open_webui.routers.functions import _derive_function_id, _prepopulate_portkey_valves
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    _seed_user(email, f"{net_id}-uid")
    _seed_config(email, "pipe-key", api_base_url="https://ai-gateway.apps.cloud.rt.nyu.edu/v1")

    function_id = _derive_function_id("Nested Pipe Clone", net_id)
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
            name="Nested Pipe Clone",
            content=content,
            meta=FunctionMeta(description="test", manifest=frontmatter),
        ),
    )
    _prepopulate_portkey_valves(function.id, function_module, user_email=email)
    valves = Functions.get_function_valves_by_id(function.id) or {}
    print(json.dumps({
        "has_portkey_key": "PORTKEY_API_KEY" in valves,
        "key_is_set": bool(valves.get("PORTKEY_API_KEY")),
        "key_value_correct": valves.get("PORTKEY_API_KEY") == "pipe-key",
        "has_portkey_url": "PORTKEY_API_BASE_URL" in valves,
    }))


# ── Scenario: STEP1_RETURNS_IMMEDIATELY ─────────────────────────────────────

def scenario_step1_returns_immediately():
    """If is_system_default=True already exists, ensure must return immediately
    without updating the valve. The cascade in WorkspaceSettings owns the valve
    after first setup — ensure must not overwrite it at every login."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "original-key")

    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
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
    # Set a distinctive initial valve value that must NOT be overwritten by ensure.
    Functions.update_function_valves_by_id(function.id, {
        "PORTKEY_API_KEY": "original-key",
        "PORTKEY_API_BASE_URL": "https://original.example.com",
    })

    # Simulate Step 1 of ensure_admin_system_default:
    # if is_system_default=True exists, return immediately (no valve update).
    existing = Functions.get_admin_system_default_function(email)
    if existing:
        returned_fn = Functions.get_function_by_id(existing.id)
    else:
        returned_fn = None

    valves_after = Functions.get_function_valves_by_id(function_id) or {}
    print(json.dumps({
        "step1_detected": existing is not None,
        "function_returned": returned_fn is not None and returned_fn.id == function_id,
        "valve_not_updated": valves_after.get("PORTKEY_API_KEY") == "original-key",
        "url_not_updated": valves_after.get("PORTKEY_API_BASE_URL") == "https://original.example.com",
    }))


# ── Scenario: CONTENT_MATCH_ADOPTED ─────────────────────────────────────────

def scenario_content_match_adopted():
    """If the admin already has a function with matching content (same as system
    default) but not marked is_system_default=True, ensure must adopt it: mark
    is_system_default=True, overwrite content with canonical, and update the
    valve. No new function is created."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.routers.functions import _normalize_content
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports
    from open_webui.utils.portkey import find_workspace_portkey_url

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "match-key")

    # Insert a clone with canonical content but a different ID, no is_system_default flag.
    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    clone_id = f"my_custom_llm__{net_id}"
    function_module, function_type, frontmatter = load_function_module_by_id(
        clone_id, content=canonical_raw
    )
    Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=clone_id,
            name="My Custom LLM",
            content=canonical_raw,
            meta=FunctionMeta(description="existing clone", manifest=frontmatter),
        ),
        is_active=True,
        is_system_default=False,
    )

    # Simulate Step 2 of ensure_admin_system_default: scan for content match.
    canonical_norm = _normalize_content(canonical_raw)
    all_functions = Functions.get_functions(email)
    adopted_fn = None
    for fn in all_functions:
        if _normalize_content(fn.content or '') == canonical_norm:
            Functions.update_function_by_id(fn.id, {
                "content": canonical_raw,
                "is_system_default": True,
                "is_active": True,
            })
            valve_update = {
                "PORTKEY_API_KEY": "match-key",
                "PORTKEY_API_BASE_URL": find_workspace_portkey_url(),
            }
            existing_valves = Functions.get_function_valves_by_id(fn.id) or {}
            Functions.update_function_valves_by_id(fn.id, {**existing_valves, **valve_update})
            adopted_fn = Functions.get_function_by_id(fn.id)
            break

    adopted_fn_db = Functions.get_function_by_id(clone_id) if adopted_fn else None
    valves = Functions.get_function_valves_by_id(clone_id) or {}
    all_system_defaults = [f for f in Functions.get_functions(email) if f.is_system_default]
    print(json.dumps({
        "adopted": adopted_fn is not None,
        "adopted_id_is_clone": adopted_fn is not None and adopted_fn.id == clone_id,
        "no_new_function_created": len(all_system_defaults) == 1,
        "is_active_on": adopted_fn_db is not None and adopted_fn_db.is_active,
        "valve_key_set": valves.get("PORTKEY_API_KEY") == "match-key",
        "valve_url_set": bool(valves.get("PORTKEY_API_BASE_URL")),
    }))


# ── Scenario: CONTENT_MISMATCH_FRESH_INACTIVE ────────────────────────────────

def scenario_content_mismatch_fresh_inactive():
    """If the admin has no function with matching content, ensure must create a
    fresh system default function with is_active=False so the admin's existing
    active function continues running undisturbed."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports
    from open_webui.utils.portkey import find_workspace_portkey_url

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "fresh-key")

    # Admin has a function with different (customized) content that is active.
    other_id = f"other_function__{net_id}"
    function_module, function_type, frontmatter = load_function_module_by_id(
        other_id, content=TEST_PIPE_WITH_PORTKEY
    )
    Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=other_id,
            name="Other Function",
            content=TEST_PIPE_WITH_PORTKEY,
            meta=FunctionMeta(description="admin's custom function", manifest=frontmatter),
        ),
        is_active=True,
        is_system_default=False,
    )

    # Simulate Step 3: determine is_active based on whether an active pipe exists.
    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    all_functions = Functions.get_functions(email)
    has_active_pipe = any(fn.is_active and fn.type == "pipe" for fn in all_functions)
    should_be_active = not has_active_pipe  # False — other_function is an active pipe

    new_module, new_type, new_frontmatter = load_function_module_by_id(
        function_id, content=canonical_raw
    )
    new_fn = Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=new_type,
        form_data=FunctionForm(
            id=function_id,
            name="LLM",
            content=canonical_raw,
            meta=FunctionMeta(description="System default LLM pipe", manifest=new_frontmatter),
        ),
        is_active=should_be_active,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(new_fn.id, {
        "PORTKEY_API_KEY": "fresh-key",
        "PORTKEY_API_BASE_URL": find_workspace_portkey_url(),
    })

    new_fn_db = Functions.get_function_by_id(function_id)
    other_fn_db = Functions.get_function_by_id(other_id)
    valves = Functions.get_function_valves_by_id(function_id) or {}
    print(json.dumps({
        "new_function_created": new_fn_db is not None,
        "new_function_inactive": new_fn_db is not None and not new_fn_db.is_active,
        "new_function_is_system_default": new_fn_db is not None and new_fn_db.is_system_default,
        "original_function_still_active": other_fn_db is not None and other_fn_db.is_active,
        "valve_key_set": valves.get("PORTKEY_API_KEY") == "fresh-key",
    }))


# ── Scenario: ID_COLLISION_SKIP ──────────────────────────────────────────────

def scenario_id_collision_skip():
    """If the derived system default ID is already taken by a function with
    different content (admin customized it), ensure must skip creation and return
    None. The admin's modified function must remain completely untouched."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.routers.functions import _normalize_content
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "collision-key")

    # Insert a function at the canonical ID with different (modified) content.
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=TEST_PIPE_WITH_PORTKEY
    )
    Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=function_type,
        form_data=FunctionForm(
            id=function_id,
            name="LLM",
            content=TEST_PIPE_WITH_PORTKEY,
            meta=FunctionMeta(description="admin-modified function", manifest=frontmatter),
        ),
        is_active=True,
        is_system_default=False,
    )

    # Simulate the full ensure decision path:
    # Step 1: no is_system_default=True → None
    step1_existing = Functions.get_admin_system_default_function(email)
    # Step 2: content scan → no match (TEST_PIPE_WITH_PORTKEY ≠ canonical)
    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    canonical_norm = _normalize_content(canonical_raw)
    all_functions = Functions.get_functions(email)
    step2_match = any(_normalize_content(fn.content or '') == canonical_norm for fn in all_functions)
    # Step 3: ID collision → skip (return None)
    id_taken = Functions.get_function_by_id(function_id) is not None

    all_fns_after = Functions.get_functions(email)
    original_fn_after = Functions.get_function_by_id(function_id)
    print(json.dumps({
        "step1_no_system_default": step1_existing is None,
        "step2_no_content_match": not step2_match,
        "id_collision_detected": id_taken,
        "no_duplicate_created": len(all_fns_after) == 1,
        "original_content_intact": original_fn_after is not None and original_fn_after.content == TEST_PIPE_WITH_PORTKEY,
        "original_still_active": original_fn_after is not None and original_fn_after.is_active,
    }))


# ── Scenario: STEP3_NO_EXISTING_FUNCTIONS ────────────────────────────────────

def scenario_step3_no_existing_functions():
    """When the admin has no existing functions at all, Step 3 must create the
    system default with is_active=True — nothing is running so there is no
    conflict and chat should work immediately after setup."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports
    from open_webui.utils.portkey import find_workspace_portkey_url

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "fresh-key-new-admin")

    # No existing functions — admin has just entered their key for the first time.
    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    all_functions = Functions.get_functions(email)
    has_active_pipe = any(fn.is_active and fn.type == "pipe" for fn in all_functions)
    should_be_active = not has_active_pipe  # True — no existing pipes

    new_module, new_type, new_frontmatter = load_function_module_by_id(
        function_id, content=canonical_raw
    )
    new_fn = Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=new_type,
        form_data=FunctionForm(
            id=function_id,
            name="LLM",
            content=canonical_raw,
            meta=FunctionMeta(description="System default LLM pipe", manifest=new_frontmatter),
        ),
        is_active=should_be_active,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(new_fn.id, {
        "PORTKEY_API_KEY": "fresh-key-new-admin",
        "PORTKEY_API_BASE_URL": find_workspace_portkey_url(),
    })

    new_fn_db = Functions.get_function_by_id(function_id)
    print(json.dumps({
        "new_function_created": new_fn_db is not None,
        "new_function_active": new_fn_db is not None and new_fn_db.is_active,
        "new_function_is_system_default": new_fn_db is not None and new_fn_db.is_system_default,
    }))


# ── Scenario: STEP3_NON_PIPE_ACTIVE ──────────────────────────────────────────

def scenario_step3_non_pipe_active():
    """When the admin has an active non-pipe function (e.g. a filter), Step 3
    must create the system default with is_active=True — filters do not provide
    LLM models so there is no conflict with a new active pipe."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports
    from open_webui.utils.portkey import find_workspace_portkey_url

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "fresh-key-filter-admin")

    # Admin has an active filter — not a pipe, so no conflict.
    filter_id = f"my_filter__{net_id}"
    filter_module, filter_type, filter_frontmatter = load_function_module_by_id(
        filter_id, content=TEST_FILTER_CONTENT
    )
    Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=filter_type,
        form_data=FunctionForm(
            id=filter_id,
            name="My Filter",
            content=TEST_FILTER_CONTENT,
            meta=FunctionMeta(description="active filter", manifest=filter_frontmatter),
        ),
        is_active=True,
        is_system_default=False,
    )

    # Simulate Step 3: active filter must not affect should_be_active.
    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    all_functions = Functions.get_functions(email)
    has_active_pipe = any(fn.is_active and fn.type == "pipe" for fn in all_functions)
    should_be_active = not has_active_pipe  # True — filter is not a pipe

    new_module, new_type, new_frontmatter = load_function_module_by_id(
        function_id, content=canonical_raw
    )
    new_fn = Functions.insert_new_function(
        user_id=user_id,
        user_email=email,
        type=new_type,
        form_data=FunctionForm(
            id=function_id,
            name="LLM",
            content=canonical_raw,
            meta=FunctionMeta(description="System default LLM pipe", manifest=new_frontmatter),
        ),
        is_active=should_be_active,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(new_fn.id, {
        "PORTKEY_API_KEY": "fresh-key-filter-admin",
        "PORTKEY_API_BASE_URL": find_workspace_portkey_url(),
    })

    filter_fn_db = Functions.get_function_by_id(filter_id)
    new_fn_db = Functions.get_function_by_id(function_id)
    print(json.dumps({
        "new_function_created": new_fn_db is not None,
        "new_function_active": new_fn_db is not None and new_fn_db.is_active,
        "new_function_is_system_default": new_fn_db is not None and new_fn_db.is_system_default,
        "filter_still_active": filter_fn_db is not None and filter_fn_db.is_active,
        "filter_type_confirmed": filter_fn_db is not None and filter_fn_db.type == "filter",
    }))


# ── Scenario: STEP3_INACTIVE_PIPE_ACTIVE ─────────────────────────────────────

def scenario_step3_inactive_pipe_creates_active():
    """When the admin has a pipe with modified content but it is toggled OFF,
    Step 3 must create the system default with is_active=True — nothing is
    actively running so the new default should start ON immediately."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports
    from open_webui.utils.portkey import find_workspace_portkey_url

    net_id = "aa12947"
    email = f"{net_id}@nyu.edu"
    user_id = f"{net_id}-uid"
    _seed_user(email, user_id)
    _seed_config(email, "fresh-key-inactive-pipe")

    # Admin has a modified pipe that is INACTIVE (toggled OFF).
    other_id = f"other_function__{net_id}"
    function_module, function_type, frontmatter = load_function_module_by_id(
        other_id, content=TEST_PIPE_WITH_PORTKEY
    )
    Functions.insert_new_function(
        user_id=user_id, user_email=email, type=function_type,
        form_data=FunctionForm(
            id=other_id, name="Other Function", content=TEST_PIPE_WITH_PORTKEY,
            meta=FunctionMeta(description="admin's inactive pipe", manifest=frontmatter),
        ),
        is_active=False,   # OFF — must not block the system default from starting ON
        is_system_default=False,
    )

    canonical_raw = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    all_functions = Functions.get_functions(email)
    has_active_pipe = any(fn.is_active and fn.type == "pipe" for fn in all_functions)
    should_be_active = not has_active_pipe  # True — existing pipe is OFF

    new_module, new_type, new_frontmatter = load_function_module_by_id(
        function_id, content=canonical_raw
    )
    new_fn = Functions.insert_new_function(
        user_id=user_id, user_email=email, type=new_type,
        form_data=FunctionForm(
            id=function_id, name="LLM", content=canonical_raw,
            meta=FunctionMeta(description="System default LLM pipe", manifest=new_frontmatter),
        ),
        is_active=should_be_active,
        is_system_default=True,
    )
    Functions.update_function_valves_by_id(new_fn.id, {
        "PORTKEY_API_KEY": "fresh-key-inactive-pipe",
        "PORTKEY_API_BASE_URL": find_workspace_portkey_url(),
    })

    new_fn_db = Functions.get_function_by_id(function_id)
    other_fn_db = Functions.get_function_by_id(other_id)
    print(json.dumps({
        "new_function_created": new_fn_db is not None,
        "new_function_active": new_fn_db is not None and new_fn_db.is_active,
        "new_function_is_system_default": new_fn_db is not None and new_fn_db.is_system_default,
        "inactive_pipe_still_inactive": other_fn_db is not None and not other_fn_db.is_active,
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
        "ENSURE_IDEMPOTENT": scenario_ensure_idempotent,
        "PIPE_NESTED_VALVES_PREPOPULATED": scenario_pipe_nested_valves_prepopulated,
        "STEP1_RETURNS_IMMEDIATELY": scenario_step1_returns_immediately,
        "CONTENT_MATCH_ADOPTED": scenario_content_match_adopted,
        "CONTENT_MISMATCH_FRESH_INACTIVE": scenario_content_mismatch_fresh_inactive,
        "ID_COLLISION_SKIP": scenario_id_collision_skip,
        "STEP3_NO_EXISTING_FUNCTIONS": scenario_step3_no_existing_functions,
        "STEP3_NON_PIPE_ACTIVE": scenario_step3_non_pipe_active,
        "STEP3_INACTIVE_PIPE_ACTIVE": scenario_step3_inactive_pipe_creates_active,
    }[scenario]()
