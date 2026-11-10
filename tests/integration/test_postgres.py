"""Runs in CI against pgvector; opt in locally using a disposable TEST_POSTGRES_URL."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.core.database import get_engine
from backend.models.tables import Job
from backend.worker.runner import run_once, single_worker


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="Requires a disposable PostgreSQL DB"
)
def test_postgres_migration_pgvector_worker_and_singleton(monkeypatch):
    token = "postgres-test-only-token-at-least-32-characters"
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setenv("DEV_API_TOKEN", token)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "token")
    get_engine.cache_clear()
    get_settings.cache_clear()
    engine = get_engine()
    job_id = None
    try:
        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
        with TestClient(create_app()) as client:
            headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}
            assert client.get("/api/v1/readiness").status_code == 200
            response = client.post("/api/v1/jobs/system-checks", headers=headers)
            assert response.status_code == 202
            job_id = response.json()["id"]
            with single_worker(engine):
                with pytest.raises(RuntimeError, match="already running"), single_worker(engine):
                    pass
                assert run_once(engine)
            assert (
                client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["status"]
                == "SUCCEEDED"
            )
    finally:
        if job_id:
            with Session(engine) as db, db.begin():
                db.execute(delete(Job).where(Job.id == job_id))
        engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
