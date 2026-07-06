"""Tests for custom models router endpoints.

Uses httpx.AsyncClient against the FastAPI app with auth overridden.
"""

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

BASE_PATH = "/api/v1/models"


@pytest.mark.asyncio
class TestModelsRouter:
    """CRUD + listing tests for models endpoints."""

    async def test_get_models_empty(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.get(f"{BASE_PATH}/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_model_as_admin(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "router-test-model",
                    "name": "Test Model",
                    "meta": {"profile_image_url": "/static/favicon.png", "description": ""},
                    "params": {},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "router-test-model"
        assert data["name"] == "Test Model"
        assert "created_at" in data
        assert "user_id" in data

    async def test_create_duplicate_id(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "dup-model",
                    "name": "First",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "dup-model",
                    "name": "Second",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert "already registered" in detail or "MODEL_ID_TAKEN" in detail

    async def test_create_missing_required_fields(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE_PATH}/create",
                json={"name": "Missing id"},
            )
        assert resp.status_code == 422  # FastAPI validation

    async def test_get_model_by_id_existing(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "router-find-me",
                    "name": "Find Me",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.get(f"{BASE_PATH}/model", params={"id": "router-find-me"})
        assert resp.status_code == 200
        assert resp.json()["id"] == "router-find-me"

    async def test_get_model_by_id_not_found(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.get(f"{BASE_PATH}/model", params={"id": "nonexistent"})
        assert resp.status_code == 404
        assert "Model not found" in resp.json()["detail"]

    async def test_list_after_create(self, async_client, mock_admin_user):
        with mock_admin_user():
            # Create a custom model WITH base_model_id (GET / filters by base_model_id != None)
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "list-me",
                    "name": "List Me",
                    "base_model_id": "some-base",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.get(f"{BASE_PATH}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(m["id"] == "list-me" for m in data)

    async def test_toggle_model(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "toggle-me",
                    "name": "Toggle",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.post(f"{BASE_PATH}/model/toggle", params={"id": "toggle-me"})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_toggle_nonexistent(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE_PATH}/model/toggle", params={"id": "nonexistent"}
            )
        assert resp.status_code == 401

    async def test_update_model(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "update-me",
                    "name": "Original",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.post(
                f"{BASE_PATH}/model/update",
                params={"id": "update-me"},
                json={
                    "id": "update-me",
                    "name": "Updated",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    async def test_update_id_immutability(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "immutable-id",
                    "name": "Original",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.post(
                f"{BASE_PATH}/model/update",
                params={"id": "immutable-id"},
                json={
                    "id": "different-id",
                    "name": "Updated",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "immutable-id"

    async def test_delete_model(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "delete-me",
                    "name": "Delete",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.delete(
                f"{BASE_PATH}/model/delete", params={"id": "delete-me"}
            )
        assert resp.status_code == 200
        assert resp.json() is True

    async def test_delete_nonexistent(self, async_client, mock_admin_user):
        with mock_admin_user():
            resp = await async_client.delete(
                f"{BASE_PATH}/model/delete", params={"id": "nonexistent"}
            )
        assert resp.status_code == 401

    async def test_delete_all_models(self, async_client, mock_admin_user):
        with mock_admin_user():
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "bulk-1",
                    "name": "Bulk 1",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "bulk-2",
                    "name": "Bulk 2",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.delete(f"{BASE_PATH}/delete/all")
        assert resp.status_code == 200
        assert resp.json() is True

        # Verify empty
        with mock_admin_user():
            list_resp = await async_client.get(f"{BASE_PATH}/")
        assert list_resp.json() == []

    async def test_get_base_models(self, async_client, mock_admin_user):
        with mock_admin_user():
            # Create a base model (base_model_id=None)
            await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "base-1",
                    "name": "Base",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
            resp = await async_client.get(f"{BASE_PATH}/base")
        assert resp.status_code == 200
        assert any(m["id"] == "base-1" for m in resp.json())

    async def test_unauthorized_user_blocked_from_create(self, async_client, mock_regular_user):
        with mock_regular_user():
            resp = await async_client.post(
                f"{BASE_PATH}/create",
                json={
                    "id": "no-perm",
                    "name": "No Permission",
                    "meta": {"profile_image_url": "/static/favicon.png"},
                    "params": {},
                },
            )
        assert resp.status_code == 401
