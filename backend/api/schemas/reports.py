"""Single-analysis report requests, summaries and frozen previews."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, StrictBool

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.models.contracts import Contract
from backend.reports.contracts import ReportContent


class ReportRequest(Contract):
    analysis_id: UUID
    include_ai_explanations: StrictBool = False


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
