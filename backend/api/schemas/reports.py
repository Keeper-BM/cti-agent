"""고정된 분석 기준본을 사용하는 보고서 요청 규격."""

from uuid import UUID

from pydantic import Field

from backend.models.contracts import Contract


class ReportRequest(Contract):
    analysis_ids: list[UUID] = Field(min_length=1, max_length=20)
