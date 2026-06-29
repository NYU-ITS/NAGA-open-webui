"""Shared fixtures for backend integration tests.

Uses SQLite (same pattern as unit backend conftest). Sets env vars before
any open_webui imports to avoid triggering real Postgres or Redis connections.
"""

import os

os.environ["WEBUI_SECRET_KEY"] = "test-secret-key-for-integration-tests"
os.environ["SUPER_ADMIN_EMAILS"] = "admin@example.com"

# Allow non-admin users to create models (workspace permission)
os.environ["USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS"] = "true"
# Do NOT override REDIS_URL — let it use the default redis://localhost:6379/0
# CacheManager gracefully handles connection failures via _check_redis_available()

_TEST_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "test_integration.db"
)
_TEST_DB_URI = f"sqlite:///{_TEST_DB_PATH}"
open(_TEST_DB_PATH, "a").close()
os.environ["DATABASE_URL"] = _TEST_DB_URI

import pytest
from contextlib import contextmanager


def pytest_configure(config):
    config.option.asyncio_mode = "auto"


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    yield
    if os.path.exists(_TEST_DB_PATH):
        try:
            os.remove(_TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def cleanup_tables():
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
