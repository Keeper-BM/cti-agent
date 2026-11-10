import pytest

from backend.core.worker_lock import sqlite_worker_lock


def test_second_sqlite_worker_cannot_recover_or_claim_active_jobs(tmp_path):
    path = tmp_path / "database.db"
    with sqlite_worker_lock(path), pytest.raises(RuntimeError, match="already running"):
        with sqlite_worker_lock(path):
            pytest.fail("A duplicate worker acquired the lock")
    with sqlite_worker_lock(path):
        pass
