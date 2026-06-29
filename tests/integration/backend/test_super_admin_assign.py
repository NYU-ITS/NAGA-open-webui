"""Integration tests: Super admin model creation auto-assigns to function creator.

Tests that when a super admin creates a model with base_model_id matching a
pipe function, ownership is automatically assigned to the function's creator.
"""

import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/models"


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
    """1I — Super admin auto-assign tests."""

    async def test_super_admin_assigns_function_creator(
        self, async_client, mock_admin_user, seed_admin, seed_user_a
    ):
        """Super admin creates model with base_model_id=function_id → user_id set to function creator."""
        func = _seed_pipe_function("pipe-1", "a@example.com", "user-a")

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("assign-1", "Assigned", base_model_id="pipe-1"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_super_admin_assigns_on_prefix_match(
        self, async_client, mock_admin_user, seed_admin, seed_user_a
    ):
        """base_model_id=func_id.slug also triggers auto-assign."""
        _seed_pipe_function("pipe-2", "a@example.com", "user-a")

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("assign-2", "Prefix Match", base_model_id="pipe-2.myslug"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_no_assign_for_unrelated_base_model(
        self, async_client, mock_admin_user, seed_admin
    ):
        """Super admin creates model with unrelated base_model_id → user_id stays as super admin."""
        _seed_pipe_function("pipe-3", "admin@example.com", "admin-1")

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("no-assign", "No Assign", base_model_id="some-other-model"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_non_admin_no_auto_assign(
        self, async_client, mock_user_a, seed_admin, seed_user_a
    ):
        """Non-admin creates model with function base_model_id → no auto-assign."""
        _seed_pipe_function("pipe-4", "a@example.com", "user-a")

        with mock_user_a():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("no-super", "No Super", base_model_id="pipe-4"),
            )
        assert resp.status_code == 200
        data = resp.json()
        # user-a is NOT a super admin (email not in SUPER_ADMIN_EMAILS, not first user)
        # so auto-assign does NOT trigger; user_id stays as the requester
        assert data["user_id"] == "user-a"
        assert data["created_by"] == "a@example.com"

    async def test_function_not_found_falls_back_to_admin(
        self, async_client, mock_admin_user, seed_admin
    ):
        """base_model_id matches no function → user_id stays as super admin."""
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("fallback", "Fallback", base_model_id="nonexistent-func"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_no_base_model_no_reassign(
        self, async_client, mock_admin_user, seed_admin
    ):
        """Super admin creates model with no base_model_id → no re-assign."""
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("no-base", "No Base"),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "admin-1"
        assert data["created_by"] == "admin@example.com"

    async def test_inactive_function_not_matched(
        self, async_client, mock_admin_user, seed_admin, seed_user_a
    ):
        """Inactive functions should not trigger auto-assign (get_functions_by_type active_only=True)."""
        from open_webui.models.functions import Functions

        func = _seed_pipe_function("pipe-inactive", "a@example.com", "user-a")
        # Deactivate the function
        Functions.update_function_by_id("pipe-inactive", {"is_active": False})

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("inactive-func", "Inactive", base_model_id="pipe-inactive"),
            )
        assert resp.status_code == 200
        data = resp.json()
        # Should NOT be reassigned because function is inactive
        assert data["user_id"] == "admin-1"
