"""자산 등록·상태 변경·조회 요청과 응답 규격."""

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.api.schemas.common import TimestampResponse
from backend.models.enums import Criticality, Exposure

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_name: Name
    host: str | None = Field(default=None, max_length=253)
    expected_release: Literal["22.04", "24.04"] | None = None
    exposure: Exposure = Exposure.UNKNOWN
    exposure_source: str = Field(min_length=1, max_length=200)
    criticality: Criticality = Criticality.UNKNOWN
    owner_display_name: str | None = Field(default=None, max_length=100)
    collection_method: Literal["MANUAL"] = "MANUAL"

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            labels = value.split(".")
            pattern = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            if not all(re.fullmatch(pattern, label) for label in labels):
                raise ValueError(
                    "Use an IP address or hostname, without a URL, port, or command"
                ) from None
            return value.lower()


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    is_active: StrictBool | None = None
    asset_name: Name | None = None
    host: str | None = Field(default=None, max_length=253)
    expected_release: Literal["22.04", "24.04"] | None = None
    exposure: Exposure | None = None
    exposure_source: str | None = Field(default=None, min_length=1, max_length=200)
    criticality: Criticality | None = None
    owner_display_name: str | None = Field(default=None, max_length=100)

    _host = field_validator("host")(AssetCreate.valid_host.__func__)

    @model_validator(mode="after")
    def provided_fields(self):
        if not self.model_fields_set:
            raise ValueError("변경할 항목을 입력하세요.")
        for name in self.model_fields_set - {"host", "expected_release", "owner_display_name"}:
            if getattr(self, name) is None:
                raise ValueError("필수 항목은 null로 변경할 수 없습니다.")
        return self


class AssetResponse(TimestampResponse, AssetCreate):
    schema_version: Literal["1.0"] = "1.0"
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AssetList(BaseModel):
    items: list[AssetResponse]
    total: int
