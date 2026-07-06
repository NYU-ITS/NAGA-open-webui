"""Tests for ModelsTable ORM methods."""

import pytest
from open_webui.models.models import Models, ModelForm, ModelMeta, ModelParams

pytestmark = pytest.mark.unit


class TestModelsTable:
    """Tests for ModelsTable ORM methods against SQLite."""

    def _make_form(self, id="test-model", name="Test Model", base_model_id=None):
        return ModelForm(
            id=id,
            name=name,
            base_model_id=base_model_id,
            meta=ModelMeta(),
            params=ModelParams(),
        )

    def test_insert_new_model_returns_model(self, db_session, seed_user):
        form = self._make_form()
        result = Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        assert result is not None
        assert result.id == "test-model"
        assert result.name == "Test Model"
        assert result.user_id == seed_user.id
        assert result.created_by == seed_user.email
        assert result.created_at > 0
        assert result.updated_at > 0

    def test_insert_duplicate_id_returns_none(self, db_session, seed_user):
        form = self._make_form(id="dup-model")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        result = Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)
        assert result is None

    def test_get_model_by_id_existing(self, db_session, seed_user):
        form = self._make_form(id="find-me")
        inserted = Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)
        assert inserted is not None

        result = Models.get_model_by_id("find-me")
        assert result is not None
        assert result.id == "find-me"
        assert result.name == "Test Model"

    def test_get_model_by_id_nonexistent(self, db_session):
        result = Models.get_model_by_id("nonexistent")
        assert result is None

    def test_toggle_model_active_to_inactive(self, db_session, seed_user):
        form = self._make_form(id="toggle-me")
        inserted = Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)
        assert inserted.is_active is True

        toggled = Models.toggle_model_by_id("toggle-me")
        assert toggled is not None
        assert toggled.is_active is False

        toggled_again = Models.toggle_model_by_id("toggle-me")
        assert toggled_again.is_active is True

    def test_toggle_nonexistent_returns_none(self, db_session):
        result = Models.toggle_model_by_id("nonexistent")
        assert result is None

    def test_update_model_by_id_changes_name(self, db_session, seed_user):
        form = self._make_form(id="update-me")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        update_form = self._make_form(id="update-me", name="Updated Name")
        result = Models.update_model_by_id("update-me", update_form)
        assert result is not None
        assert result.name == "Updated Name"

    def test_update_model_by_id_immutable_id(self, db_session, seed_user):
        """The id field in the form should be ignored during update; DB id stays."""
        form = self._make_form(id="original-id")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        update_form = self._make_form(id="different-id", name="Updated")
        result = Models.update_model_by_id("original-id", update_form)
        assert result is not None
        assert result.id == "original-id"

    def test_update_nonexistent_returns_none(self, db_session):
        form = self._make_form(id="nope")
        result = Models.update_model_by_id("nope", form)
        assert result is None

    def test_delete_model_by_id_existing(self, db_session, seed_user):
        form = self._make_form(id="delete-me")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        result = Models.delete_model_by_id("delete-me")
        assert result is True
        assert Models.get_model_by_id("delete-me") is None

    def test_delete_model_by_id_nonexistent_returns_true(self, db_session):
        """ORM returns True even if no rows deleted. Router prevents via existence check."""
        result = Models.delete_model_by_id("nonexistent")
        assert result is True

    def test_get_models_only_custom(self, db_session, seed_user):
        """get_models() returns only models with base_model_id != None."""
        form_custom = self._make_form(id="custom-1", base_model_id="base-1")
        form_base = self._make_form(id="base-1", base_model_id=None)
        Models.insert_new_model(form_custom, user_id=seed_user.id, user_email=seed_user.email)
        Models.insert_new_model(form_base, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_models()
        ids = [m.id for m in results]
        assert "custom-1" in ids
        assert "base-1" not in ids

    def test_get_base_models_only_base(self, db_session, seed_user):
        """get_base_models() returns only models with base_model_id == None."""
        form_custom = self._make_form(id="custom-1", base_model_id="base-1")
        form_base = self._make_form(id="base-1", base_model_id=None)
        Models.insert_new_model(form_custom, user_id=seed_user.id, user_email=seed_user.email)
        Models.insert_new_model(form_base, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_base_models()
        ids = [m.id for m in results]
        assert "base-1" in ids
        assert "custom-1" not in ids

    def test_get_base_models_no_access_filtering(self, db_session, seed_user):
        """get_base_models() returns all base models regardless of access_control."""
        form = self._make_form(id="base-1", base_model_id=None)
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_base_models()
        assert len(results) >= 1
        # No filtering — should return the base model even though not owned by a test user

    def test_get_all_models_creator_sees_own_model(self, db_session, seed_user):
        """Creator always sees own models via created_by == user_email match."""
        form = self._make_form(id="own-model")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_all_models(user_id=seed_user.id, user_email=seed_user.email)
        assert any(m.id == "own-model" for m in results)

    def test_get_all_models_private_not_visible_to_others(self, db_session, seed_user, seed_user_2):
        """Private model (access_control=None) not visible to other users."""
        form = self._make_form(id="private-model")
        Models.insert_new_model(form, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_all_models(user_id=seed_user_2.id, user_email=seed_user_2.email)
        assert not any(m.id == "private-model" for m in results)

    def test_get_models_by_ids_batch(self, db_session, seed_user):
        form_a = self._make_form(id="batch-a")
        form_b = self._make_form(id="batch-b")
        Models.insert_new_model(form_a, user_id=seed_user.id, user_email=seed_user.email)
        Models.insert_new_model(form_b, user_id=seed_user.id, user_email=seed_user.email)

        results = Models.get_models_by_ids(["batch-a", "batch-b", "nonexistent"])
        assert "batch-a" in results
        assert "batch-b" in results
        assert "nonexistent" not in results

    def test_get_models_by_ids_empty_list(self, db_session):
        results = Models.get_models_by_ids([])
        assert results == {}
