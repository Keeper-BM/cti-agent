from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.comparison.contracts import ComparisonResult
from backend.models.contracts import Contract


class ComparisonRequest(Contract):
    baseline_analysis_id: UUID
    target_inventory_id: UUID


class ComparisonResponse(TimestampResponse):
    id: UUID
    asset_id: UUID
    baseline_analysis_id: UUID
    target_inventory_id: UUID
    job: JobResponse
    created_at: datetime
    completed_at: datetime | None
    version: str


class ComparisonDetail(ComparisonResponse):
    result: ComparisonResult | None


class ComparisonList(BaseModel):
    items: list[ComparisonResponse]
    total: int
