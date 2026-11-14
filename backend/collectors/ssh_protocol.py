"""Fixed read-only command protocol. No request fields are interpolated into commands."""

import hashlib
import re
import shlex
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.assessment.debian_version import compare_versions
from backend.collectors.service_status import SERVICE_UNITS, ServiceObservation, parse_service
from backend.core.errors import AppError
from backend.models.contracts import Coverage, InstalledPackage, InventorySnapshot, OperatingSystem

COLLECTOR_VERSION = "ubuntu-ssh/1.2"
ENV = "/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C LANG=C "
PACKAGE_FORMAT = (
    "${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\t"
    "${Architecture}\t${db:Status-Status}\t${db:Status-Eflag}\n"
)
POLICY_PACKAGES = (
    "apache2 apache2-bin apache2-data apache2-utils mysql-server mysql-server-8.0 "
    "mysql-server-core-8.0 mysql-client-8.0 mysql-client-core-8.0 libmysqlclient21"
)
COMMANDS = {
    "os_release": ENV + "/usr/bin/cat /etc/os-release",
    "architecture": ENV + "/usr/bin/dpkg --print-architecture",
    "packages": ENV + "/usr/bin/dpkg-query --show --showformat=" + shlex.quote(PACKAGE_FORMAT),
    "apt_policy": ENV
    + "/usr/bin/timeout --kill-after=2s 12s /usr/bin/apt-cache "
    + "-o Dir::Cache::pkgcache= -o Dir::Cache::srcpkgcache= policy "
    + POLICY_PACKAGES,
    **{
        name: ENV
        + "/usr/bin/timeout --kill-after=1s 5s /usr/bin/systemctl --no-pager --all show "
        + "--property=Id,LoadState,ActiveState,SubState,UnitFileState "
        + unit
        for name, unit in SERVICE_UNITS.items()
    },
}
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_PACKAGES = 5000
NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,199}$")
ARCH = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
STATES = {
    "installed",
    "unpacked",
    "half-installed",
    "half-configured",
    "triggers-awaited",
    "triggers-pending",
    "config-files",
    "not-installed",
}


class CommandResult(BaseModel):
    name: str
    exit_code: int
    stdout: str
    stderr_present: bool = False


class CollectionEvidence(BaseModel):
    collector_version: str = COLLECTOR_VERSION
    observed_at: datetime
    verified_host_fingerprint: str
    commands: list[CommandResult]
    output_sha256: str
    origin_verification: str = "NOT_VERIFIED"
    warnings: list[str]
    services: list[ServiceObservation] = Field(default_factory=list)


def clean_output(value: str) -> str:
    # APT repository URLs may contain credentials. Never store those userinfo fields.
    return re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@", r"\1[REDACTED]@", value)


def parse_os(value: str) -> OperatingSystem:
    fields = {}
    try:
        for line in value.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, raw = line.split("=", 1)
            if key in fields:
                raise ValueError()
            parts = shlex.split(raw, comments=True)
            fields[key] = " ".join(parts)
    except ValueError:
        raise AppError("SSH_OUTPUT_INVALID", "OS 정보 형식을 해석할 수 없습니다.", 502) from None
    if fields.get("ID") != "ubuntu" or fields.get("VERSION_ID") not in {"22.04", "24.04"}:
        raise AppError("SSH_OS_UNSUPPORTED", "Ubuntu 22.04·24.04만 수집 대상으로 지원합니다.", 422)
    codename = fields.get("VERSION_CODENAME") or fields.get("UBUNTU_CODENAME")
    if codename and not re.fullmatch(r"[a-z]{1,30}", codename):
        raise AppError("SSH_OUTPUT_INVALID", "OS 코드명 형식이 올바르지 않습니다.", 502)
    return OperatingSystem(id="ubuntu", version_id=fields["VERSION_ID"], codename=codename)


