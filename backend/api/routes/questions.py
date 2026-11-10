from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.routes.findings import find_analysis
from backend.api.schemas.questions import (
    QuestionDetail,
    QuestionList,
    QuestionRequest,
    QuestionResponse,
)
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.llm.client import require_configuration
from backend.models.tables import Asset, Job, QuestionAsset, QuestionRun
from backend.retrieval.context import prepare, sha
from backend.retrieval.contracts import PROMPT_VERSION

router = APIRouter(prefix="/questions", tags=["questions"])


def response(row, db):
    return {
        **{k: getattr(row, k) for k in QuestionResponse.model_fields if k != "job"},
        "job": db.get(Job, row.job_id),
    }


@router.post("", response_model=QuestionResponse, status_code=202)
def create(
    payload: QuestionRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    ids = sorted(str(i) for i in payload.analysis_ids)
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        run = db.scalar(select(QuestionRun).where(QuestionRun.job_id == existing.id))
        if not run or sorted(run.analysis_ids) != ids or run.question != payload.question:
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(run, db)
    analyses = [find_analysis(i, db) for i in ids]
    for analysis in analyses:
        if not analysis.completed_at or db.get(Job, analysis.job_id).status != "SUCCEEDED":
            raise AppError("ANALYSIS_NOT_COMPLETED", "완료된 분석만 선택하세요.", 409)
        if not db.get(Asset, analysis.asset_id).is_active:
            raise AppError("ASSET_INACTIVE", "비활성 자산은 저장된 답변만 조회할 수 있습니다.", 409)
    try:
        context = prepare(db, payload.question, analyses)
        settings = get_settings()
        if not context.insufficient_evidence:
            require_configuration(settings)
        job = Job(kind="QUESTION", asset_id=analyses[0].asset_id, idempotency_key=idempotency_key)
        db.add(job)
        db.flush()
        wire = context.model_dump(mode="json")
        run = QuestionRun(
            job_id=job.id,
            asset_id=analyses[0].asset_id,
            question=payload.question,
            analysis_ids=ids,
            model=settings.llm_model if not context.insufficient_evidence else "none",
            prompt_version=PROMPT_VERSION,
            context_sha256=sha(wire),
            input_payload=wire,
            active_slot="school",
        )
        db.add(run)
        db.flush()
        for asset in set(a.asset_id for a in analyses):
            db.add(QuestionAsset(question_id=run.id, asset_id=asset))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "QUESTION_BUSY",
            "질문 작업을 처리 중이거나 중복 요청입니다. 완료 후 다시 시도하세요.",
            409,
        ) from None
    db.refresh(run)
    return response(run, db)


@router.get("", response_model=QuestionList)
def listing(
    db: Database,
    asset_id: UUID | None = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = (
        []
        if asset_id is None
        else [
            QuestionRun.id.in_(
                select(QuestionAsset.question_id).where(QuestionAsset.asset_id == str(asset_id))
            )
        ]
    )
    rows = db.scalars(
        select(QuestionRun)
        .options(defer(QuestionRun.input_payload), defer(QuestionRun.result))
        .where(*filters)
        .order_by(QuestionRun.created_at.desc(), QuestionRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(r, db) for r in rows],
        "total": db.scalar(select(func.count()).select_from(QuestionRun).where(*filters)),
    }


@router.get("/{question_id}", response_model=QuestionDetail)
def detail(question_id: UUID, db: Database):
    run = db.get(QuestionRun, str(question_id))
    if not run:
        raise AppError("QUESTION_NOT_FOUND", "질문 기록을 찾을 수 없습니다.", 404)
    return {**response(run, db), "result": run.result, "usage": run.usage}
