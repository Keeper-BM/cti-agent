from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.routes.findings import find_analysis
from backend.api.schemas.comparisons import (
    ComparisonDetail,
    ComparisonList,
    ComparisonRequest,
    ComparisonResponse,
)
from backend.comparison.contracts import VERSION
from backend.comparison.service import digest, pin
from backend.core.errors import AppError
from backend.models.tables import ComparisonRun, InventoryRecord, Job

router = APIRouter(prefix="/comparisons", tags=["comparisons"])


def response(row, db):
    return {
        **{k: getattr(row, k) for k in ComparisonResponse.model_fields if k != "job"},
        "job": db.get(Job, row.job_id),
    }


@router.post("", response_model=ComparisonResponse, status_code=202)
def create(
    payload: ComparisonRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    old = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if old:
        row = db.scalar(select(ComparisonRun).where(ComparisonRun.job_id == old.id))
        if (
            not row
            or row.baseline_analysis_id != str(payload.baseline_analysis_id)
            or row.target_inventory_id != str(payload.target_inventory_id)
        ):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(row, db)
    analysis = find_analysis(payload.baseline_analysis_id, db)
    if (
        not analysis.completed_at
        or not analysis.feed_payload
        or db.get(Job, analysis.job_id).status != "SUCCEEDED"
    ):
        raise AppError("ANALYSIS_NOT_COMPLETED", "완료된 분석을 기준으로 선택하세요.", 409)
    target = db.get(InventoryRecord, str(payload.target_inventory_id))
    if not target or target.asset_id != analysis.asset_id:
        raise AppError("INVENTORY_NOT_FOUND", "이 자산의 비교할 입력 기록이 없습니다.", 404)
    data = pin(db, analysis, target).model_dump(mode="json")
    sha = digest(data)
    job = Job(kind="COMPARISON", asset_id=analysis.asset_id, idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        row = ComparisonRun(
            job_id=job.id,
            asset_id=analysis.asset_id,
            baseline_analysis_id=analysis.id,
            target_inventory_id=target.inventory_id,
            version=VERSION,
            input_payload=data,
            input_sha256=sha,
        )
        db.add(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "COMPARISON_CONFLICT", "중복 요청입니다. 작업 상태를 확인하세요.", 409
        ) from None
    db.refresh(row)
    return response(row, db)


@router.get("", response_model=ComparisonList)
def listing(
    db: Database,
    asset_id: UUID | None = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = [] if asset_id is None else [ComparisonRun.asset_id == str(asset_id)]
    rows = db.scalars(
        select(ComparisonRun)
        .options(defer(ComparisonRun.input_payload), defer(ComparisonRun.result))
        .where(*filters)
        .order_by(ComparisonRun.created_at.desc(), ComparisonRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(r, db) for r in rows],
        "total": db.scalar(select(func.count()).select_from(ComparisonRun).where(*filters)),
    }


@router.get("/{comparison_id}", response_model=ComparisonDetail)
def detail(comparison_id: UUID, db: Database):
    row = db.get(ComparisonRun, str(comparison_id))
    if not row:
        raise AppError("COMPARISON_NOT_FOUND", "비교 기록을 찾을 수 없습니다.", 404)
    return {**response(row, db), "result": row.result}
