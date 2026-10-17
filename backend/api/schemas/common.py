"""공통 HTTP 응답, 시각 형식, 오류 및 기능 상태 규격."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class TimestampResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", "started_at", "finished_at", check_fields=False)
    @classmethod
    def utc_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool


class ErrorResponse(BaseModel):
    error: ErrorDetail


class FeatureFlags(BaseModel):
    assets: bool = True
    development_examples: bool = True
    worker_system_check: bool = True
    ssh_collection: bool = False
    security_feeds: bool = False
    assessment: bool = False
    rag: bool = False
    reports: bool = False
    user_accounts: bool = False


class CapabilitiesResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["development"] = "development"
    features: FeatureFlags
