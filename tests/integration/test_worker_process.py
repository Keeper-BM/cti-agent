"""Crash/restart a real Worker process using only a temporary DB and loopback SSH."""

import os
import subprocess
import sys
import time
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.tables import AuditEvent
from backend.worker.runner import run_once
from tests.integration import test_collections as collection_tests

lab = collection_tests.lab


@contextmanager
def worker_process(log_path):
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.worker"],
            env={**os.environ, "WORKER_POLL_SECONDS": "0.1", "PYTHONUNBUFFERED": "1"},
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_worker_process_crash_audits_interruption_and_preserves_previous_snapshot(
    client, headers, engine, lab, tmp_path
):
    server, asset, profile, _ = lab

    def detail(run):
        return collection_tests.get_run(client, headers, asset, run)

    def enqueue():
        return collection_tests.enqueue(client, headers, asset, profile)

    def wait_for(run, status, process):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert process.poll() is None, "Worker exited before reaching the expected state"
            result = detail(run)
            if result["job"]["status"] == status:
                return result
            time.sleep(0.05)
        raise AssertionError(f"Expected {status}; last job state: {result['job']['status']}")

    first = enqueue()
    assert run_once(engine)
    saved = detail(first)
    assert saved["job"]["status"] == "SUCCEEDED"
    inventory_path = f"/api/v1/assets/{asset['id']}/inventories/{saved['inventory_id']}"
    inventory = client.get(inventory_path, headers=headers).json()
    server.slow = True
    interrupted = enqueue()
    with worker_process(tmp_path / "first-worker.log") as process:
        wait_for(interrupted, "RUNNING", process)
        duplicate = subprocess.run(
            [sys.executable, "-m", "backend.worker"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert duplicate.returncode != 0 and "already running" in duplicate.stderr
        assert detail(interrupted)["job"]["status"] == "RUNNING"
        process.kill()  # Simulate a crash, not the normal graceful SIGTERM path.
        process.wait(timeout=5)
    assert detail(interrupted)["job"]["status"] == "RUNNING"

    server.slow = False
    with worker_process(tmp_path / "restarted-worker.log") as process:
        failed = wait_for(interrupted, "FAILED", process)
        assert failed["job"]["error_code"] == "WORKER_RESTARTED"
        assert failed["inventory_id"] is None and failed["job"]["attempts"] == 1
        assert detail(first) == saved
        assert client.get(inventory_path, headers=headers).json() == inventory
        retry = enqueue()  # Recovery released the asset's active collection slot.
        assert wait_for(retry, "SUCCEEDED", process)["inventory_id"] is not None
    with Session(engine) as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "job.interrupted")).all()
        assert len(events) == 1
        assert events[0].asset_id == asset["id"]
        assert events[0].target_id == interrupted["job"]["id"]
        assert events[0].details == {"kind": "SSH_COLLECTION", "error_code": "WORKER_RESTARTED"}
    assert (
        client.get(f"/api/v1/assets/{asset['id']}/inventories", headers=headers).json()["total"]
        == 2
    )
