import logging
import signal
from contextlib import contextmanager
from threading import Event

from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.database import get_engine
from backend.core.diagnostics import safe_exception_details
from backend.models.enums import JobStatus
from backend.models.tables import Job, utcnow

logger = logging.getLogger(__name__)
WORKER_LOCK_ID = 81642026


@contextmanager
def single_worker(engine: Engine):
    """Hold a PostgreSQL session lock; local SQLite requires one worker by convention."""
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
        db.execute(
            update(Job)
            .where(Job.status == JobStatus.RUNNING)
            .values(
                status=JobStatus.FAILED,
                error_code="WORKER_RESTARTED",
                finished_at=utcnow(),
            )
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
        if kind != "SYSTEM_CHECK":
            error_code = "UNSUPPORTED_JOB_TYPE"
        else:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            result = {
                "message": "API → DB → Worker 연결 확인 완료",
                "scope": "infrastructure_only",
            }
    except Exception as exc:
        logger.error("Job failed; job_id=%s; %s", job_id, safe_exception_details(exc))
        error_code = "JOB_EXECUTION_FAILED"

    with Session(engine) as db, db.begin():
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
            logger.info("Worker ready; enabled job type=SYSTEM_CHECK")
            while not stop.is_set():
                if not run_once(engine):
                    stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()
