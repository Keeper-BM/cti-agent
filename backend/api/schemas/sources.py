from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.sources.contracts import CVE_PATTERN, SecurityRecord, SourceId


class SourceSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release: Literal["22.04", "24.04"] = "22.04"
    package: Literal["apache2", "mysql-8.0"] = "apache2"
    cve_id: str | None = Field(default=None, pattern=CVE_PATTERN)
    url: str | None = Field(default=None, max_length=450)


class SnapshotResponse(TimestampResponse):
    id: UUID
    job_id: UUID
    source_id: SourceId
    scope_key: str
    captured_at: datetime
    adapter_version: str
    document_count: int
    record_count: int


class SnapshotList(BaseModel):
    items: list[SnapshotResponse]
    total: int


class SourceStatus(BaseModel):
    source_id: SourceId
    name: str
    purpose: str
    url: str
    latest_job: JobResponse | None
    latest_snapshot: SnapshotResponse | None


class SourceStatusList(BaseModel):
    items: list[SourceStatus]
    nvd_key_configured: bool


class DocumentInfo(TimestampResponse):
    id: UUID
    snapshot_id: UUID
    url: str
    captured_at: datetime
    sha256: str
    content_type: str


class RecordResponse(BaseModel):
    id: UUID
    snapshot_id: UUID
    source_id: SourceId
    scope_key: str
    data: SecurityRecord
    document: DocumentInfo


class RecordList(BaseModel):
    items: list[RecordResponse]
    total: int


class CVEDetail(BaseModel):
    cve_id: str
    records: list[RecordResponse]
    kev_status: Literal["LISTED", "NOT_LISTED", "NOT_FETCHED"]
    kev_snapshot: SnapshotResponse | None
    oracle_urls: list[str]
