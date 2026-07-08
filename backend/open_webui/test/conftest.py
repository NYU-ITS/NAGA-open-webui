"""Shared fixtures for custom model backend tests (unit + integration).

Env vars must be set BEFORE any open_webui imports that trigger database
initialization (open_webui.config.py runs migrations at import time).

ENV VARS (override via shell or CI):
  WEBUI_SECRET_KEY                        — defaults to test value
  SUPER_ADMIN_EMAILS                      — defaults to test value
  USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS — defaults to "true"
  DATABASE_URL                            — defaults to local SQLite
"""

import os
import sys
import time

_CI = os.environ.get("CI", "").lower() in ("1", "true", "yes")


def _require_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name)
    if val:
        return val
    if default is not None:
        return default
    if _CI:
        print(f"FATAL: required env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return ""


os.environ["WEBUI_SECRET_KEY"] = _require_env("WEBUI_SECRET_KEY", "test-secret-key-for-tests")
os.environ["SUPER_ADMIN_EMAILS"] = _require_env("SUPER_ADMIN_EMAILS", "admin@example.com")
os.environ.setdefault("USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS", "true")

_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_custom_models.db")
_TEST_DB_URI = f"sqlite:///{_TEST_DB_PATH}"
open(_TEST_DB_PATH, "a").close()
os.environ.setdefault("DATABASE_URL", _TEST_DB_URI)

import pytest
from contextlib import contextmanager

TEST_RUN_PREFIX = f"test-custom-models-{int(time.time())}"


def pytest_configure(config):
    config.option.asyncio_mode = "auto"
    config.addinivalue_line("markers", "unit: unit tests (backend)")
    config.addinivalue_line("markers", "integration: integration tests (backend)")


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    yield
    if os.path.exists(_TEST_DB_PATH):
        try:
            os.remove(_TEST_DB_PATH)
        except OSError:
            pass


_CUSTOM_MODEL_PATTERNS = ("test_custom_models", "test_models_table", "test_models_cache")


@pytest.fixture(autouse=True)
def cleanup_tables(request):
    test_file = str(request.node.fspath)
    if not any(p in test_file for p in _CUSTOM_MODEL_PATTERNS):
        yield
        return
    from open_webui.internal.db import engine, Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    from open_webui.internal.db import get_db
    with get_db() as session:
        yield session
        session.rollback()


@pytest.fixture(scope="session")
def app():
    from open_webui.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def async_client(app):
    import httpx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def seed_admin(db_session):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="admin-1",
        name="Admin User",
        email="admin@example.com",
        profile_image_url="/user.png",
        role="admin",
    )
    yield user


@pytest.fixture
def seed_user(db_session, seed_admin):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="test-user-1",
        name="Test User",
        email="test@example.com",
        profile_image_url="/user.png",
        role="admin",
    )
    yield user
    Users.delete_user_by_id("test-user-1")


@pytest.fixture
def seed_user_2(db_session, seed_admin):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="test-user-2",
        name="Test User 2",
        email="test2@example.com",
        profile_image_url="/user.png",
        role="user",
    )
    yield user
    Users.delete_user_by_id("test-user-2")


@pytest.fixture
def seed_user_a(db_session, seed_admin):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="user-a",
        name="User A",
        email="a@example.com",
        profile_image_url="/user.png",
        role="user",
    )
    yield user


@pytest.fixture
def seed_user_b(db_session, seed_admin):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="user-b",
        name="User B",
        email="b@example.com",
        profile_image_url="/user.png",
        role="user",
    )
    yield user


@pytest.fixture
def seed_user_c(db_session, seed_admin):
    from open_webui.models.users import Users
    user = Users.insert_new_user(
        id="user-c",
        name="User C",
        email="c@example.com",
        profile_image_url="/user.png",
        role="user",
    )
    yield user


@pytest.fixture
def mock_admin_user(app):
    @contextmanager
    def _mock(user_id="admin-1", email="admin@example.com"):
        from open_webui.utils.auth import (
            get_verified_user,
            get_admin_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id=user_id,
                name="Admin",
                email=email,
                role="admin",
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_admin_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        app.dependency_overrides = {}

    return _mock


@pytest.fixture
def mock_regular_user(app):
    @contextmanager
    def _mock(user_id="user-1", email="user@test.com", role="user"):
        from open_webui.utils.auth import (
            get_verified_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id=user_id,
                name="Regular User",
                email=email,
                role=role,
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        app.dependency_overrides = {}

    return _mock


@pytest.fixture
def mock_user_a(app):
    @contextmanager
    def _mock(user_id="user-a", email="a@example.com", role="user"):
        from open_webui.utils.auth import (
            get_verified_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id=user_id,
                name="User A",
                email=email,
                role=role,
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        app.dependency_overrides = {}

    return _mock


@pytest.fixture
def mock_user_b(app):
    @contextmanager
    def _mock(user_id="user-b", email="b@example.com", role="user"):
        from open_webui.utils.auth import (
            get_verified_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id=user_id,
                name="User B",
                email=email,
                role=role,
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        app.dependency_overrides = {}

    return _mock


@pytest.fixture
def cleanup_groups():
    created: list[str] = []

    def _register(group_id: str) -> str:
        created.append(group_id)
        return group_id

    yield _register

    from open_webui.models.groups import Groups
    for gid in created:
        try:
            Groups.delete_group_by_id(gid)
        except Exception:
            pass


@pytest.fixture
def cleanup_functions():
    created: list[str] = []

    def _register(func_id: str) -> str:
        created.append(func_id)
        return func_id

    yield _register

    from open_webui.models.functions import Functions
    for fid in created:
        try:
            Functions.delete_function_by_id(fid)
        except Exception:
            pass


@pytest.fixture
def unique_model_id():
    def _make(suffix: str = "") -> str:
        parts = [TEST_RUN_PREFIX]
        if suffix:
            parts.append(suffix)
        return "-".join(parts)

    return _make
