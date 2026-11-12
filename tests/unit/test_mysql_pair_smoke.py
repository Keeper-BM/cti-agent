from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from scripts.smoke_mysql_pair import CVE, FIXED_VERSION, package_state, run, verify_findings

FINDING = {
    "package_name": "mysql-server-8.0",
    "cve_id": CVE,
    "fixed_version": FIXED_VERSION,
    "version_comparison": "MEETS_FIX",
    "origin_status": "UNKNOWN",
    "verdict": "NEEDS_REVIEW",
}


def test_restored_package_comparison_ignores_new_collection_ids_but_detects_version_change():
    old = {
        "binary_name": "mysql-server-8.0",
        "binary_version": "8.0.36-2ubuntu3",
        "architecture": "arm64",
        "package_id": str(uuid4()),
        "origin_evidence_ref": str(uuid4()),
        "origin_status": "UNKNOWN",
    }
    new = {**old, "package_id": str(uuid4()), "origin_evidence_ref": str(uuid4())}
    assert package_state([old]) == package_state([new])
    new["binary_version"] = "8.0.46-0ubuntu0.24.04.5"
    assert package_state([old]) != package_state([new])


@pytest.mark.parametrize(
    "field,value",
    [
        ("version_comparison", "BELOW_FIX"),
        ("fixed_version", "9.0"),
        ("origin_status", "OFFICIAL_MATCH"),
        ("verdict", "FIXED"),
        ("cve_id", "CVE-2024-0000"),
    ],
)
def test_acceptance_does_not_pass_wrong_version_or_unverified_definite_verdict(field, value):
    finding = deepcopy(FINDING)
    verify_findings([finding], "MEETS_FIX")
    finding[field] = value
    with pytest.raises(RuntimeError):
        verify_findings([finding], "MEETS_FIX")


def test_acceptance_requires_server_finding():
    with pytest.raises(RuntimeError, match="No findings"):
        verify_findings([], "MEETS_FIX")
    finding = {**FINDING, "package_name": "mysql-client-8.0"}
    with pytest.raises(RuntimeError, match="Server finding absent"):
        verify_findings([finding], "MEETS_FIX")


def test_tampered_baseline_identifiers_cannot_redirect_authenticated_requests():
    def unexpected(request):
        pytest.fail("An invalid identifier must fail before any authenticated request")

    baseline = {
        "schema": "mysql-version-pair/1",
        "asset_id": str(uuid4()),
        "analysis": {"id": "https://other.invalid/"},
        "snapshots": {},
    }
    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(unexpected)
    ) as client:
        with pytest.raises(ValueError):
            run(client, None, baseline=baseline)
