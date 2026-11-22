"""Single-analysis report requests, summaries and frozen previews."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, StrictBool, model_validator

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.models.contracts import Contract
from backend.reports.contracts import ReportContent


class ReportRequest(Contract):
    analysis_id: UUID
    include_ai_explanations: StrictBool = False
    generate_ai_summary: StrictBool = False

    @model_validator(mode="after")
    def check_summary_option(self):
        if self.generate_ai_summary and not self.include_ai_explanations:
            raise ValueError("AI 요약을 생성하려면 보고서에 AI 요약을 포함해야 합니다.")
        return self


class ReportResponse(TimestampResponse):
    id: UUID
    job: JobResponse
    analysis_id: UUID
    asset_id: UUID
    asset_name: str
    is_synthetic: bool
    include_ai_explanations: bool
    explanation_count: int
    finding_count: int
    template_version: str
    input_sha256: str
    markdown_sha256: str | None
    created_at: datetime
    completed_at: datetime | None


class ReportDetail(ReportResponse):
    content: ReportContent | None


class ReportList(BaseModel):
    items: list[ReportResponse]
    total: int
