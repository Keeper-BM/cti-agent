from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.api.schemas.sources import RecordResponse, SnapshotResponse
from backend.assessment.contracts import AssessmentFinding
from backend.models.contracts import Contract


class AnalysisRequest(Contract):
    inventory_id: UUID


class AnalysisResponse(TimestampResponse):
    id: UUID
    job: JobResponse
    asset_id: UUID
    inventory_id: UUID
    asset_name: str
    expected_release: str | None
    os_release: str | None
    is_synthetic: bool
    ruleset_version: str
    feed_snapshot_id: UUID
    sources: list[SnapshotResponse]
    warnings: list[str]
    summary: dict[str, int] | None
    created_at: datetime
    completed_at: datetime | None


class AnalysisList(BaseModel):
    items: list[AnalysisResponse]
    total: int


class FindingList(BaseModel):
    items: list[AssessmentFinding]
    total: int


class FindingDetail(AssessmentFinding):
    related_records: list[RecordResponse]
    kev_snapshot: SnapshotResponse | None
