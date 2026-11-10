"""Create frozen reports, browse history and download stored UTF-8 Markdown."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.schemas.reports import ReportDetail, ReportList, ReportRequest, ReportResponse
from backend.core.errors import AppError
from backend.models.tables import AnalysisRun, Job, ReportRun, utcnow
from backend.reports.contracts import TEMPLATE_VERSION
from backend.reports.snapshot import digest, freeze_report

router = APIRouter(prefix="/reports", tags=["reports"])


def response(report, db):
    return {
        **{k: getattr(report, k) for k in ReportResponse.model_fields if k != "job"},
        "job": db.get(Job, report.job_id),
    }


def find_report(report_id, db):
    report = db.get(ReportRun, str(report_id))
    if report is None:
        raise AppError("REPORT_NOT_FOUND", "보고서를 찾을 수 없습니다.", 404)
    return report


@router.post("", response_model=ReportResponse, status_code=202)
def create_report(
    payload: ReportRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        report = db.scalar(select(ReportRun).where(ReportRun.job_id == existing.id))
        if (
            report is None
            or report.analysis_id != str(payload.analysis_id)
            or (report.include_ai_explanations != payload.include_ai_explanations)
        ):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(report, db)
    analysis = db.get(AnalysisRun, str(payload.analysis_id))
    if analysis is None:
        raise AppError("ANALYSIS_NOT_FOUND", "보고서로 만들 분석을 찾을 수 없습니다.", 404)
    if not analysis.completed_at or db.get(Job, analysis.job_id).status != "SUCCEEDED":
        raise AppError("ANALYSIS_NOT_COMPLETED", "완료된 분석만 보고서로 만들 수 있습니다.", 409)
    report_id, frozen_at = uuid4(), utcnow()
    content = freeze_report(db, analysis, report_id, frozen_at, payload.include_ai_explanations)
    pinned = content.model_dump(mode="json")
    input_hash = digest(pinned)
    job = Job(kind="REPORT", asset_id=analysis.asset_id, idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        report = ReportRun(
            id=str(report_id),
            job_id=job.id,
            analysis_id=analysis.id,
            asset_id=analysis.asset_id,
            asset_name=content.asset_name,
            is_synthetic=content.is_synthetic,
            include_ai_explanations=payload.include_ai_explanations,
            explanation_count=len(content.explanations),
            finding_count=len(content.findings),
            template_version=TEMPLATE_VERSION,
            input_sha256=input_hash,
            input_payload=pinned,
            created_at=frozen_at,
        )
        db.add(report)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "REPORT_CONFLICT", "중복 요청입니다. 같은 요청 키로 다시 확인하세요.", 409
        ) from None
    db.refresh(report)
    return response(report, db)


@router.get("", response_model=ReportList)
def list_reports(
    db: Database,
    asset_id: UUID | None = None,
    analysis_id: UUID | None = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conditions = []
    if asset_id:
        conditions.append(ReportRun.asset_id == str(asset_id))
    if analysis_id:
        conditions.append(ReportRun.analysis_id == str(analysis_id))
    reports = db.scalars(
        select(ReportRun)
        .options(
            defer(ReportRun.input_payload), defer(ReportRun.content), defer(ReportRun.markdown)
        )
        .where(*conditions)
        .order_by(ReportRun.created_at.desc(), ReportRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(r, db) for r in reports],
        "total": db.scalar(select(func.count()).select_from(ReportRun).where(*conditions)),
    }


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: UUID, db: Database):
    report = find_report(report_id, db)
    return {**response(report, db), "content": report.content}


@router.get(
    "/{report_id}/markdown",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}},
)
def download_report(report_id: UUID, db: Database):
    report = find_report(report_id, db)
    if (
        not report.completed_at
        or report.markdown is None
        or db.get(Job, report.job_id).status != "SUCCEEDED"
    ):
        raise AppError("REPORT_NOT_READY", "완료된 보고서만 내려받을 수 있습니다.", 409)
    return Response(
        content=report.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cti-report-{report.id}.md"',
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": report.markdown_sha256,
        },
    )
