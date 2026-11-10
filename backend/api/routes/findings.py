"""Queue frozen analyses and query immutable findings and source evidence."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.routes.sources import record_response, records_query
from backend.api.schemas.findings import (
    AnalysisList,
    AnalysisRequest,
    AnalysisResponse,
    FindingDetail,
    FindingList,
)
from backend.assessment.service import pin_inputs
from backend.core.errors import AppError
from backend.models.enums import ProcessingStatus, Verdict
from backend.models.tables import (
    AnalysisRun,
    Asset,
    FindingRecord,
    InventoryRecord,
    Job,
    SecuritySnapshot,
    SourceRecord,
)

router = APIRouter(tags=["assessment"])


def analysis_response(analysis, db):
    data = {
        name: getattr(analysis, name)
        for name in AnalysisResponse.model_fields
        if name not in {"job", "sources"}
    }
    data["job"] = db.get(Job, analysis.job_id)
    data["sources"] = list(
        db.scalars(
            select(SecuritySnapshot)
            .where(SecuritySnapshot.id.in_(analysis.source_snapshot_ids))
            .order_by(SecuritySnapshot.source_id, SecuritySnapshot.scope_key)
        )
    )
    return data


def find_analysis(analysis_id, db):
    value = db.get(AnalysisRun, str(analysis_id))
    if value is None:
        raise AppError("ANALYSIS_NOT_FOUND", "분석 기록을 찾을 수 없습니다.", 404)
    return value


@router.post("/analyses", response_model=AnalysisResponse, status_code=202)
def create_analysis(
    payload: AnalysisRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        analysis = db.scalar(select(AnalysisRun).where(AnalysisRun.job_id == existing.id))
        if analysis is None or analysis.inventory_id != str(payload.inventory_id):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return analysis_response(analysis, db)
    inventory = db.get(InventoryRecord, str(payload.inventory_id))
    if inventory is None:
        raise AppError("INVENTORY_NOT_FOUND", "분석할 패키지 입력 기록을 찾을 수 없습니다.", 404)
    if not db.get(Asset, inventory.asset_id).is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산입니다. 활성화한 뒤 분석하세요.", 409)
    job = Job(kind="ASSESSMENT", asset_id=inventory.asset_id, idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        analysis = pin_inputs(db, inventory, job)
        db.add(analysis)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "ANALYSIS_CONFLICT", "중복 요청입니다. 같은 요청 키로 다시 확인하세요.", 409
        ) from None
    db.refresh(analysis)
    return analysis_response(analysis, db)


@router.get("/analyses", response_model=AnalysisList)
def list_analyses(
    db: Database,
    asset_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conditions = [] if asset_id is None else [AnalysisRun.asset_id == str(asset_id)]
    items = db.scalars(
        select(AnalysisRun)
        .options(defer(AnalysisRun.feed_payload))
        .where(*conditions)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [analysis_response(a, db) for a in items],
        "total": db.scalar(select(func.count()).select_from(AnalysisRun).where(*conditions)),
    }


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: UUID, db: Database):
    return analysis_response(find_analysis(analysis_id, db), db)


@router.get("/findings", response_model=FindingList)
def list_findings(
    db: Database,
    analysis_id: UUID | None = None,
    asset_id: UUID | None = None,
    verdict: Verdict | None = None,
    processing_status: ProcessingStatus | None = None,
    search: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conditions = []
    if analysis_id:
        find_analysis(analysis_id, db)
        conditions.append(FindingRecord.analysis_id == str(analysis_id))
    if asset_id:
        conditions.append(FindingRecord.asset_id == str(asset_id))
    if verdict:
        conditions.append(FindingRecord.verdict == verdict)
    if processing_status:
        conditions.append(FindingRecord.processing_status == processing_status)
    if search.strip():
        conditions.append(
            or_(
                FindingRecord.cve_id.icontains(search.strip(), autoescape=True),
                FindingRecord.package_name.icontains(search.strip(), autoescape=True),
            )
        )
    # Apply display priority before pagination, including when a search is active.
    priority = case(
        {
            Verdict.AFFECTED: 0,
            Verdict.NEEDS_REVIEW: 1,
            Verdict.FIXED: 2,
            Verdict.NOT_AFFECTED: 3,
            ProcessingStatus.COLLECTION_FAILED: 4,
            ProcessingStatus.PARTIAL_COLLECTION: 5,
            ProcessingStatus.NO_MATCHING_RECORD: 6,
            ProcessingStatus.NOT_INSTALLED: 7,
            ProcessingStatus.OUT_OF_SCOPE: 9,
        },
        value=func.coalesce(FindingRecord.verdict, FindingRecord.processing_status),
        else_=8,
    )
    items = db.scalars(
        select(FindingRecord)
        .where(*conditions)
        .order_by(
            priority,
            func.coalesce(FindingRecord.cve_id, ""),
            func.coalesce(FindingRecord.package_name, ""),
            FindingRecord.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [r.payload for r in items],
        "total": db.scalar(select(func.count()).select_from(FindingRecord).where(*conditions)),
    }


@router.get("/findings/{finding_id}", response_model=FindingDetail)
def get_finding(finding_id: UUID, db: Database):
    finding = db.get(FindingRecord, str(finding_id))
    if finding is None:
        raise AppError("FINDING_NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    analysis = db.get(AnalysisRun, finding.analysis_id)
    rows = (
        db.execute(
            records_query()
            .where(
                SourceRecord.snapshot_id.in_(analysis.source_snapshot_ids),
                SourceRecord.cve_id == finding.cve_id,
            )
            .order_by(SourceRecord.source_id, SourceRecord.id)
        )
        if finding.cve_id
        else []
    )
    kev = db.scalar(
        select(SecuritySnapshot).where(
            SecuritySnapshot.id.in_(analysis.source_snapshot_ids),
            SecuritySnapshot.source_id == "kev",
        )
    )
    source_order = {"ubuntu": 0, "nvd": 1, "kev": 2, "apache": 3, "oracle": 4}
    related = sorted(rows, key=lambda row: (source_order[row[0].source_id], row[0].id))
    return {
        **finding.payload,
        "related_records": [record_response(row) for row in related],
        "kev_snapshot": kev,
    }
