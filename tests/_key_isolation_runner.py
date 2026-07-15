"""
Scenario runner for per-admin system default function key isolation tests.

Each scenario seeds a scratch SQLite DB, exercises the relevant code path,
and prints a single JSON line to stdout for the test to parse.

Scenarios:
  ENSURE_CREATES_FUNCTION  - first-time /ensure call creates per-admin function with key in valve
  ENSURE_UPDATES_VALVE     - second /ensure call updates valve without creating a duplicate
  ADMIN_SEES_OWN_ONLY      - admin A cannot see admin B's system default via get_functions()
  USER_SEES_GROUP_ADMIN    - non-admin user in admin A's group sees admin A's system default
  PIPE_NO_KEY_ERROR        - pipe() with empty valve returns error string
  PIPE_USES_VALVE_KEY      - pipe() reads key directly from self.valves (zero extra DB queries)
  SUBCASE_B_NO_VALVE       - Subcase B adoption inserts function with no PORTKEY_API_KEY in valve
"""
import json
import sys
import time

from fastapi import FastAPI


def _make_app():
    app = FastAPI()
    app.state.FUNCTIONS = {}
    return app


# ── Shared helpers ────────────────────────────────────────────────────────────

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


def _seed_group(group_id: str, name: str, created_by: str, member_ids: list):
    """Seed a group with the given admin (created_by) and member IDs."""
    from open_webui.internal.db import get_db
    from open_webui.models.groups import Group
    with get_db() as db:
        db.add(Group(
            id=group_id,
            name=name,
            description="test group",
            user_id=created_by,
            created_by=created_by,
            user_ids=member_ids,
            permissions={},
            updated_at=int(time.time()),
            created_at=int(time.time()),
        ))
        db.commit()


def _valve_of(function_id: str) -> dict:
    from open_webui.models.functions import Functions
    return Functions.get_function_valves_by_id(function_id) or {}


