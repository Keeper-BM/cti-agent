import ipaddress
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.collectors.ssh_protocol import CollectionEvidence
from backend.models.contracts import Contract


class SSHProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    host: str = Field(min_length=1, max_length=45)
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    username: str = Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    key_alias: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    host_fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")

    @field_validator("host")
    @classmethod
    def literal_ip(cls, value):
        try:
            address = ipaddress.ip_address(value)
            if (
                address.is_unspecified
                or address.is_multicast
                or address.is_link_local
                or "%" in value
            ):
                raise ValueError()
            return str(address)
        except ValueError:
            raise ValueError("명시적인 서버 IPv4 또는 IPv6 주소를 입력하세요.") from None


class SSHProfileResponse(SSHProfileInput, TimestampResponse):
    id: UUID
    asset_id: UUID
    created_at: datetime


class SSHProfileState(BaseModel):
    profile: SSHProfileResponse | None


class SSHSettingsResponse(BaseModel):
    enabled: bool
    allowed_targets: list[str]
    key_aliases: list[str]
    timeout_seconds: float
    message: str


class CollectionRequest(Contract):
    profile_id: UUID


class CollectionResponse(TimestampResponse):
    id: UUID
    asset_id: UUID
    profile: SSHProfileResponse
    job: JobResponse
    inventory_id: UUID | None
    collector_version: str
    created_at: datetime
    completed_at: datetime | None


class CollectionDetail(CollectionResponse):
    evidence: CollectionEvidence | None


class CollectionList(BaseModel):
    items: list[CollectionResponse]
    total: int
