"""Tests for ModelsLRUCache and get_affected_user_ids_for_model."""

import pytest
import threading
from unittest.mock import patch, MagicMock
from open_webui.utils.models import ModelsLRUCache, get_affected_user_ids_for_model

pytestmark = pytest.mark.unit


# Patch target: open_webui.models.groups.Groups.get_group_by_id
# (imported inside get_affected_user_ids_for_model function)


class TestModelsLRUCache:
    def test_set_and_get(self):
        cache = ModelsLRUCache(maxsize=10)
        cache["user1"] = {"m1": {"id": "m1"}}
        assert cache["user1"] == {"m1": {"id": "m1"}}

    def test_lru_eviction(self):
        cache = ModelsLRUCache(maxsize=2)
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3  # evicts "a"

        assert "a" not in cache
        assert cache["b"] == 2
        assert cache["c"] == 3

    def test_get_moves_to_end_preventing_eviction(self):
        cache = ModelsLRUCache(maxsize=2)
        cache["a"] = 1
        cache["b"] = 2
        _ = cache.get("a")  # moves "a" to end
        cache["c"] = 3  # evicts "b" (not "a")

        assert cache["a"] == 1
        assert "b" not in cache
        assert cache["c"] == 3

    def test_thread_safety(self):
        cache = ModelsLRUCache(maxsize=100)
        errors = []

        def writer():
            try:
                for i in range(50):
                    cache[f"key-{i}"] = i
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    cache.get(f"key-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGetAffectedUserIds:
    @patch("open_webui.utils.models.get_super_admin_emails", return_value=[])
    def test_includes_model_owner(self, mock_super):
        model = MagicMock(
            user_id="owner-1",
            access_control=None,
        )
        result = get_affected_user_ids_for_model(model)
        assert "owner-1" in result

    @patch("open_webui.utils.models.get_super_admin_emails", return_value=[])
    @patch("open_webui.models.groups.Groups.get_group_by_id")
    def test_includes_group_members_read(self, mock_get_group, mock_super):
        mock_get_group.return_value = MagicMock(
            user_id="group-owner",
            user_ids=["member-1", "member-2"],
        )
        model = MagicMock(
            user_id="owner-1",
            access_control={
                "read": {"group_ids": ["g1"], "user_ids": []},
                "write": {"group_ids": [], "user_ids": []},
            },
        )

        result = get_affected_user_ids_for_model(model)
        assert "group-owner" in result
        assert "member-1" in result
        assert "member-2" in result

    @patch("open_webui.utils.models.get_super_admin_emails", return_value=[])
    def test_includes_explicit_user_ids(self, mock_super):
        model = MagicMock(
            user_id="owner-1",
            access_control={
                "read": {"group_ids": [], "user_ids": ["reader-1"]},
                "write": {"group_ids": [], "user_ids": ["writer-1"]},
            },
        )
        result = get_affected_user_ids_for_model(model)
        assert "reader-1" in result
        assert "writer-1" in result

    @patch("open_webui.utils.models.get_super_admin_emails", return_value=["super@test.com"])
    @patch("open_webui.utils.models.Users.get_user_by_email")
    def test_super_admins_always_included(self, mock_get_email, mock_super):
        mock_get_email.return_value = MagicMock(id="super-1")
        model = MagicMock(
            user_id="owner-1",
            access_control=None,
        )
        result = get_affected_user_ids_for_model(model)
        assert "super-1" in result

    @patch("open_webui.utils.models.get_super_admin_emails", return_value=[])
    def test_model_without_access_control_returns_only_owner(self, mock_super):
        model = MagicMock(
            user_id="owner-1",
            access_control=None,
        )
        result = get_affected_user_ids_for_model(model)
        # Returns a list, not a set
        assert "owner-1" in result
        assert len(result) == 1
