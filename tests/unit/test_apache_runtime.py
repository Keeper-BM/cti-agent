import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.assessment.engine import UbuntuAssessmentEngine
from backend.assessment.runtime import (
    HTTP2_CVE,
    HTTP2_FIXED,
    HTTP2_VULNERABLE,
    reviewed_http2_record,
)
from backend.models.contracts import InventorySnapshot
from backend.models.enums import CollectionMethod, OriginStatus
from backend.models.runtime import HTTP2_CONDITION, ApacheHTTP2Evidence
from backend.verification.runtime import confirm_apache_http2
from tests.unit.test_assessment import finding, inputs


def scenario():
    inventory, feed = inputs(version=HTTP2_VULNERABLE, fixed=HTTP2_FIXED)
    now = datetime.now(UTC)
    inventory.collected_at = inventory.ingested_at = now
    inventory.is_synthetic = False
    inventory.collection_method = CollectionMethod.SSH
    inventory.os.version_id = "24.04"
    inventory.verification_id = uuid4()
    package = inventory.packages[0]
    package.origin_status = OriginStatus.OFFICIAL_MATCH
    package.origin_evidence_ref = str(inventory.verification_id)
    rule = feed.advisories[0].rules[0]
    rule.release = "24.04"
    rule.runtime_condition = HTTP2_CONDITION
    feed.advisories[0].cve_id = HTTP2_CVE
    inventory.apache_http2 = ApacheHTTP2Evidence(
        observer_version="apache-runtime/1.0",
        observed_at=now,
        main_pid=100,
        process_start_ticks=1000,
        boot_id=uuid4(),
        service_active=True,
        module_loaded=True,
        listener_owned=True,
        process_unchanged=True,
        endpoint="http://127.0.0.1:80/",
        http_version="2",
        http_status=200,
        executable_sha256="a" * 64,
        module_sha256="b" * 64,
        verification_id=inventory.verification_id,
        package_version=HTTP2_VULNERABLE,
        source_version=HTTP2_VULNERABLE,
    )
    return inventory, feed


def test_only_verified_apache_binary_and_exact_cve_gain_confirmed_applicability():
    inventory, feed = scenario()
    result = finding(inventory, feed)
    assert result.verdict == "AFFECTED" and result.version_comparison == "BELOW_FIX"
    assert result.runtime_evidence == inventory.apache_http2
    package = inventory.packages[0].model_copy(deep=True)
    package.package_id = uuid4()
    package.binary_name = "apache2-data"
    inventory.packages.append(package)
    other = feed.advisories[0].model_copy(deep=True)
    other.cve_id = "CVE-2023-38709"
    other.rules[0].rule_id = uuid4()
    other.rules[0].runtime_condition = None
    other.rules[0].limitations = ["Unverified runtime conditions"]
    feed.advisories.append(other)
    results = UbuntuAssessmentEngine().assess(inventory, feed)
    affected = [f for f in results if f.verdict == "AFFECTED"]
    assert (
        len(affected) == 1
        and affected[0].package_name == "apache2-bin"
        and affected[0].cve_id == HTTP2_CVE
    )
    assert all(f.verdict == "NEEDS_REVIEW" for f in results if f.cve_id and f not in affected)
    assert finding(inventory, feed, rejected_cves={HTTP2_CVE}).verdict == "NEEDS_REVIEW"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "different_proof",
        "json",
        "synthetic",
        "unknown_origin",
        "old_observation",
        "other_version",
    ],
)
def test_unobserved_or_untrusted_conditions_never_become_affected(change):
    inv, feed = scenario()
    if change == "missing":
        inv.apache_http2 = None
    elif change == "different_proof":
        inv.apache_http2.verification_id = uuid4()
    elif change == "json":
        inv.collection_method = "JSON"
    elif change == "synthetic":
        inv.is_synthetic = True
    elif change == "unknown_origin":
        inv.packages[0].origin_status = "UNKNOWN"
    elif change == "old_observation":
        inv.apache_http2.observed_at -= timedelta(hours=1)
    else:
        inv.packages[0].source_version = "2.4.58-1ubuntu7"
    result = finding(inv, feed)
    assert result.verdict == "NEEDS_REVIEW" and result.runtime_evidence is None


def test_fixed_version_still_works_without_optional_runtime_observer():
    inv, feed = scenario()
    inv.apache_http2 = None
    inv.packages[0].source_version = inv.packages[0].binary_version = HTTP2_FIXED
    assert finding(inv, feed).verdict == "FIXED"


def test_reviewed_rule_requires_exact_official_scope_and_version_range():
    data = SimpleNamespace(
        cve_id=HTTP2_CVE,
        package_name="apache2",
        release="24.04",
        fixed_version=HTTP2_FIXED,
        affected_versions=[HTTP2_VULNERABLE],
    )
    assert reviewed_http2_record(data, True)
    assert not reviewed_http2_record(data, False)
    for name, value in [
        ("release", "22.04"),
        ("cve_id", "CVE-2024-0001"),
        ("package_name", "mysql-8.0"),
        ("fixed_version", "2.4.99-1"),
        ("affected_versions", []),
    ]:
        altered = copy.copy(data)
        setattr(altered, name, value)
        assert not reviewed_http2_record(altered, True)


def test_observation_must_match_authenticated_files_and_current_timestamp():
    inv, _ = scenario()
    evidence = inv.apache_http2
    raw = {
        "status": "OK",
        "observation": evidence.model_dump(
            mode="json", exclude={"verification_id", "package_version", "source_version"}
        ),
    }
    artifacts = {
        str(inv.packages[0].package_id): {
            "files": {
                "/usr/sbin/apache2": {"sha256": "a" * 64},
                "/usr/lib/apache2/modules/mod_http2.so": {"sha256": "b" * 64},
            }
        }
    }
    verified, _ = confirm_apache_http2(raw, inv, artifacts, str(inv.verification_id))
    assert verified == evidence
    for name, value in [
        ("executable_sha256", "c" * 64),
        ("module_sha256", "c" * 64),
        ("http_version", "1.1"),
        ("listener_owned", False),
        ("observed_at", (datetime.now(UTC) - timedelta(minutes=5)).isoformat()),
    ]:
        changed = copy.deepcopy(raw)
        changed["observation"][name] = value
        assert confirm_apache_http2(changed, inv, artifacts, str(inv.verification_id))[0] is None
    assert confirm_apache_http2(None, inv, artifacts, str(inv.verification_id))[0] is None
    # Legacy snapshots retain their meaning without a runtime evidence field.
    data = inv.model_dump(mode="json")
    data.pop("apache_http2")
    assert InventorySnapshot.model_validate(data).apache_http2 is None
