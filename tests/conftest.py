import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.core.database import get_engine

TEST_TOKEN = "test-only-token-with-at-least-32-characters"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "token")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEV_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    # Tests must never pick up a real school credential from the developer's .env.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", "")
    monkeypatch.setenv("SSH_KEY_DIRECTORY", str(tmp_path / "ssh-keys"))
    monkeypatch.setenv("SSH_KEY_PASSWORD", "")
    monkeypatch.setenv("PACKAGE_CACHE_DIRECTORY", str(tmp_path / "package-cache"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    instance = get_engine()
    yield instance
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
