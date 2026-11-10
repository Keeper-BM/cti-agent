"""Stored package comparisons; a comparison is not an asset verdict."""

from typing import Literal

from pydantic import Field

from backend.assessment.remediation import Remediation
from backend.models.contracts import Finding
from backend.models.enums import OriginStatus
from backend.models.runtime import ApacheHTTP2Evidence
from backend.sources.contracts import Metric

RULESET_VERSION = "ubuntu-packages/1.2"
RELEASES = {"22.04", "24.04"}
PACKAGES = {"apache2", "mysql-8.0"}
MAX_FINDINGS = 20000

# Used to locate candidate source advisories, never to invent a source version.
BINARY_SOURCES = {
    "apache2": "apache2",
    "apache2-bin": "apache2",
    "apache2-data": "apache2",
    "apache2-utils": "apache2",
    "mysql-server": "mysql-8.0",
    "mysql-server-8.0": "mysql-8.0",
    "mysql-server-core-8.0": "mysql-8.0",
    "mysql-client-8.0": "mysql-8.0",
    "mysql-client-core-8.0": "mysql-8.0",
    "libmysqlclient21": "mysql-8.0",
}


class AssessmentFinding(Finding):
    runtime_evidence: ApacheHTTP2Evidence | None = None
    remediation: Remediation | None = None
    package_name: str | None = None
    source_package: str | None = None
    binary_version: str | None = None
    architecture: str | None = None
    origin_status: OriginStatus | None = None
    origin_evidence_ref: str | None = None
    version_comparison: Literal["BELOW_FIX", "MEETS_FIX", "UNAVAILABLE"] = "UNAVAILABLE"
    reasons: list[str] = Field(default_factory=list)
    kev_status: Literal["LISTED", "NOT_LISTED", "NOT_FETCHED"] = "NOT_FETCHED"
    nvd_metrics: list[Metric] = Field(default_factory=list)
