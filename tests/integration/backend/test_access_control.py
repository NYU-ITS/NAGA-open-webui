"""Integration tests: Access control cross-table (models + groups + users).

Tests both has_access() and item_assigned_to_user_groups() code paths with
real DB joins using SQLite.
"""

import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/models"


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
    """1H — Access control cross-table integration tests."""

    async def test_private_model_only_creator_can_read(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("private-1", "Private", access_control=None),
            )

        # Creator can read
        with mock_admin_user():
            resp = await async_client.get(f"{BASE}/model", params={"id": "private-1"})
        assert resp.status_code == 200

        # Other user cannot
        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "private-1"})
        assert resp.status_code == 401

    async def test_empty_access_control_only_creator(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("empty-ac-1", "Empty AC", access_control={}),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "empty-ac-1"})
        assert resp.status_code == 401

    async def test_group_read_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="Readers", description="read group"),
        )
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name="Readers", description="read group", user_ids=["user-a"]),
        )

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "group-read-1",
                    "Group Read",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "group-read-1"})
        assert resp.status_code == 200

    async def test_non_group_member_denied(
        self, async_client, mock_admin_user, mock_user_b, seed_admin, seed_user_b
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="Exclusive", description="members only"),
        )
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name="Exclusive", description="members only", user_ids=["user-a"]),
        )

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "exclusive-1",
                    "Exclusive",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        # user-b is not in group
        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": "exclusive-1"})
        assert resp.status_code == 401

    async def test_group_write_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="Writers", description="write group"),
        )
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name="Writers", description="write group", user_ids=["user-a"]),
        )

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "group-write-1",
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
                params={"id": "group-write-1"},
                json=_model_payload("group-write-1", "Updated by group member"),
            )
        assert resp.status_code == 200

    async def test_explicit_user_read_access(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "user-explicit-1",
                    "Explicit User",
                    access_control={
                        "read": {"group_ids": [], "user_ids": ["user-a"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "user-explicit-1"})
        assert resp.status_code == 200

    async def test_user_not_in_explicit_list_denied(
        self, async_client, mock_admin_user, mock_user_b, seed_admin, seed_user_b
    ):
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "explicit-other",
                    "Explicit Other",
                    access_control={
                        "read": {"group_ids": [], "user_ids": ["user-a"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": "explicit-other"})
        assert resp.status_code == 401

    async def test_mixed_group_and_user_access(
        self, async_client, mock_admin_user, mock_user_a, mock_user_b, seed_admin, seed_user_a, seed_user_b
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="Mixed", description="mixed group"),
        )
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name="Mixed", description="mixed group", user_ids=["user-a"]),
        )

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "mixed-1",
                    "Mixed Access",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": ["user-b"]},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        # user-a has group access
        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "mixed-1"})
        assert resp.status_code == 200

        # user-b has explicit user access
        with mock_user_b():
            resp = await async_client.get(f"{BASE}/model", params={"id": "mixed-1"})
        assert resp.status_code == 200

    async def test_user_in_multiple_groups(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group_a = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="GroupA", description="a"),
        )
        group_b = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="GroupB", description="b"),
        )
        # Add user-a to both groups
        Groups.update_group_by_id(
            group_a.id,
            GroupUpdateForm(name="GroupA", description="a", user_ids=["user-a"]),
        )
        Groups.update_group_by_id(
            group_b.id,
            GroupUpdateForm(name="GroupB", description="b", user_ids=["user-a"]),
        )

        # Model accessible only via group_b
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "multi-group-1",
                    "Multi Group",
                    access_control={
                        "read": {"group_ids": [group_b.id], "user_ids": []},
                        "write": {"group_ids": [], "user_ids": []},
                    },
                ),
            )

        with mock_user_a():
            resp = await async_client.get(f"{BASE}/model", params={"id": "multi-group-1"})
        assert resp.status_code == 200

    async def test_each_user_sees_only_accessible_models(
        self, async_client, mock_admin_user, mock_user_a, mock_user_b, seed_admin, seed_user_a, seed_user_b
    ):
        # Admin creates: shared model (user-a has write access via group), private model
        from open_webui.models.groups import Groups, GroupForm, GroupUpdateForm

        group = Groups.insert_new_group(
            user_id="admin-1",
            user_email="admin@example.com",
            form_data=GroupForm(name="Shared", description="shared"),
        )
        Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(name="Shared", description="shared", user_ids=["user-a"]),
        )

        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload(
                    "shared-1",
                    "Shared",
                    access_control={
                        "read": {"group_ids": [group.id], "user_ids": []},
                        "write": {"group_ids": [group.id], "user_ids": []},
                    },
                ),
            )
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("private-admin", "Admin Private", base_model_id="other-base"),
            )

        # user-a sees shared model (has write access via group)
        with mock_user_a():
            resp = await async_client.get(f"{BASE}/")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert "shared-1" in ids
        assert "private-admin" not in ids

    async def test_admin_can_update_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        # user-a creates a model
        with mock_user_a():
            resp = await async_client.post(
                f"{BASE}/create",
                json=_model_payload("user-a-model", "User A Model"),
            )
        assert resp.status_code == 200

        # admin can update it
        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/model/update",
                params={"id": "user-a-model"},
                json=_model_payload("user-a-model", "Admin Updated"),
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Admin Updated"

    async def test_admin_can_delete_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_user_a():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("user-a-del", "User A Del"),
            )

        with mock_admin_user():
            resp = await async_client.delete(f"{BASE}/model/delete", params={"id": "user-a-del"})
        assert resp.status_code == 200

    async def test_admin_can_toggle_any_model(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_user_a():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("user-a-toggle", "User A Toggle"),
            )

        with mock_admin_user():
            resp = await async_client.post(
                f"{BASE}/model/toggle", params={"id": "user-a-toggle"}
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_base_models_no_access_filtering(
        self, async_client, mock_admin_user, mock_user_a, seed_admin, seed_user_a
    ):
        with mock_admin_user():
            await async_client.post(
                f"{BASE}/create",
                json=_model_payload("base-unfiltered", "Base Unfiltered", base_model_id=None),
            )

        # user-a can see base models regardless of access_control
        with mock_user_a():
            resp = await async_client.get(f"{BASE}/base")
        assert resp.status_code == 200
        assert any(m["id"] == "base-unfiltered" for m in resp.json())
