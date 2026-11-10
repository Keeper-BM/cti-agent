"""Bind an optional privileged observation to authenticated Ubuntu package files."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError

from backend.models.runtime import ApacheHTTP2Evidence, ApacheHTTP2Observation


def confirm_apache_http2(raw, inventory, artifacts, verification_id):
    unavailable = (
        "Apache HTTP/2 실행 조건은 확인하지 못했습니다. 해당 조건의 확정 판단을 제한합니다."
    )
    if not isinstance(raw, dict) or raw.get("status") != "OK":
        return None, unavailable
    package = next(
        (
            p
            for p in inventory.packages
            if p.binary_name == "apache2-bin"
            and p.architecture == "amd64"
            and p.origin_status == "OFFICIAL_MATCH"
        ),
        None,
    )
    if not package or inventory.is_synthetic or inventory.collection_method != "SSH":
        return None, unavailable
    try:
        observation = ApacheHTTP2Observation.model_validate(raw["observation"])
        if abs((datetime.now(UTC) - observation.observed_at).total_seconds()) > 90:
            return None, unavailable
        files = artifacts[str(package.package_id)]["files"]
        if (
            files["/usr/sbin/apache2"]["sha256"] != observation.executable_sha256
            or files["/usr/lib/apache2/modules/mod_http2.so"]["sha256"] != observation.module_sha256
        ):
            return None, unavailable
        evidence = ApacheHTTP2Evidence(
            **observation.model_dump(),
            verification_id=UUID(verification_id),
            package_version=package.binary_version,
            source_version=package.source_version,
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        return None, unavailable
    return evidence, "공식 파일과 연결된 Apache 프로세스·HTTP/2 모듈·루프백 응답을 확인했습니다."
