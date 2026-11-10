from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.models.runtime import ApacheHTTP2Evidence

VERSION = "ubuntu-files/1.1"
RELEASES = {"22.04": "jammy", "24.04": "noble"}
PACKAGES = {
    "apache2",
    "apache2-bin",
    "apache2-data",
    "apache2-utils",
    "mysql-server",
    "mysql-server-8.0",
    "mysql-server-core-8.0",
    "mysql-client-8.0",
    "mysql-client-core-8.0",
    "libmysqlclient21",
}


class FileCheck(BaseModel):
    path: str
    kind: str
    expected: str | None = None
    observed: str | None = None
    status: Literal["MATCH", "DIFFERENT", "MISSING", "UNREADABLE", "CONFIGURATION", "UNSUPPORTED"]


class PackageCheck(BaseModel):
    package_id: str
    name: str
    version: str | None
    architecture: str | None
    status: Literal["MATCH", "DIFFERENT", "UNAVAILABLE", "CHANGED"]
    message: str
    archive: dict | None = None
    files: list[FileCheck] = Field(default_factory=list)


class VerificationEvidence(BaseModel):
    apache_http2: ApacheHTTP2Evidence | None = None
    apache_runtime_note: str | None = None
    verifier_version: str = VERSION
    checked_at: datetime
    original_inventory_id: str
    host_fingerprint: str
    packages: list[PackageCheck]
    warnings: list[str] = Field(default_factory=list)
