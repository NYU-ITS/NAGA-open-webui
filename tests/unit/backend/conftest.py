"""Shared fixtures for backend unit tests.

IMPORTANT: Env vars must be set at module level BEFORE any open_webui
imports that trigger database initialization (open_webui.config.py runs
migrations at import time and needs a working database).

The DB file is pre-created as an empty file so that alembic migrations
can initialize it properly on first import.

ENV VARS (override via shell or CI — do NOT hardcode in production):
  WEBUI_SECRET_KEY    — required, fail-fast if missing in CI
  SUPER_ADMIN_EMAILS  — required, fail-fast if missing in CI
  DATABASE_URL        — optional, defaults to local SQLite
"""

import os
import sys
import time

_CI = os.environ.get("CI", "").lower() in ("1", "true", "yes")


def _require_env(name: str, default: str | None = None) -> str:
    """Return env var value. Fail fast in CI if missing and no default."""
    val = os.environ.get(name)
    if val:
        return val
    if default is not None:
        return default
    if _CI:
        print(f"FATAL: required env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return ""


# Use direct assignment — Dockerfile sets WEBUI_SECRET_KEY="" which prevents setdefault from working
os.environ["WEBUI_SECRET_KEY"] = _require_env("WEBUI_SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ["SUPER_ADMIN_EMAILS"] = _require_env("SUPER_ADMIN_EMAILS", "test@example.com")

# Create empty DB file before setting DATABASE_URL — alembic migrations
# run at open_webui import time and need the file to exist
_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test_unit.db")
_TEST_DB_URI = f"sqlite:///{_TEST_DB_PATH}"
# Touch the file
open(_TEST_DB_PATH, "a").close()
os.environ.setdefault("DATABASE_URL", _TEST_DB_URI)

import pytest
from contextlib import contextmanager


# Unique prefix for this test run — used by integration tests to tag test data
TEST_RUN_PREFIX = f"test-unit-{int(time.time())}"


# Set asyncio_mode to auto so class-level @pytest.mark.asyncio propagates to methods
def pytest_configure(config):
    config.option.asyncio_mode = "auto"
    config.addinivalue_line("markers", "unit: unit tests (backend)")


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Tables are created by alembic at import time. Clean up after session."""
    yield
    # Clean up: remove the test DB file
    if os.path.exists(_TEST_DB_PATH):
        try:
            os.remove(_TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def cleanup_tables():
    """Clean all tables before each test to prevent state pollution."""
    from open_webui.internal.db import engine, Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    """Provide a clean DB session per test."""
    from open_webui.internal.db import get_db

    with get_db() as session:
        yield session
        session.rollback()


@pytest.fixture
def seed_user(db_session):
    """Create and return a test admin user. Cleans up after each test."""
    from open_webui.models.users import Users

    user = Users.insert_new_user(
        id="test-user-1",
        name="Test User",
        email="test@example.com",
        profile_image_url="/user.png",
        role="admin",
    )
    yield user
    # Clean up
    Users.delete_user_by_id("test-user-1")


@pytest.fixture
def seed_user_2(db_session):
    """Create and return a second test user (non-admin). Cleans up after each test."""
    from open_webui.models.users import Users

    user = Users.insert_new_user(
        id="test-user-2",
        name="Test User 2",
        email="test2@example.com",
        profile_image_url="/user.png",
        role="user",
    )
    yield user
    # Clean up
    Users.delete_user_by_id("test-user-2")


@pytest.fixture(scope="session")
def app():
    """Import the FastAPI app."""
    from open_webui.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
async def async_client(app):
    """Yield an httpx.AsyncClient bound to the FastAPI app."""
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_admin_user():
    """Yield a context manager that overrides auth with an admin user."""

    @contextmanager
    def _mock():
        from open_webui.main import app as fastapi_app
        from open_webui.utils.auth import (
            get_verified_user,
            get_admin_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id="admin-1",
                name="Admin",
                email="admin@test.com",
                role="admin",
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        fastapi_app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_admin_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        fastapi_app.dependency_overrides = {}

    return _mock


@pytest.fixture
def mock_regular_user():
    """Yield a context manager that overrides auth with a regular user."""

    @contextmanager
    def _mock():
        from open_webui.main import app as fastapi_app
        from open_webui.utils.auth import (
            get_verified_user,
            get_current_user,
            get_current_user_by_api_key,
        )
        from open_webui.models.users import User

        def create_user():
            return User(
                id="user-1",
                name="Regular User",
                email="user@test.com",
                role="user",
                profile_image_url="/user.png",
                last_active_at=0,
                updated_at=0,
                created_at=0,
            )

        fastapi_app.dependency_overrides = {
            get_current_user: create_user,
            get_verified_user: create_user,
            get_current_user_by_api_key: create_user,
        }
        yield
        fastapi_app.dependency_overrides = {}

    return _mock
