import os

# The first user inserted must be in the super-admin allow-list (fork gating).
os.environ["SUPER_ADMIN_EMAILS"] = "admin@test.com"

from contextlib import contextmanager

from test.util.abstract_integration_test import AbstractPostgresTest


@contextmanager
def as_user(app, **kwargs):
    """Override the authenticated user so the router's real role checks run on top."""
    from open_webui.utils.auth import get_current_user
    from open_webui.models.users import UserModel

    params = {
        "id": "admin",
        "name": "Admin",
        "email": "admin@test.com",
        "role": "admin",
        "profile_image_url": "/user.png",
        "last_active_at": 0,
        "updated_at": 0,
        "created_at": 0,
        "info": None,
        **kwargs,
    }
    user = UserModel(**params)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestGroups(AbstractPostgresTest):
    BASE_PATH = "/api/v1/groups"

    @classmethod
    def setup_class(cls):
        super().setup_class()
        from open_webui.models.groups import Groups
        from open_webui.models.users import Users

        cls.groups = Groups
        cls.users = Users

    def setup_method(self):
        super().setup_method()
        self.users.insert_new_user(
            id="admin", name="Admin", email="admin@test.com", role="admin"
        )
        self.users.insert_new_user(
            id="member", name="Member", email="member@test.com", role="user"
        )

    def teardown_method(self):
        self.groups.delete_all_groups()
        super().teardown_method()

    @property
    def app(self):
        return self.fast_api_client.app

    def _create(self, name="QA", description="desc", **extra):
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            return self.fast_api_client.post(
                self.create_url("/create"),
                json={"name": name, "description": description, **extra},
            )

    # ---- authentication ----

    def test_unauthenticated_is_rejected(self):
        response = self.fast_api_client.get(self.create_url("/"))
        assert response.status_code in (401, 403)

    # ---- validation ----

    def test_create_requires_name(self):
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.post(
                self.create_url("/create"), json={"description": "no name"}
            )
        assert response.status_code == 422

    def test_get_unknown_id_returns_401(self):
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.get(self.create_url("/id/does-not-exist"))
        assert response.status_code == 401

    # ---- admin CRUD ----

    def test_create_stamps_ownership_and_defaults(self):
        response = self._create()
        assert response.status_code == 200, response.text
        group = response.json()
        assert group["id"]
        assert group["name"] == "QA"
        assert group["description"] == "desc"
        assert group["created_by"] == "admin@test.com"
        assert group["user_id"] == "admin"
        assert group["user_ids"] == []
        assert isinstance(group["created_at"], int)
        assert isinstance(group["updated_at"], int)

    def test_new_group_appears_in_list(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.get(self.create_url("/"))
        assert response.status_code == 200
        assert group_id in [g["id"] for g in response.json()]

    def test_get_group_by_id(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.get(self.create_url(f"/id/{group_id}"))
        assert response.status_code == 200
        assert response.json()["id"] == group_id

    def test_update_name_description_permissions(self):
        group_id = self._create().json()["id"]
        permissions = {"workspace": {"models": True}}
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.post(
                self.create_url(f"/id/{group_id}/update"),
                json={
                    "name": "QA-updated",
                    "description": "updated",
                    "permissions": permissions,
                },
            )
        assert response.status_code == 200, response.text
        group = response.json()
        assert group["name"] == "QA-updated"
        assert group["description"] == "updated"
        assert group["permissions"] == permissions

    def test_update_membership_with_valid_user(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.post(
                self.create_url(f"/id/{group_id}/update"),
                json={"name": "QA", "description": "desc", "user_ids": ["member"]},
            )
        assert response.status_code == 200, response.text
        assert "member" in response.json()["user_ids"]

    def test_invalid_user_ids_are_filtered(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.post(
                self.create_url(f"/id/{group_id}/update"),
                json={"name": "QA", "description": "desc", "user_ids": ["ghost"]},
            )
        assert response.status_code == 200, response.text
        assert "ghost" not in response.json()["user_ids"]

    def test_update_nonexistent_returns_400(self):
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.post(
                self.create_url("/id/missing/update"),
                json={"name": "x", "description": "y"},
            )
        assert response.status_code == 400

    def test_delete_group(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="admin", role="admin", email="admin@test.com"):
            response = self.fast_api_client.delete(
                self.create_url(f"/id/{group_id}/delete")
            )
            assert response.status_code == 200
            assert response.json() is True

            after = self.fast_api_client.get(self.create_url(f"/id/{group_id}"))
        assert after.status_code == 401

    # ---- role enforcement ----

    def test_non_admin_cannot_create(self):
        with as_user(self.app, id="member", role="user", email="member@test.com"):
            response = self.fast_api_client.post(
                self.create_url("/create"), json={"name": "x", "description": "y"}
            )
        assert response.status_code == 401

    def test_non_admin_cannot_get_by_id(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="member", role="user", email="member@test.com"):
            response = self.fast_api_client.get(self.create_url(f"/id/{group_id}"))
        assert response.status_code == 401

    def test_non_admin_cannot_update(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="member", role="user", email="member@test.com"):
            response = self.fast_api_client.post(
                self.create_url(f"/id/{group_id}/update"),
                json={"name": "x", "description": "y"},
            )
        assert response.status_code == 401

    def test_non_admin_cannot_delete(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="member", role="user", email="member@test.com"):
            response = self.fast_api_client.delete(
                self.create_url(f"/id/{group_id}/delete")
            )
        assert response.status_code == 401

    def test_non_admin_list_excludes_groups_they_are_not_in(self):
        group_id = self._create().json()["id"]
        with as_user(self.app, id="member", role="user", email="member@test.com"):
            response = self.fast_api_client.get(self.create_url("/"))
        assert response.status_code == 200
        assert group_id not in [g["id"] for g in response.json()]
