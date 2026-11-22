"""Prepare one optional, grounded AI summary as part of a report job."""

from uuid import uuid4

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.llm.client import configuration_issue
from backend.llm.context import context_digest, prepare_context
from backend.llm.contracts import PROMPT_VERSION
from backend.llm.service import generate_explanation
from backend.models.tables import Asset, FindingRecord, utcnow
from backend.reports.contracts import (
    AutomaticSummaryInput,
    ReportContent,
    ReportExplanation,
    ReportInput,
)


def pin_report_input(db, report: ReportContent, generate_ai_summary: bool) -> ReportInput:
    inputs = ReportInput(report=report, generate_ai_summary=generate_ai_summary)
    if not generate_ai_summary:
        return inputs

    target = report.priority_finding_id
    if target is None:
        report.ai_summary_note = "영향 있음 또는 추가 확인이 필요한 판정이 없습니다."
        return inputs
    if any(summary.finding_id == target for summary in report.explanations):
        return inputs

    settings = get_settings()
    if not db.get(Asset, str(report.asset_id)).is_active:
        report.ai_summary_note = "비활성 자산의 저장 자료로 보고서를 만들었습니다."
        return inputs
    if configuration_issue(settings):
        report.ai_summary_note = "학교 AI 연결 설정을 확인한 뒤 요약을 생성할 수 있습니다."
        return inputs

    try:
        context = prepare_context(db, db.get(FindingRecord, str(target)))
    except AppError:
        report.ai_summary_note = "대표 판정에 AI 요약을 생성할 공식 근거가 충분하지 않습니다."
        return inputs
    inputs.summary = AutomaticSummaryInput(
        finding_id=target, model=settings.llm_model, prompt_version=PROMPT_VERSION, context=context
    )
    return inputs


def append_automatic_summary(report: ReportContent, inputs: AutomaticSummaryInput) -> None:
    settings = get_settings()
    if inputs.model != settings.llm_model or inputs.prompt_version != PROMPT_VERSION:
        report.ai_summary_note = "요청 후 학교 AI 설정이 바뀌어 새 요약을 생성하지 못했습니다."
        return

    try:
        reply, output = generate_explanation(settings, inputs.context)
    except AppError as error:
        report.ai_summary_note = f"새 AI 요약 생성 실패 ({error.code}). {error.message}"
        return

    report.explanations.append(
        ReportExplanation(
            id=uuid4(),
            finding_id=inputs.finding_id,
            model=inputs.model,
            reported_model=reply.model,
            prompt_version=inputs.prompt_version,
            context_sha256=context_digest(inputs.context),
            completed_at=utcnow(),
            result=output,
        )
    )