def _simulate_ensure(user_email: str, user_id: str, api_key: str) -> dict | None:
    """Simulate what POST /functions/system-default/ensure does (model-layer only)."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    existing = Functions.get_admin_system_default_function(user_email)
    if existing:
        Functions.update_function_valves_by_id(existing.id, {"PORTKEY_API_KEY": api_key})
        return Functions.get_function_by_id(existing.id)

    if not api_key:
        return None

    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{user_id}"
    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    function_module, function_type, frontmatter = load_function_module_by_id(
        function_id, content=content
    )

    function = Functions.insert_new_function(
        user_id=user_id,
        user_email=user_email,
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
    if function:
        Functions.update_function_valves_by_id(function.id, {"PORTKEY_API_KEY": api_key})
    return function


# ── Scenario: ENSURE_CREATES_FUNCTION ────────────────────────────────────────

def scenario_ensure_creates_function():
    """First-time ensure call for admin A creates a per-admin system default
    function with PORTKEY_API_KEY in its valve."""
    fn = _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-for-admin-a")
    valve = _valve_of(fn.id if fn else "system_default_llm__admin-a-id")
    from open_webui.models.functions import Functions
    all_fns = [f for f in Functions.get_functions("admin_a@nyu.edu") if f.is_system_default]
    print(json.dumps({
        "function_id": fn.id if fn else None,
        "has_portkey_key": "PORTKEY_API_KEY" in valve,
        "key_in_valve": bool(valve.get("PORTKEY_API_KEY")),
        "is_system_default_count": len(all_fns),
    }))


# ── Scenario: ENSURE_UPDATES_VALVE ───────────────────────────────────────────

def scenario_ensure_updates_valve():
    """Second ensure call updates the valve rather than creating a duplicate."""
    _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-v1")
    _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-v2")

    from open_webui.models.functions import Functions
    system_defaults = [
        f for f in Functions.get_functions("admin_a@nyu.edu") if f.is_system_default
    ]
    valve = _valve_of(system_defaults[0].id) if system_defaults else {}
    print(json.dumps({
        "system_default_count": len(system_defaults),
        "valve_key_updated": valve.get("PORTKEY_API_KEY") == "key-v2",
    }))


# ── Scenario: ADMIN_SEES_OWN_ONLY ─────────────────────────────────────────────

def scenario_admin_sees_own_only():
    """Admin A must NOT see admin B's system default in their own get_functions()
    result — each admin's per-admin copy is invisible to other admins through
    the route (user.role == 'admin' path)."""
    _seed_user("admin_a@nyu.edu", "admin-a-id", role="admin")
    _seed_user("admin_b@nyu.edu", "admin-b-id", role="admin")
    _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-for-admin-a")
    _simulate_ensure("admin_b@nyu.edu", "admin-b-id", "key-for-admin-b")

    from open_webui.models.functions import Functions

    class FakeUser:
        def __init__(self, email, user_id, role):
            self.email = email
            self.id = user_id
            self.role = role

    user_a = FakeUser("admin_a@nyu.edu", "admin-a-id", "admin")
    user_b = FakeUser("admin_b@nyu.edu", "admin-b-id", "admin")

    fns_a = [f.id for f in Functions.get_functions("admin_a@nyu.edu", user=user_a)]
    fns_b = [f.id for f in Functions.get_functions("admin_b@nyu.edu", user=user_b)]

    print(json.dumps({
        "a_sees_b_function": any("admin-b-id" in fid for fid in fns_a),
        "b_sees_a_function": any("admin-a-id" in fid for fid in fns_b),
        "a_function_ids": fns_a,
        "b_function_ids": fns_b,
    }))


# ── Scenario: USER_SEES_GROUP_ADMIN ──────────────────────────────────────────

def scenario_user_sees_group_admin():
    """A non-admin user in admin A's group can see admin A's system default
    via get_functions(user=non_admin_user), but not admin B's."""
    _seed_user("admin_a@nyu.edu", "admin-a-id", role="admin")
    _seed_user("admin_b@nyu.edu", "admin-b-id", role="admin")
    _seed_user("student@nyu.edu", "student-id", role="user")
    _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-for-admin-a")
    _simulate_ensure("admin_b@nyu.edu", "admin-b-id", "key-for-admin-b")
    _seed_group("group-1", "Admin A Group", "admin_a@nyu.edu", ["student-id"])

    from open_webui.models.functions import Functions

    class FakeUser:
        def __init__(self, email, user_id, role):
            self.email = email
            self.id = user_id
            self.role = role

    student = FakeUser("student@nyu.edu", "student-id", "user")
    fns = [f.id for f in Functions.get_functions("student@nyu.edu", user=student)]

    print(json.dumps({
        "student_sees_admin_a_default": any("admin-a-id" in fid for fid in fns),
        "student_sees_admin_b_default": any("admin-b-id" in fid for fid in fns),
        "visible_function_ids": fns,
    }))


# ── Scenario: PIPE_NO_KEY_ERROR ───────────────────────────────────────────────

def scenario_pipe_no_key_error():
    """pipe() with an empty PORTKEY_API_KEY valve must return a human-readable
    error string, not raise or attempt an API call."""
    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    pipe_instance, _, _ = load_function_module_by_id("system_default_llm", content=content)
    # valve defaults to empty string
    result = pipe_instance.pipe(
        body={"model": "system_default_llm.test", "messages": [], "stream": False},
        __user__={"email": "admin@nyu.edu", "name": "Admin", "id": "admin-id"},
    )
    print(json.dumps({
        "is_error_string": isinstance(result, str) and "Error" in result,
        "result_type": type(result).__name__,
    }))


# ── Scenario: PIPE_USES_VALVE_KEY ────────────────────────────────────────────

