from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.api.dependencies import Database
from backend.api.schemas.jobs import JobList, JobResponse
from backend.core.errors import AppError
from backend.models.tables import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobList)
def list_jobs(db: Database, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    items = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset))
    return {"items": list(items), "total": db.scalar(select(func.count()).select_from(Job))}


@router.post("/system-checks", response_model=JobResponse, status_code=202)
def enqueue_system_check(
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    job = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if job is not None:
        if job.kind != "SYSTEM_CHECK":
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return job
    job = Job(kind="SYSTEM_CHECK", idempotency_key=idempotency_key)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Database):
    job = db.get(Job, str(job_id))
    if job is None:
        raise AppError("JOB_NOT_FOUND", "작업을 찾을 수 없습니다.", 404)
    return job
