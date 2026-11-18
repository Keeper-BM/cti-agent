from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.api.schemas.assets import AssetResponse
from backend.api.schemas.common import TimestampResponse


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # An explicit snapshot means use that inventory; otherwise collect via SSH.
    inventory_id: UUID | None = None


class WorkflowSource(BaseModel):
    source: str
    scope: str
    job_id: UUID
    status: Literal["QUEUED", "RUNNING", "UPDATED", "CACHED", "FAILED"]
    records: int | None = None
    captured_at: datetime | None = None
    snapshot_id: UUID | None = None


class WorkflowResponse(TimestampResponse):
    id: UUID
    asset_id: UUID
    mode: Literal["ssh", "saved"]
    status: Literal["RUNNING", "FAILED", "COMPLETED"]
    stage: Literal["inventory", "sources", "analysis", "report"]
    inventory_id: UUID | None
    package_count: int | None
    verification_note: str | None
    collected_at: datetime | None
    is_synthetic: bool | None
    analysis_id: UUID | None
    report_id: UUID | None
    sources: list[WorkflowSource]
    timeline: dict[str, datetime]
    warnings: list[str]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class InventoryBrief(TimestampResponse):
    inventory_id: UUID
    package_count: int
    os_release: str | None
    is_synthetic: bool
    collected_at: datetime


class AnalysisBrief(TimestampResponse):
    id: UUID
    inventory_id: UUID
    os_release: str | None
    completed_at: datetime
    is_synthetic: bool
    summary: dict[str, int]
    report_id: UUID | None


class WorkspaceResponse(BaseModel):
    asset: AssetResponse
    profile_id: UUID | None
    connection_status: Literal["unconfigured", "configured", "verified", "failed"]
    connection_checked_at: datetime | None
    inventory: InventoryBrief | None
    latest: WorkflowResponse | None
    history: list[AnalysisBrief]


class ConnectionCheck(TimestampResponse):
    verified: bool
    checked_at: datetime
