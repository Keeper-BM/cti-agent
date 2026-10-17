"""작업 실행 상태와 조회 응답 규격."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from backend.api.schemas.common import TimestampResponse
from backend.models.enums import JobStatus


class JobResponse(TimestampResponse):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    kind: str
    status: JobStatus
    attempts: int
    result: dict | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
