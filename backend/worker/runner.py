import logging
import signal
from contextlib import contextmanager
from threading import Event

from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.auth.access import authorize_job
from backend.core.audit import audit
from backend.core.config import get_settings
from backend.core.database import get_engine
from backend.core.diagnostics import safe_exception_details
from backend.core.errors import AppError
from backend.core.worker_lock import sqlite_worker_lock
from backend.models.enums import JobStatus
from backend.models.tables import (
    CollectionRun,
    ExplanationRun,
    Job,
    QuestionRun,
    VerificationRun,
    utcnow,
)

logger = logging.getLogger(__name__)
WORKER_LOCK_ID = 81642026


@contextmanager
def single_worker(engine: Engine):
    """Hold an OS file lock for SQLite or a PostgreSQL session advisory lock."""
    if engine.dialect.name == "sqlite":
        with sqlite_worker_lock(engine.url.database):
            yield
        return
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            acquired = connection.scalar(text(f"SELECT pg_try_advisory_lock({WORKER_LOCK_ID})"))
            if not acquired:
                raise RuntimeError("A worker is already running. This starter uses one worker.")
        try:
            yield
        finally:
            if engine.dialect.name == "postgresql":
                connection.execute(text(f"SELECT pg_advisory_unlock({WORKER_LOCK_ID})"))


def recover_interrupted_jobs(engine: Engine) -> None:
    """Do not silently retry a job whose side effects are unknown."""
    with Session(engine) as db, db.begin():
        interrupted = db.execute(
            select(Job.id, Job.kind, Job.asset_id, Job.requested_by).where(
                Job.status == JobStatus.RUNNING
            )
        ).all()
        db.execute(
            update(Job)
            .where(Job.status == JobStatus.RUNNING)
            .values(
                status=JobStatus.FAILED,
                error_code="WORKER_RESTARTED",
                finished_at=utcnow(),
            )
        )
        for job in interrupted:
            audit(
                db,
                "job.interrupted",
                asset_id=job.asset_id,
                target_id=job.id,
                actor_id=job.requested_by,
                outcome="FAILED",
                details={"kind": job.kind, "error_code": "WORKER_RESTARTED"},
            )
        db.execute(
            update(QuestionRun)
            .where(
                QuestionRun.job_id.in_(
                    select(Job.id).where(Job.status.in_(["SUCCEEDED", "FAILED"]))
                )
            )
            .values(active_slot=None)
        )
        db.execute(
            update(ExplanationRun)
            .where(
                ExplanationRun.job_id.in_(
                    select(Job.id).where(Job.status.in_(["SUCCEEDED", "FAILED"]))
                )
            )
            .values(active_slot=None)
        )
        db.execute(
            update(CollectionRun)
            .where(
                CollectionRun.job_id.in_(
                    select(Job.id).where(Job.status.in_(["SUCCEEDED", "PARTIAL", "FAILED"]))
                )
            )
            .values(active_slot=None)
        )
        db.execute(
            update(VerificationRun)
            .where(
                VerificationRun.job_id.in_(
                    select(Job.id).where(Job.status.in_(["SUCCEEDED", "PARTIAL", "FAILED"]))
                )
            )
            .values(active_slot=None)
        )


def run_once(engine: Engine) -> bool:
    with Session(engine) as db, db.begin():
        job = db.scalar(
            select(Job)
            .where(Job.status == JobStatus.QUEUED)
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return False
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        job.attempts += 1
        job_id, kind = job.id, job.kind

    result = None
    error_code = None
    try:
        with Session(engine) as db:
            authorize_job(db, db.get(Job, job_id))
        if kind == "QUESTION":
            from backend.retrieval.service import answer_job

            result = answer_job(engine, job_id)
        elif kind == "COMPARISON":
            from backend.comparison.service import compare_job

            result = compare_job(engine, job_id)
        elif kind == "VERIFICATION":
            from backend.verification.service import verify_job

            result = verify_job(engine, job_id)
        elif kind == "SSH_COLLECTION":
            from backend.collectors.ssh_service import collect_job

            result = collect_job(engine, job_id)
        elif kind == "REPORT":
            from backend.reports.service import report_job

            result = report_job(engine, job_id)
        elif kind == "EXPLANATION":
            from backend.llm.service import explain_job

            result = explain_job(engine, job_id)
        elif kind == "ASSESSMENT":
            from backend.assessment.service import assess_job

            result = assess_job(engine, job_id)
        elif kind == "SOURCE_SYNC":
            from backend.sources.service import sync_source_job

            result = sync_source_job(engine, job_id)
        elif kind != "SYSTEM_CHECK":
            error_code = "UNSUPPORTED_JOB_TYPE"
        else:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            result = {
                "message": "API → DB → Worker 연결 확인 완료",
                "scope": "infrastructure_only",
            }
    except AppError as exc:
        error_code = exc.code
        result = {"message": exc.message}
    except Exception as exc:
        logger.error("Job failed; job_id=%s; %s", job_id, safe_exception_details(exc))
        error_code = "JOB_EXECUTION_FAILED"

    with Session(engine) as db, db.begin():
        # Domain services commit outputs and terminal status together; do not overwrite PARTIAL.
        completed = db.get(Job, job_id)
        if completed.status != "RUNNING":
            audit(
                db,
                "job.finished",
                asset_id=completed.asset_id,
                target_id=job_id,
                actor_id=completed.requested_by,
                outcome=completed.status,
                details={"kind": kind},
            )
            return True
        if kind == "SSH_COLLECTION":
            db.execute(
                update(CollectionRun).where(CollectionRun.job_id == job_id).values(active_slot=None)
            )
        if kind == "VERIFICATION":
            db.execute(
                update(VerificationRun)
                .where(VerificationRun.job_id == job_id)
                .values(active_slot=None)
            )
        if kind == "EXPLANATION":
            db.execute(
                update(ExplanationRun)
                .where(ExplanationRun.job_id == job_id)
                .values(active_slot=None)
            )
        if kind == "QUESTION":
            db.execute(
                update(QuestionRun).where(QuestionRun.job_id == job_id).values(active_slot=None)
            )
        db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.FAILED if error_code else JobStatus.SUCCEEDED,
                result=result,
                error_code=error_code,
                finished_at=utcnow(),
            )
        )
        audit(
            db,
            "job.finished",
            asset_id=completed.asset_id,
            target_id=job_id,
            actor_id=completed.requested_by,
            outcome="FAILED" if error_code else "SUCCEEDED",
            details={"kind": kind, "error_code": error_code},
        )
    logger.info("Job finished; job_id=%s status=%s", job_id, error_code or "SUCCEEDED")
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    settings = get_settings()
    engine = get_engine()
    try:
        with single_worker(engine):
            recover_interrupted_jobs(engine)
            logger.info(
                "Worker ready; enabled job types="
                "SYSTEM_CHECK,SOURCE_SYNC,ASSESSMENT,EXPLANATION,REPORT,SSH_COLLECTION,VERIFICATION,COMPARISON,QUESTION"
            )
            while not stop.is_set():
                if not run_once(engine):
                    stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()
