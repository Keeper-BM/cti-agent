from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.workflow_batches import MAX_BATCH_ASSETS
from backend.models.enums import Verdict

Frequency = Literal["DAILY", "WEEKLY"]
ChangeKind = Literal["NEW_AFFECTED", "FIXED", "RECHECK"]


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    asset_ids: list[UUID] = Field(min_length=1, max_length=MAX_BATCH_ASSETS)
    frequency: Frequency
    local_time: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    weekday: int | None = Field(default=None, strict=True, ge=0, le=6)

    @model_validator(mode="after")
    def validate_selection(self):
        if (self.frequency == "WEEKLY") != (self.weekday is not None):
            raise ValueError("매주 반복할 때만 요일을 선택하세요.")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("같은 자산이 중복되었습니다.")
        return self


class ScheduleEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(strict=True)


class ScheduleAsset(BaseModel):
    id: UUID
    asset_name: str


class ScheduleResponse(TimestampResponse):
    id: UUID
    name: str
    frequency: Frequency
    weekday: int | None
    local_time: str
    next_run_at: datetime | None
    assets: list[ScheduleAsset]
    inaccessible_asset_count: int


class ScheduleList(BaseModel):
    items: list[ScheduleResponse]
    total: int


class ScheduleRunResponse(TimestampResponse):
    id: UUID
    scheduled_for: datetime
    created_at: datetime
    finished_at: datetime | None
    batch_id: UUID | None
    status: Literal["RUNNING", "COMPLETED", "PARTIAL", "FAILED", "SKIPPED"]
    error: str | None


class ScheduleRunList(BaseModel):
    items: list[ScheduleRunResponse]
    total: int


class ComparisonAsset(TimestampResponse):
    asset_id: UUID
    asset_name: str
    analysis_id: UUID | None
    previous_analysis_id: UUID | None
    previous_completed_at: datetime | None
    status: Literal["COMPARED", "BASELINE", "UNAVAILABLE"]
    reason: str | None


class ScheduleChange(BaseModel):
    kind: ChangeKind
    asset_id: UUID
    cve_id: str
    package_name: str
    architecture: str | None
    previous_verdict: Verdict | None
    verdict: Verdict | None
    previous_finding_id: UUID | None
    finding_id: UUID | None


class ScheduleChanges(BaseModel):
    assets: list[ComparisonAsset]
    counts: dict[ChangeKind, int]
    items: list[ScheduleChange]
    total: int
