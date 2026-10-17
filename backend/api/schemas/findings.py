"""분석 요청과 판정 목록 응답 규격."""

from uuid import UUID

from pydantic import BaseModel

from backend.models.contracts import Contract, Finding


class AnalysisRequest(Contract):
    inventory_id: UUID
    feed_snapshot_id: UUID


class FindingList(BaseModel):
    items: list[Finding]
    total: int
