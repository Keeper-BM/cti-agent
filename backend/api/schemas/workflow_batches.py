from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.api.schemas.common import TimestampResponse
from backend.models.enums import Verdict

MAX_BATCH_ASSETS = 20
CoverageState = Literal["EVALUATED", "NO_TARGET", "NO_EVIDENCE"]


class WorkflowBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[UUID] = Field(min_length=2, max_length=MAX_BATCH_ASSETS)

    @field_validator("asset_ids")
    @classmethod
    def distinct_assets(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("같은 자산이 중복되었습니다.")
        return value


class BatchPriority(BaseModel):
    asset_id: UUID
    cve_id: str
    package_name: str
    verdict: Literal["AFFECTED", "NEEDS_REVIEW"]
    kev_listed: bool
    next_step: str | None
    finding_id: UUID | None = None
    cvss_score: float | None = None
    priority_reason: str | None = None


class BatchReportSummary(BaseModel):
    cve_count: int
    affected_cve_count: int
    attention_asset_count: int
    priority_total: int
    priorities: list[BatchPriority]


class BatchAssetResponse(TimestampResponse):
    asset_id: UUID
    asset_name: str
    status: Literal["RUNNING", "COMPLETED", "FAILED"]
    stage: Literal["inventory", "sources", "analysis", "report"]
    analysis_id: UUID | None
    report_id: UUID | None
    os_release: str | None
    is_synthetic: bool
    carried: bool
    verdict_counts: dict[str, int]
    coverage: CoverageState | None
    evaluated_pairs: int
    package_count: int | None
    collection_status: str | None
    collected_at: datetime | None
    error: str | None
    report_note: str | None


class BatchSource(TimestampResponse):
    job_id: UUID
    source: str
    scope: str
    status: Literal["UPDATED", "CACHED", "FAILED", "REUSED"]
    captured_at: datetime | None = None
    snapshot_id: UUID | None = None
    asset_names: list[str]


class WorkflowBatchResponse(TimestampResponse):
    id: UUID
    parent_id: UUID | None
    retry_id: UUID | None
    status: Literal["RUNNING", "COMPLETED", "PARTIAL", "FAILED"]
    created_at: datetime
    finished_at: datetime | None
    assets: list[BatchAssetResponse]
    evaluated_cve_count: int | None
    affected_cve_count: int | None
    sources: list[BatchSource]
    report_status: Literal["WAITING", "QUEUED", "READY", "FAILED"]
    report_summary: BatchReportSummary | None
    report_error: str | None


class WorkflowBatchList(BaseModel):
    items: list[WorkflowBatchResponse]
    total: int


class BatchComparisonFinding(TimestampResponse):
    finding_id: UUID
    asset_id: UUID
    package_name: str | None
    architecture: str | None
    binary_version: str | None
    installed_version: str | None
    fixed_version: str | None
    verdict: Verdict
    ubuntu_snapshot_id: UUID | None
    captured_at: datetime | None


class BatchComparison(BaseModel):
    cve_id: str | None
    items: list[BatchComparisonFinding]