def make_inventory(asset_id: UUID, run_id: str, results: list[CommandResult], fingerprint: str):
    by_name = {r.name: r for r in results}
    if set(by_name) != set(COMMANDS) or len(results) != len(COMMANDS):
        raise AppError("SSH_OUTPUT_INVALID", "필수 조회 결과가 누락되었습니다.", 502)
    if by_name["os_release"].exit_code != 0:
        raise AppError(
            "SSH_OS_READ_FAILED", "OS 정보를 읽지 못했습니다. 계정 권한을 확인하세요.", 502
        )
    os_info = parse_os(by_name["os_release"].stdout)
    warnings, missing = [], []
    arch = by_name["architecture"].stdout.strip()
    if by_name["architecture"].exit_code == 0 and ARCH.fullmatch(arch):
        os_info.architecture = arch
    else:
        missing.append("os.architecture")
        warnings.append("OS 아키텍처를 확인하지 못했습니다.")
    query = by_name["packages"]
    packages, identities = [], set()
    malformed = 0
    for line in query.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            malformed += 1
            continue
        binary, version, source, source_version, arch, state, flag = parts
        if state not in STATES:
            malformed += 1
            continue
        if state in {"not-installed", "config-files"}:
            continue
        name, separator, qualified_arch = binary.partition(":")
        if (
            not NAME.fullmatch(name)
            or not ARCH.fullmatch(arch)
            or (separator and qualified_arch != arch)
            or (source and not NAME.fullmatch(source))
        ):
            malformed += 1
            continue
        if (name, arch) in identities:
            raise AppError("SSH_OUTPUT_INVALID", "조회 결과에 중복 패키지가 있습니다.", 502)
        identities.add((name, arch))
        for label, value in [("binary_version", version), ("source_version", source_version)]:
            try:
                compare_versions(value, value)
            except ValueError:
                missing.append(f"packages[{len(packages)}].{label}")
        if not source:
            missing.append(f"packages[{len(packages)}].source_name")
        if state != "installed" or flag != "ok":
            warnings.append(f"{name}: 설치 상태가 정상 완료 상태가 아닙니다.")
        packages.append(
            InstalledPackage(
                package_id=uuid4(),
                binary_name=name,
                binary_version=version or None,
                source_name=source or None,
                source_version=source_version or None,
                architecture=arch,
                install_status=state if flag == "ok" else "error",
                origin_status="UNKNOWN",
                origin_evidence_ref=run_id,
                origin_description=(
                    "SSH로 패키지 DB를 조회했습니다. 설치 출처·바이너리 무결성은 미검증입니다."
                ),
            )
        )
        if len(packages) > MAX_PACKAGES:
            raise AppError("SSH_PACKAGE_LIMIT", "패키지 개수가 5,000개 제한을 초과합니다.", 502)
    if not packages:
        raise AppError("SSH_PACKAGE_READ_FAILED", "저장할 패키지 정보를 읽지 못했습니다.", 502)
    complete = query.exit_code == 0 and malformed == 0
    if query.exit_code != 0:
        warnings.append("패키지 조회 명령이 실패 상태로 종료되어 일부 결과만 저장했습니다.")
    if malformed:
        warnings.append(f"패키지 {malformed}줄을 해석하지 못했습니다. 부분 수집으로 저장합니다.")
    if by_name["apt_policy"].exit_code != 0:
        warnings.append("APT 캐시의 출처 참고 정보를 읽지 못했습니다.")
    services = [
        parse_service(unit, by_name[name].exit_code, by_name[name].stdout)
        for name, unit in SERVICE_UNITS.items()
    ]
    for service in services:
        if service.status == "UNKNOWN":
            warnings.append(f"{service.unit}: 서비스 상태를 확인하지 못했습니다.")
    warnings.append(
        "APT 캐시는 저장소의 참고 정보입니다. 설치 출처·서명·파일 무결성을 증명하지 않습니다."
    )
    now = datetime.now(UTC)
    inventory = InventorySnapshot(
        inventory_id=uuid4(),
        asset_id=asset_id,
        collected_at=now,
        ingested_at=now,
        collection_method="SSH",
        collection_status="COMPLETE" if complete else "PARTIAL",
        os=os_info,
        packages=packages,
        coverage=Coverage(package_list_complete=complete, missing_fields=missing),
        errors=warnings,
        collector_version=COLLECTOR_VERSION,
        is_synthetic=False,
    )
    sanitized = [r.model_copy(update={"stdout": clean_output(r.stdout)}) for r in results]
    wire = "\n".join(r.model_dump_json() for r in sanitized)
    evidence = CollectionEvidence(
        observed_at=now,
        verified_host_fingerprint=fingerprint,
        commands=sanitized,
        output_sha256=hashlib.sha256(wire.encode("utf-8")).hexdigest(),
        warnings=warnings,
        services=services,
    )
    return inventory, evidence
