from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.schemas.explanations import (
    ExplanationList,
    ExplanationRequest,
    ExplanationResponse,
    LLMStatus,
)
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.llm.client import configuration_issue, require_configuration
from backend.llm.context import context_digest, prepare_context
from backend.llm.contracts import PROMPT_VERSION, SCHOOL_BASE_URL
from backend.models.tables import Asset, ExplanationRun, FindingRecord, Job

router = APIRouter(prefix="/explanations", tags=["explanations"])


def response(run, db):
    return {
        **{key: getattr(run, key) for key in ExplanationResponse.model_fields if key != "job"},
        "job": db.get(Job, run.job_id),
    }


@router.get("/status", response_model=LLMStatus)
def status():
    settings = get_settings()
    issue = configuration_issue(settings)
    return {
        "configured": issue is None,
        "model": settings.llm_model if issue is None else None,
        "message": issue or "설정 완료. 설명 생성 요청 시 학교 API에 연결합니다.",
    }


@router.post("", response_model=ExplanationResponse, status_code=202)
def create_explanation(
    payload: ExplanationRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        run = db.scalar(select(ExplanationRun).where(ExplanationRun.job_id == existing.id))
        if run is None or run.finding_id != str(payload.finding_id):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(run, db)
    finding = db.get(FindingRecord, str(payload.finding_id))
    if finding is None:
        raise AppError("FINDING_NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    if not db.get(Asset, finding.asset_id).is_active:
        raise AppError(
            "ASSET_INACTIVE", "비활성 자산입니다. 저장된 설명은 계속 조회할 수 있습니다.", 409
        )
    pending = db.scalar(
        select(ExplanationRun)
        .join(Job, Job.id == ExplanationRun.job_id)
        .where(Job.status.in_(["QUEUED", "RUNNING"]))
    )
    if pending:
        raise AppError("LLM_BUSY", "AI 설명 작업을 처리 중입니다. 완료 후 요청하세요.", 409)
    settings = get_settings()
    require_configuration(settings)
    context = prepare_context(db, finding)
    job = Job(kind="EXPLANATION", asset_id=finding.asset_id, idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        run = ExplanationRun(
            active_slot="school",
            job_id=job.id,
            finding_id=finding.id,
            analysis_id=finding.analysis_id,
            provider="dcu",
            base_url=SCHOOL_BASE_URL,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION,
            context_sha256=context_digest(context),
            input_payload=context.model_dump(mode="json"),
        )
        db.add(run)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "EXPLANATION_CONFLICT", "중복 요청입니다. 같은 요청 키로 다시 확인하세요.", 409
        ) from None
    db.refresh(run)
    return response(run, db)


@router.get("", response_model=ExplanationList)
def list_explanations(
    db: Database,
    finding_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    if db.get(FindingRecord, str(finding_id)) is None:
        raise AppError("FINDING_NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    condition = ExplanationRun.finding_id == str(finding_id)
    runs = db.scalars(
        select(ExplanationRun)
        .options(defer(ExplanationRun.input_payload))
        .where(condition)
        .order_by(ExplanationRun.created_at.desc(), ExplanationRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(run, db) for run in runs],
        "total": db.scalar(select(func.count()).select_from(ExplanationRun).where(condition)),
    }


@router.get("/{explanation_id}", response_model=ExplanationResponse)
def get_explanation(explanation_id: UUID, db: Database):
    run = db.get(ExplanationRun, str(explanation_id))
    if run is None:
        raise AppError("EXPLANATION_NOT_FOUND", "저장된 설명을 찾을 수 없습니다.", 404)
    return response(run, db)
