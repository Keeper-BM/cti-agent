"""Domain contracts for collection, assessment, evidence, and explanation."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.models.enums import (
    CollectionMethod,
    CollectionStatus,
    OriginStatus,
    ProcessingStatus,
    ReasonCode,
    Verdict,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"


class InstalledPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: UUID
    binary_name: str = Field(min_length=1)
    binary_version: str | None = None
    source_name: str | None = None
    source_version: str | None = None
    architecture: str | None = None
    install_status: str
    origin_status: OriginStatus = OriginStatus.UNKNOWN
    origin_evidence_ref: str | None = None


class OperatingSystem(BaseModel):
    id: str | None = None
    version_id: str | None = None
    codename: str | None = None
    architecture: str | None = None


class Coverage(BaseModel):
    package_list_complete: bool = False
    missing_fields: list[str] = Field(default_factory=list)


class InventorySnapshot(Contract):
    inventory_id: UUID
    asset_id: UUID
    collected_at: AwareDatetime
    ingested_at: AwareDatetime
    collection_method: CollectionMethod
    collection_status: CollectionStatus
    os: OperatingSystem
    packages: list[InstalledPackage]
    coverage: Coverage
    errors: list[str] = Field(default_factory=list)
    collector_version: str

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        if len({package.package_id for package in self.packages}) != len(self.packages):
            raise ValueError("Package IDs must be unique within an inventory")
        if self.collection_status == CollectionStatus.COMPLETE:
            if not self.os.id or not self.os.version_id or not self.coverage.package_list_complete:
                raise ValueError("COMPLETE requires OS identity and a complete package list")
        elif self.coverage.package_list_complete:
            raise ValueError("An incomplete collection cannot assert a complete package list")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_version_id: UUID
    source: str
    title: str
    url: str
    excerpt: str


class AdvisoryPackageRule(BaseModel):
    """A normalized package condition; raw source semantics remain the adapter's concern."""

    model_config = ConfigDict(extra="forbid")
    rule_id: UUID
    package_name: str = Field(min_length=1)
    package_kind: Literal["BINARY", "SOURCE"]
    os_id: str = Field(min_length=1)
    release: str = Field(min_length=1)
    architecture: str | None = None
    status: Literal["AFFECTED", "FIX_RELEASED", "NOT_AFFECTED", "UNKNOWN"]
    fixed_version: str | None = None
    version_scheme: Literal["DEBIAN"] = "DEBIAN"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fixed_version(self) -> Self:
        if self.status == "FIX_RELEASED" and not self.fixed_version:
            raise ValueError("FIX_RELEASED requires the full fixed version")
        return self


class NormalizedAdvisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    advisory_id: str = Field(min_length=1)
    cve_id: str = Field(pattern=r"^CVE-\d{4}-\d{4,}$")
    rules: list[AdvisoryPackageRule]
    evidence_refs: list[Evidence] = Field(min_length=1)


class FeedSnapshot(Contract):
    feed_snapshot_id: UUID
    captured_at: AwareDatetime
    normalizer_version: str
    is_synthetic: bool = False
    advisories: list[NormalizedAdvisory]

    @model_validator(mode="after")
    def validate_rule_ids(self) -> Self:
        ids = [rule.rule_id for advisory in self.advisories for rule in advisory.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("Rule IDs must be unique within a feed snapshot")
        return self


class Finding(Contract):
    finding_id: UUID
    analysis_id: UUID
    asset_id: UUID
    inventory_id: UUID
    package_ref: UUID | None = None
    installed_version: str | None = None
    comparison_basis: Literal["BINARY", "SOURCE"] | None = None
    matched_rule_id: UUID | None = None
    cve_id: str | None = Field(default=None, pattern=r"^CVE-\d{4}-\d{4,}$")
    processing_status: ProcessingStatus
    verdict: Verdict | None = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    fixed_version: str | None = None
    evidence_refs: list[Evidence] = Field(default_factory=list)
    evaluated_at: AwareDatetime
    ruleset_version: str
    feed_snapshot_id: UUID | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if (self.processing_status == ProcessingStatus.EVALUATED) != (self.verdict is not None):
            raise ValueError("Only EVALUATED findings have a verdict, and it is required")
        if self.verdict in {Verdict.AFFECTED, Verdict.FIXED, Verdict.NOT_AFFECTED}:
            if not self.evidence_refs or not self.cve_id or not self.feed_snapshot_id:
                raise ValueError("A definite verdict requires a CVE, evidence, and a feed snapshot")
            if not all(
                [
                    self.package_ref,
                    self.installed_version,
                    self.comparison_basis,
                    self.matched_rule_id,
                ]
            ):
                raise ValueError("A definite verdict requires a package, version, basis, and rule")
        return self


class Answer(Contract):
    requested_asset_ids: list[UUID]
    analysis_ids: list[UUID]
    answer: str
    citations: list[Evidence]
    warnings: list[str] = Field(default_factory=list)
