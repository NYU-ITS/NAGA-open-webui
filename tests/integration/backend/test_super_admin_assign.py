"""Integration tests: Super admin model creation auto-assigns to function creator.

Tests that when a super admin creates a model with base_model_id matching a
pipe function, ownership is automatically assigned to the function's creator.
"""

import pytest
from tests.integration.backend.conftest import TEST_RUN_PREFIX

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BASE = "/api/v1/models"


def _mid(suffix: str) -> str:
    return f"{TEST_RUN_PREFIX}-{suffix}"


def _fid(suffix: str) -> str:
    return f"{TEST_RUN_PREFIX}-func-{suffix}"


def _model_payload(id, name, base_model_id=None):
    return {
        "id": id,
        "name": name,
        "base_model_id": base_model_id,
        "meta": {"profile_image_url": "/static/favicon.png"},
        "params": {},
    }


def _seed_pipe_function(func_id, created_by_email, user_id, active=True):
    from open_webui.models.functions import Functions, FunctionForm, FunctionMeta

    func = Functions.insert_new_function(
        user_id=user_id,
        user_email=created_by_email,
        type="pipe",
        form_data=FunctionForm(
            id=func_id,
            name=f"Function {func_id}",
            content="def pipe(): pass",
            meta=FunctionMeta(description="test pipe"),
        ),
    )
    if func and active:
        Functions.update_function_by_id(func_id, {"is_active": True})
    return func


class TestSuperAdminAssign:
    """Super admin auto-assign tests."""

    async def test_super_admin_assigns_function_creator(
        self, async_client, mock_admin_user, seed_admin, seed_user_a,
        cleanup_functions,
    ):
        func_id = _fid("pipe-1")
        model_id = _mid("assign-1")
        _seed_pipe_function(func_id, "a@example.com", "user-a")
        cleanup_functions(func_id)

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Assigned", base_model_id=func_id),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_super_admin_assigns_on_prefix_match(
        self, async_client, mock_admin_user, seed_admin, seed_user_a,
        cleanup_functions,
    ):
        func_id = _fid("pipe-2")
        model_id = _mid("assign-2")
        _seed_pipe_function(func_id, "a@example.com", "user-a")
        cleanup_functions(func_id)

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Prefix Match", base_model_id=f"{func_id}.myslug"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_no_assign_for_unrelated_base_model(
        self, async_client, mock_admin_user, seed_admin,
        cleanup_functions,
    ):
        func_id = _fid("pipe-3")
        model_id = _mid("no-assign")
        _seed_pipe_function(func_id, "admin@example.com", "admin-1")
        cleanup_functions(func_id)

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "No Assign", base_model_id="some-other-model"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_non_admin_no_auto_assign(
        self, async_client, mock_user_a, seed_admin, seed_user_a,
        cleanup_functions,
    ):
        func_id = _fid("pipe-4")
        model_id = _mid("no-super")
        _seed_pipe_function(func_id, "a@example.com", "user-a")
        cleanup_functions(func_id)

        with mock_user_a():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "No Super", base_model_id=func_id),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_function_not_found_falls_back_to_admin(
        self, async_client, mock_admin_user, seed_admin
    ):
        model_id = _mid("fallback")
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Fallback", base_model_id="nonexistent-func"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_no_base_model_no_reassign(
        self, async_client, mock_admin_user, seed_admin
    ):
        model_id = _mid("no-base")
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "No Base"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_inactive_function_not_matched(
        self, async_client, mock_admin_user, seed_admin, seed_user_a,
        cleanup_functions,
    ):
        func_id = _fid("pipe-inactive")
        model_id = _mid("inactive-func")
        _seed_pipe_function(func_id, "a@example.com", "user-a")
        from open_webui.models.functions import Functions
        Functions.update_function_by_id(func_id, {"is_active": False})
        cleanup_functions(func_id)

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Inactive", base_model_id=func_id),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
