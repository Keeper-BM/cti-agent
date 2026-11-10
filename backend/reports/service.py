import hashlib

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.models.tables import Job, ReportRun, utcnow
from backend.reports.contracts import MAX_REPORT_BYTES, TEMPLATE_VERSION, ReportContent
from backend.reports.markdown import render_markdown
from backend.reports.snapshot import digest


def report_job(engine: Engine, job_id: str) -> dict:
    with Session(engine) as db:
        report = db.scalar(select(ReportRun).where(ReportRun.job_id == job_id))
        if report is None:
            raise AppError("REPORT_NOT_FOUND", "보고서 입력을 찾을 수 없습니다.", 500)
        if report.completed_at:
            return db.get(Job, job_id).result
        if report.template_version != TEMPLATE_VERSION:
            raise AppError(
                "REPORT_TEMPLATE_CHANGED", "보고서 양식이 변경되었습니다. 새로 요청하세요.", 409
            )
        if digest(report.input_payload) != report.input_sha256:
            raise AppError(
                "REPORT_INPUT_CHANGED", "고정한 보고서 입력의 무결성을 확인하지 못했습니다.", 409
            )
        content = ReportContent.model_validate(report.input_payload)
        report_id = report.id
    content.generated_at = utcnow()
    markdown = render_markdown(content)
    data = markdown.encode("utf-8")
    if len(data) > MAX_REPORT_BYTES:
        raise AppError("REPORT_SIZE_LIMIT", "생성한 보고서가 16 MiB 제한을 초과합니다.", 422)
    with Session(engine) as db, db.begin():
        report = db.get(ReportRun, report_id)
        job = db.get(Job, job_id)
        if report.completed_at:
            return job.result
        if job.status != "RUNNING":
            raise AppError("REPORT_INTERRUPTED", "보고서 작업이 중단되어 저장하지 않았습니다.", 409)
        report.content = content.model_dump(mode="json")
        report.markdown = markdown
        report.markdown_sha256 = hashlib.sha256(data).hexdigest()
        report.completed_at = content.generated_at
        result = {"message": "분석 결과를 고정한 보고서를 저장했습니다.", "report_id": report_id}
        job.status, job.result, job.finished_at = "SUCCEEDED", result, report.completed_at
    return result
