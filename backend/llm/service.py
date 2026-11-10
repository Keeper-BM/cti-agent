from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.llm.client import SchoolLLM, require_configuration
from backend.llm.context import context_digest
from backend.llm.contracts import PROMPT_VERSION, SCHOOL_BASE_URL, ExplanationContext
from backend.llm.prompt import messages
from backend.llm.validation import validate_output
from backend.models.tables import ExplanationRun, Job, utcnow


def explain_job(engine: Engine, job_id: str) -> dict:
    settings = get_settings()
    with Session(engine) as db:
        run = db.scalar(select(ExplanationRun).where(ExplanationRun.job_id == job_id))
        if run is None:
            raise AppError("EXPLANATION_NOT_FOUND", "설명 생성 입력을 찾을 수 없습니다.", 500)
        if run.completed_at:
            return db.get(Job, job_id).result
        require_configuration(settings)
        if (
            run.model != settings.llm_model
            or run.prompt_version != PROMPT_VERSION
            or run.base_url != SCHOOL_BASE_URL
        ):
            raise AppError(
                "LLM_CONFIG_CHANGED", "모델·설명 규칙이 변경되었습니다. 새로 요청하세요.", 409
            )
        context = ExplanationContext.model_validate(run.input_payload)
        if context_digest(context) != run.context_sha256:
            raise AppError(
                "LLM_CONTEXT_CHANGED", "고정한 설명 입력의 무결성을 확인할 수 없습니다.", 409
            )
        run_id = run.id
    # Network work occurs without holding a database transaction or write lock.
    reply = SchoolLLM(settings).generate(messages(context))
    output = validate_output(reply.content, context)
    with Session(engine) as db, db.begin():
        run = db.get(ExplanationRun, run_id)
        job = db.get(Job, job_id)
        if run.completed_at:
            return job.result
        if job.status != "RUNNING":
            raise AppError(
                "LLM_JOB_INTERRUPTED", "설명 작업이 중단되어 결과를 저장하지 않았습니다.", 409
            )
        run.result = output.model_dump(mode="json")
        run.usage = reply.usage
        run.reported_model = reply.model
        run.completed_at = utcnow()
        run.active_slot = None
        result = {"message": "검증한 AI 설명을 저장했습니다.", "explanation_id": run.id}
        job.status, job.result, job.finished_at = "SUCCEEDED", result, run.completed_at
    return result
