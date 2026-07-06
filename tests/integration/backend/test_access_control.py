"""Integration tests: Access control cross-table (models + groups + users).

Tests both has_access() and item_assigned_to_user_groups() code paths with
real DB joins using SQLite.
"""

import pytest
from tests.integration.backend.conftest import TEST_RUN_PREFIX

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BASE = "/api/v1/models"


def _mid(suffix: str) -> str:
    return f"{TEST_RUN_PREFIX}-{suffix}"


def _gid(suffix: str) -> str:
    return f"{TEST_RUN_PREFIX}-grp-{suffix}"


def _model_payload(id, name, access_control=None, base_model_id="some-base"):
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


class TestAccessControl:
    """Access control cross-table integration tests."""

    async def test_private_model_only_creator_can_read(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("private-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Private", access_control=None),
            )

        with mock_admin_user():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 401

    async def test_empty_access_control_only_creator(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("empty-ac-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Empty AC", access_control={}),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 401

    async def test_group_read_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a,
        cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = _gid("readers")
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="read group"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="read group", user_ids=["user-a"]),
        )

        model_id = _mid("group-read-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Group Read",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

    async def test_non_group_member_denied(
        self, async_client, mock_admin_user, mock_user_b, seed_admin, seed_user_b,
        cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = _gid("exclusive")
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="members only"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="members only", user_ids=["user-a"]),
        )

        model_id = _mid("exclusive-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Exclusive",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 401

    async def test_group_write_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a,
        cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = _gid("writers")
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="write group"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="write group", user_ids=["user-a"]),
        )

        model_id = _mid("group-write-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Group Write",
                    access_control={
                        "read": {"group_ids": [], "user_ids": []},
                        "write": {"group_ids": [group.id], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.post(
                f"{BASE}/model/update",
                params={"id": model_id},
                json=_model_payload(model_id, "Updated by group member"),
            )
        assert resp.status_code == 200

    async def test_explicit_user_read_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("user-explicit-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Explicit User",
                    access_control={
                        "read": {"group_ids": [], "user_ids": ["user-a"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

    async def test_user_not_in_explicit_list_denied(
        self, async_client, mock_admin_user, mock_user_b, seed_admin, seed_user_b
    ):
        model_id = _mid("explicit-other")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Explicit Other",
                    access_control={
                        "read": {"group_ids": [], "user_ids": ["user-a"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 401

    async def test_mixed_group_and_user_access(
        self, async_client, mock_admin_user, mock_user_a, mock_user_b,
        seed_admin, seed_user_a, seed_user_b, cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = _gid("mixed")
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="mixed group"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="mixed group", user_ids=["user-a"]),
        )

        model_id = _mid("mixed-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Mixed Access",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": ["user-b"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

    async def test_user_in_multiple_groups(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a,
        cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_a_name = _gid("group-a")
        group_b_name = _gid("group-b")
        group_a = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_a_name, description="a"),
        )
        group_b = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_b_name, description="b"),
        )
        cleanup_groups(group_a.id)
        cleanup_groups(group_b.id)
        Groups.update_group_by_id(
            group_a.id,
            GroupUpdateForm(name=group_a_name, description="a", user_ids=["user-a"]),
        )
        Groups.update_group_by_id(
            group_b.id,
            GroupUpdateForm(name=group_b_name, description="b", user_ids=["user-a"]),
        )

        model_id = _mid("multi-group-1")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    model_id,
                    "Multi Group",
                    access_control={
                        "read": {"group_ids": [group_b.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": model_id})
        assert resp.status_code == 200

    async def test_each_user_sees_only_accessible_models(
        self, async_client, mock_admin_user, mock_user_a, mock_user_b,
        seed_admin, seed_user_a, seed_user_b, cleanup_groups,
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_name = _gid("shared")
        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name=group_name, description="shared"),
        )
        cleanup_groups(group.id)
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name=group_name, description="shared", user_ids=["user-a"]),
        )

        shared_id = _mid("shared-1")
        private_id = _mid("private-admin")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    shared_id,
                    "Shared",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [group.id], "user_ids": []},
                    },
                ),
            )
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(private_id, "Admin Private", base_model_id="other-base"),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert shared_id in ids
        assert private_id not in ids

    async def test_admin_can_update_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("user-a-model")
        with mock_user_a():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "User A Model"),
            )
        assert resp.status_code == 200

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/model/update",
                params={"id": model_id},
                json=_model_payload(model_id, "Admin Updated"),
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Admin Updated"

    async def test_admin_can_delete_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("user-a-del")
        with mock_user_a():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "User A Del"),
            )

        with mock_admin_user():
            resp = await async_client.delete(f"{BASE}/model/delete", params={"id": model_id})
        assert resp.status_code == 200

    async def test_admin_can_toggle_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("user-a-toggle")
        with mock_user_a():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "User A Toggle"),
            )

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/model/toggle", params={"id": model_id}
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_base_models_no_access_filtering(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        model_id = _mid("base-unfiltered")
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(model_id, "Base Unfiltered", base_model_id=None),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/base")
        assert resp.status_code == 200
        assert any(m["id"] == model_id for m in resp.json())