def scenario_pipe_uses_valve_key():
    """pipe() reads PORTKEY_API_KEY directly from self.valves (the per-admin
    function row's valve). Two admin functions with different keys must never
    use each other's key — no cross-admin contamination."""
    import unittest.mock as mock

    _simulate_ensure("admin_a@nyu.edu", "admin-a-id", "key-for-admin-a")
    _simulate_ensure("admin_b@nyu.edu", "admin-b-id", "key-for-admin-b")

    from open_webui.config import DEFAULT_SYSTEM_FUNCTION_CONTENT, DEFAULT_SYSTEM_FUNCTION_ID
    from open_webui.models.functions import Functions
    from open_webui.utils.plugin import load_function_module_by_id, replace_imports

    content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
    captured = {}

    def fake_post(url, json=None, headers=None, stream=False, **kw):
        captured["last_key"] = (headers or {}).get("x-portkey-api-key", "")
        resp = mock.MagicMock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        return resp

    fn_a = Functions.get_admin_system_default_function("admin_a@nyu.edu")
    fn_b = Functions.get_admin_system_default_function("admin_b@nyu.edu")

    with mock.patch("requests.post", side_effect=fake_post):
        # Load admin A's function and call pipe()
        pipe_a, _, _ = load_function_module_by_id(fn_a.id, content=content)
        # Manually set valve from DB (mirrors what OpenWebUI's pipeline does)
        pipe_a.valves.PORTKEY_API_KEY = _valve_of(fn_a.id).get("PORTKEY_API_KEY", "")
        pipe_a.pipe(
            body={"model": f"{fn_a.id}.test", "messages": [], "stream": False},
            __user__={"email": "admin_a@nyu.edu", "name": "A", "id": "admin-a-id"},
        )
        key_used_for_a = captured.get("last_key", "")

        # Load admin B's function and call pipe()
        pipe_b, _, _ = load_function_module_by_id(fn_b.id, content=content)
        pipe_b.valves.PORTKEY_API_KEY = _valve_of(fn_b.id).get("PORTKEY_API_KEY", "")
        pipe_b.pipe(
            body={"model": f"{fn_b.id}.test", "messages": [], "stream": False},
            __user__={"email": "admin_b@nyu.edu", "name": "B", "id": "admin-b-id"},
        )
        key_used_for_b = captured.get("last_key", "")

    print(json.dumps({
        "a_used_own_key": key_used_for_a == "key-for-admin-a",
        "b_used_own_key": key_used_for_b == "key-for-admin-b",
        "keys_are_different": key_used_for_a != key_used_for_b,
    }))


# ── Scenario: SUBCASE_B_NO_VALVE ─────────────────────────────────────────────

def scenario_subcase_b_no_valve():
    """Subcase B adoption must not write PORTKEY_API_KEY into the system default
    valve. The key is written only by /ensure when the admin saves Workspace Settings."""
    from open_webui.config import Config
    from open_webui.internal.db import get_db
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

    # Seed a non-Portkey function and a workspace config key (like Subcase B scenario)
    Functions.insert_new_function(
        user_id="admin-id",
        user_email="admin@nyu.edu",
        type="pipe",
        form_data=FunctionForm(
            id="other_pipe",
            name="Other",
            content='"""\ntitle: Other\nversion: 0.1\n"""\n',
            meta=FunctionMeta(description="other", manifest={"version": "0.1"}),
        ),
        is_active=True,
    )
    with get_db() as db:
        db.add(Config(
            email="admin@nyu.edu",
            data={"rag": {"openai_api_key": "workspace-key-xyz"}},
            version=0,
        ))
        db.commit()

    from open_webui.main import adopt_existing_llm_function, seed_default_function
    app = _make_app()
    adopt_existing_llm_function(app)
    seed_default_function(app)

    valve = _valve_of("system_default_llm")
    print(json.dumps({
        "has_portkey_key_in_valve": "PORTKEY_API_KEY" in valve,
        "valve": valve,
    }))


# ── Dispatch ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scenario = sys.argv[1]
    {
        "ENSURE_CREATES_FUNCTION": scenario_ensure_creates_function,
        "ENSURE_UPDATES_VALVE": scenario_ensure_updates_valve,
        "ADMIN_SEES_OWN_ONLY": scenario_admin_sees_own_only,
        "USER_SEES_GROUP_ADMIN": scenario_user_sees_group_admin,
        "PIPE_NO_KEY_ERROR": scenario_pipe_no_key_error,
        "PIPE_USES_VALVE_KEY": scenario_pipe_uses_valve_key,
        "SUBCASE_B_NO_VALVE": scenario_subcase_b_no_valve,
    }[scenario]()
