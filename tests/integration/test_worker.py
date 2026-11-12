import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.tables import AuditEvent, Job, utcnow
from backend.worker.runner import recover_interrupted_jobs, run_once


def test_api_to_worker_pipeline(client, headers, engine):
    response = client.post(
        "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "worker-check"}
    )
    job_id = response.json()["id"]
    assert run_once(engine) is True
    result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
    assert result["status"] == "SUCCEEDED"
    assert result["attempts"] == 1
    assert result["result"]["scope"] == "infrastructure_only"
    assert result["started_at"] and result["finished_at"]
    assert run_once(engine) is False


def test_unknown_job_fails_instead_of_reporting_success(engine):
    with Session(engine) as db, db.begin():
        db.add(Job(kind="UNIMPLEMENTED_COLLECTION", idempotency_key="unknown"))
    run_once(engine)
    with Session(engine) as db:
        job = db.scalar(select(Job))
        assert job.status == "FAILED"
        assert job.error_code == "UNSUPPORTED_JOB_TYPE"


def test_restart_records_interrupted_work_and_preserves_completed_jobs(engine):
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Job(kind="SYSTEM_CHECK", idempotency_key="running", status="RUNNING"),
                Job(
                    kind="SYSTEM_CHECK",
                    idempotency_key="done",
                    status="SUCCEEDED",
                    finished_at=utcnow(),
                    result={"previous": True},
                ),
                Job(kind="SYSTEM_CHECK", idempotency_key="queued", status="QUEUED"),
            ]
        )
    recover_interrupted_jobs(engine)
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        records = {job.idempotency_key: job for job in db.scalars(select(Job))}
        assert records["running"].status == "FAILED"
        assert records["running"].error_code == "WORKER_RESTARTED"
        assert records["done"].result == {"previous": True}
        assert records["done"].status == "SUCCEEDED"
        assert records["queued"].status == "QUEUED"
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "job.interrupted")).all()
        assert len(events) == 1
        assert events[0].target_id == records["running"].id
        assert events[0].outcome == "FAILED"
        assert events[0].details == {"kind": "SYSTEM_CHECK", "error_code": "WORKER_RESTARTED"}


def test_recovery_audit_and_status_change_are_atomic(engine, monkeypatch):
    with Session(engine) as db, db.begin():
        job = Job(kind="SYSTEM_CHECK", idempotency_key="running", status="RUNNING")
        db.add(job)
        db.flush()
        job_id = job.id

    def unavailable_audit(*args, **kwargs):
        raise RuntimeError("simulated audit storage failure")

    monkeypatch.setattr("backend.worker.runner.audit", unavailable_audit)
    with pytest.raises(RuntimeError, match="audit storage"):
        recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert db.get(Job, job_id).status == "RUNNING"
        assert db.get(Job, job_id).error_code is None
        assert db.scalars(select(AuditEvent)).all() == []
