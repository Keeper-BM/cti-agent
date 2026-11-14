import os
from contextlib import nullcontext
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.core.database import get_engine
from tests.fixtures.database import temporary_postgres_database

TEST_TOKEN = "test-only-token-with-at-least-32-characters"

POSTGRES_MATRIX_FILES = {
    "integration/test_api.py",
    "integration/test_asset_csv.py",
    "integration/test_auth.py",
    "integration/test_collections.py",
    "integration/test_inventories.py",
    "integration/test_worker.py",
}


def pytest_addoption(parser):
    parser.addoption(
        "--postgres-matrix",
        action="store_true",
        help="Also run asset, inventory, auth, SSH and worker tests in fresh PostgreSQL databases",
    )


def pytest_configure(config):
    if config.getoption("--postgres-matrix") and not os.getenv("TEST_POSTGRES_URL"):
        raise pytest.UsageError("--postgres-matrix requires TEST_POSTGRES_URL with CREATEDB access")


def pytest_generate_tests(metafunc):
    if (
        metafunc.config.getoption("--postgres-matrix")
        and metafunc.definition.path.relative_to(Path(__file__).parent).as_posix()
        in POSTGRES_MATRIX_FILES
        and "engine" in metafunc.fixturenames
    ):
        metafunc.parametrize("engine", ["sqlite", "postgresql"], indirect=True)


@pytest.fixture
def engine(tmp_path, monkeypatch, request):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "token")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEV_API_TOKEN", TEST_TOKEN)
    # Tests must never pick up a real school credential from the developer's .env.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", "")
    monkeypatch.setenv("SSH_KEY_DIRECTORY", str(tmp_path / "ssh-keys"))
    monkeypatch.setenv("SSH_KEY_PASSWORD", "")
    monkeypatch.setenv("PACKAGE_CACHE_DIRECTORY", str(tmp_path / "package-cache"))
    database = (
        temporary_postgres_database(os.environ["TEST_POSTGRES_URL"])
        if getattr(request, "param", "sqlite") == "postgresql"
        else nullcontext(f"sqlite:///{tmp_path / 'test.db'}")
    )
    with database as url:
        monkeypatch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        get_engine.cache_clear()
        instance = None
        try:
            command.upgrade(Config("alembic.ini"), "head")
            instance = get_engine()
            yield instance
        finally:
            if instance is not None:
                instance.dispose()
            get_engine.cache_clear()
            get_settings.cache_clear()


@pytest.fixture
def client(engine):
    with TestClient(create_app()) as instance:
        yield instance


@pytest.fixture
def headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
