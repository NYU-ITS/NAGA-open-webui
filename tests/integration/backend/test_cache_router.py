"""Integration tests: Router ops -> cache invalidation -> fresh reads.

Verifies that create/update/toggle/delete correctly invalidate the in-memory
ModelsLRUCache and subsequent reads return fresh data from the DB.
"""

import pytest
from tests.integration.backend.conftest import TEST_RUN_PREFIX

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BASE = "/api/v1/models"


def _mid(suffix: str = "cache-model") -> str:
    return f"{TEST_RUN_PREFIX}-{suffix}"


def _model_payload(id=None, name="Cache Model", base_model_id="some-base", access_control=None):
    if id is None:
        id = _mid()
    payload = {
        "id": id,
        "name": name,
        "base_model_id": base_model_id,
        "meta": {"profile_image_url": "/static/favicon.png"},
        "params": {},
    }
    if access_control is not None:
        payload["access_control"] = access_control
    return payload


class TestCacheRouterIntegration:
    """Cache + Router integration tests."""

    async def test_create_then_list(self, async_client, mock_admin_user):
        model_id = _mid("cache-crud")
        with mock_admin_user():
            resp = await async_client.post(f"{BASE}/create", json=_model_payload(id=model_id))
            assert resp.status_code == 200

            resp = await async_client.get(f"{BASE}/")
        assert resp.status_code == 200
        models = resp.json()
        assert any(m["id"] == model_id for m in models)

    async def test_update_reflected_in_list(self, async_client, mock_admin_user):
        model_id = _mid("cache-update")
        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=model_id, name="Original"))
            resp = await async_client.post(
                f"{BASE}/model/update",
                params={"id": model_id},
                json=_model_payload(id=model_id, name="Updated"),
            )
            assert resp.status_code == 200

            resp = await async_client.get(f"{BASE}/")
        models = resp.json()
        model = next(m for m in models if m["id"] == model_id)
        assert model["name"] == "Updated"

    async def test_toggle_reflected_in_list(self, async_client, mock_admin_user):
        model_id = _mid("cache-toggle")
        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=model_id))
            resp = await async_client.post(f"{BASE}/model/toggle", params={"id": model_id})
            assert resp.status_code == 200
            assert resp.json()["is_active"] is False

            resp = await async_client.get(f"{BASE}/")
        models = resp.json()
        model = next(m for m in models if m["id"] == model_id)
        assert model["is_active"] is False

    async def test_delete_reflected_in_list(self, async_client, mock_admin_user):
        model_id = _mid("cache-delete")
        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=model_id))
            resp = await async_client.delete(f"{BASE}/model/delete", params={"id": model_id})
            assert resp.status_code == 200

            resp = await async_client.get(f"{BASE}/")
        assert not any(m["id"] == model_id for m in resp.json())

    async def test_delete_all_clears_cache(self, async_client, mock_admin_user):
        m1 = _mid("cache-m1")
        m2 = _mid("cache-m2")
        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=m1))
            await async_client.post(f"{BASE}/create", json=_model_payload(id=m2, name="M2"))
            resp = await async_client.delete(f"{BASE}/delete/all")
            assert resp.status_code == 200

            resp = await async_client.get(f"{BASE}/")
        assert resp.json() == []

    async def test_create_model_invalidate_cache_for_creator(
        self, async_client, mock_admin_user, seed_admin, app
    ):
        from open_webui.utils.models import ModelsLRUCache

        app.state.MODELS = ModelsLRUCache()
        app.state.MODELS["admin-1"] = {"old": {}}

        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=_mid("cache-inv")))

        assert "admin-1" not in app.state.MODELS

    async def test_create_with_access_control_invalidates_group_member_cache(
        self, async_client, mock_admin_user, seed_admin, seed_user_a, app,
        cleanup_groups,
    ):
        from open_webui.utils.models import ModelsLRUCache
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = f"{TEST_RUN_PREFIX}-cache-grp"
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="desc"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="desc", user_ids=["user-a"]),
        )

        app.state.MODELS = ModelsLRUCache()
        app.state.MODELS["user-a"] = {"old": {}}

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    id=_mid("cache-grp-inv"),
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    }
                ),
            )

        assert "user-a" not in app.state.MODELS

    async def test_base_models_endpoint_returns_all(self, async_client, mock_admin_user):
        base_id = _mid("cache-base-1")
        custom_id = _mid("cache-custom-1")
        with mock_admin_user():
            await async_client.post(f"{BASE}/create", json=_model_payload(id=base_id, base_model_id=None))
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(id=custom_id, base_model_id=base_id),
            )
            resp = await async_client.get(f"{BASE}/base")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert base_id in ids
        assert custom_id not in ids
