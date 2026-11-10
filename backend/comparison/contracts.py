from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.assessment.contracts import AssessmentFinding
from backend.models.contracts import FeedSnapshot, InventorySnapshot

VERSION = "analysis-comparison/1.0"


class ComparisonInput(BaseModel):
    baseline_analysis_id: UUID
    asset_id: UUID
    asset_name: str
    expected_release: str | None
    before: InventorySnapshot
    after: InventorySnapshot
    feed: FeedSnapshot
    rejected_cves: list[str]
    risk_facts: dict[str, dict]
    source_snapshot_ids: list[str]


class ComparisonRow(BaseModel):
    package_name: str
    architecture: str | None
    cve_id: str | None
    change: Literal["ADDED", "REMOVED", "CHANGED", "UNCHANGED"]
    before: list[AssessmentFinding]
    after: list[AssessmentFinding]


class ComparisonResult(BaseModel):
    baseline_analysis_id: UUID
    asset_id: UUID
    asset_name: str
    before_inventory_id: UUID
    after_inventory_id: UUID
    source_snapshot_ids: list[str]
    ruleset_version: str
    before_collected_at: datetime
    after_collected_at: datetime
    completed_at: datetime
    summary: dict[str, int]
    rows: list[ComparisonRow]
    warnings: list[str] = Field(default_factory=list)
