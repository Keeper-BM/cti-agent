"""JSON file input. Identity, ingestion time and trust levels are server-owned."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.api.schemas.common import TimestampResponse
from backend.models.enums import CollectionStatus

PackageName = Annotated[
    str,
    StringConstraints(strict=True, min_length=2, max_length=200, pattern=r"^[a-z0-9][a-z0-9+.-]+$"),
]
VersionText = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=200, pattern=r"^[0-9][A-Za-z0-9.+:~\-]*$"
    ),
]
ShortName = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
]
OriginText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
]


class InventoryOSInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["ubuntu"]
    version_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]{2}\.[0-9]{2}$")]
    codename: ShortName | None = None
    architecture: ShortName | None = None


class PackageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binary_name: PackageName
    binary_version: VersionText | None = None
    source_name: PackageName | None = None
    source_version: VersionText | None = None
    architecture: ShortName | None = None
    origin: OriginText | None = None

    @model_validator(mode="after")
    def source_version_has_name(self) -> Self:
        if self.source_version is not None and self.source_name is None:
            raise ValueError("source_version이 있으면 source_name도 필요합니다.")
        return self


class InventoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    collected_at: AwareDatetime
    os: InventoryOSInput
    packages: list[PackageInput] = Field(min_length=1, max_length=5000)
    package_list_complete: StrictBool = False
    is_synthetic: StrictBool = False

    @field_validator("collected_at", mode="before")
    @classmethod
    def timestamp_is_text(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("collected_at은 시간대가 포함된 ISO 8601 문자열이어야 합니다.")
        return value

    @model_validator(mode="after")
    def unique_packages(self) -> Self:
        identities = [(package.binary_name, package.architecture) for package in self.packages]
        if len(set(identities)) != len(identities):
            raise ValueError("같은 패키지 이름과 아키텍처가 중복되어 있습니다.")
        return self


class InventorySummary(TimestampResponse):
    inventory_id: UUID
    asset_id: UUID
    collected_at: datetime
    ingested_at: datetime
    os_release: str
    package_count: int
    collection_status: CollectionStatus
    is_synthetic: bool


class InventoryList(BaseModel):
    items: list[InventorySummary]
    total: int


class CsvInventoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=2 * 1024 * 1024)
