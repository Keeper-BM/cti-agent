from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceId = Literal["ubuntu", "nvd", "kev", "apache", "oracle"]
CVE_PATTERN = r"^CVE-[0-9]{4}-[0-9]{4,19}$"


class Metric(BaseModel):
    version: str
    vector: str | None = None
    score: float | None = None
    provider: str | None = None


class SecurityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cve_id: str = Field(pattern=CVE_PATTERN)
    title: str
    description: str
    package_name: str | None = None
    release: str | None = None
    status: Literal[
        "FIX_AVAILABLE", "UNKNOWN", "WITHDRAWN", "REJECTED", "KNOWN_EXPLOITED", "REFERENCE"
    ]
    fixed_version: str | None = None
    upstream_fixed_version: str | None = None
    ranges: list[dict] = Field(default_factory=list)
    affected_versions: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    priority: str | None = None
    references: list[str] = Field(default_factory=list)
    published_at: str | None = None
    modified_at: str | None = None
    notes: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


class Download(BaseModel):
    url: str
    captured_at: datetime
    sha256: str
    content_type: str
    text: str


class CollectedDocument(BaseModel):
    download: Download
    records: list[SecurityRecord]


SOURCE_INFO = {
    "ubuntu": ("Ubuntu CVE", "릴리스별 패키지·수정 기준", "https://ubuntu.com/security/cves"),
    "nvd": ("NVD", "CVE 설명·CVSS·CWE", "https://nvd.nist.gov/"),
    "kev": ("CISA KEV", "실제 악용이 확인된 취약점 목록", "https://www.cisa.gov/kev"),
    "apache": (
        "Apache HTTP Server",
        "제품의 영향 조건·수정 공지",
        "https://httpd.apache.org/security/vulnerabilities_24.html",
    ),
    "oracle": (
        "Oracle / MySQL",
        "선택한 공식 공지의 MySQL 관련 내용",
        "https://www.oracle.com/security-alerts/",
    ),
}
ADAPTER_VERSION = "security-sources/1.0"
