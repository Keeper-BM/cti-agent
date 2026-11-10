from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.assessment.engine import UbuntuAssessmentEngine
from backend.models.contracts import (
    AdvisoryPackageRule,
    Coverage,
    Evidence,
    FeedSnapshot,
    InstalledPackage,
    InventorySnapshot,
    NormalizedAdvisory,
    OperatingSystem,
)

NOW = datetime(2026, 11, 10, tzinfo=UTC)
CVE = "CVE-2099-10001"


def inputs(source="apache2", version="2.4.52-1ubuntu4.3", fixed="2.4.52-1ubuntu4.4"):
    inventory = InventorySnapshot(
        inventory_id=uuid4(),
        asset_id=uuid4(),
        collected_at=NOW,
        ingested_at=NOW,
        collection_method="JSON",
        collection_status="COMPLETE",
        is_synthetic=True,
        os=OperatingSystem(id="ubuntu", version_id="22.04", architecture="amd64"),
        packages=[
            InstalledPackage(
                package_id=uuid4(),
                binary_name="apache2-bin" if source == "apache2" else "mysql-server-8.0",
                binary_version=version,
                source_name=source,
                source_version=version,
                architecture="amd64",
                install_status="installed",
                origin_status="VERIFIED_LAB",
                origin_evidence_ref="synthetic-only",
            )
        ],
        coverage=Coverage(package_list_complete=True),
        collector_version="synthetic-only",
    )
    feed = FeedSnapshot(
        feed_snapshot_id=uuid4(),
        captured_at=NOW,
        normalizer_version="synthetic-only",
        is_synthetic=True,
        advisories=[
            NormalizedAdvisory(
                advisory_id="synthetic",
                cve_id=CVE,
                rules=[
                    AdvisoryPackageRule(
                        rule_id=uuid4(),
                        package_name=source,
                        package_kind="SOURCE",
                        os_id="ubuntu",
                        release="22.04",
                        status="FIX_RELEASED",
                        fixed_version=fixed,
                    )
                ],
                evidence_refs=[
                    Evidence(
                        document_version_id=uuid4(),
                        source="synthetic",
                        title="test",
                        url="https://example.invalid",
                        excerpt="Synthetic rule",
                    )
                ],
            )
        ],
    )
    return inventory, feed


def finding(inventory, feed, **kwargs):
    return next(
        f for f in UbuntuAssessmentEngine().assess(inventory, feed, **kwargs) if f.package_ref
    )


@pytest.mark.parametrize(
    ("version", "verdict", "comparison"),
    [
        ("2.4.52-1ubuntu4.3", "AFFECTED", "BELOW_FIX"),
        ("2.4.52-1ubuntu4.4", "FIXED", "MEETS_FIX"),
        ("2.4.52-1ubuntu4.10", "FIXED", "MEETS_FIX"),
        ("2.4.52-1ubuntu4.4~test1", "AFFECTED", "BELOW_FIX"),
    ],
)
def test_verified_rules_compare_full_debian_versions(version, verdict, comparison):
    result = finding(*inputs(version=version))
    assert result.verdict == verdict
    assert result.version_comparison == comparison
    assert result.comparison_basis == "SOURCE"


def test_mysql_release_and_source_basis():
    inventory, feed = inputs("mysql-8.0", "8.0.36-0ubuntu0.22.04.1", "8.0.36-0ubuntu0.22.04.1")
    inventory.packages[0].binary_version = "1.0"
    assert finding(inventory, feed).verdict == "FIXED"
    inventory.os.version_id = "24.04"
    assert finding(inventory, feed).processing_status == "NO_MATCHING_RECORD"
    feed.advisories[0].rules[0].release = "24.04"
    assert finding(inventory, feed).verdict == "FIXED"


@pytest.mark.parametrize("origin", ["UNKNOWN", "USER_DECLARED", "UNSUPPORTED"])
def test_user_input_never_becomes_verified_by_claiming_a_version(origin):
    inventory, feed = inputs(version="2.4.52-1ubuntu4.4")
    inventory.packages[0].origin_status = origin
    result = finding(inventory, feed)
    assert result.verdict == "NEEDS_REVIEW"
    assert result.version_comparison == "MEETS_FIX"
    assert "UNKNOWN_ORIGIN" in result.reason_codes


@pytest.mark.parametrize("version", [None, "not-a-version"])
def test_missing_or_invalid_source_version_never_falls_back_to_binary(version):
    inventory, feed = inputs()
    inventory.packages[0].source_version = version
    result = finding(inventory, feed)
    assert result.version_comparison == "UNAVAILABLE"
    assert result.verdict == "NEEDS_REVIEW"


def test_conditions_architecture_rejected_and_conflicting_rules_block_verdict():
    inventory, feed = inputs()
    rule = feed.advisories[0].rules[0]
    rule.limitations = ["Unverified runtime configuration"]
    assert finding(inventory, feed).verdict == "NEEDS_REVIEW"
    inventory.packages[0].source_version = rule.fixed_version
    assert finding(inventory, feed).verdict == "FIXED"
    assert finding(inventory, feed, rejected_cves={CVE}).verdict == "NEEDS_REVIEW"
    assert finding(inventory, feed, expected_release="24.04").verdict == "NEEDS_REVIEW"
    rule.architecture = "arm64"
    assert finding(inventory, feed).verdict == "NEEDS_REVIEW"
    rule.architecture = None
    feed.advisories[0].rules.append(
        rule.model_copy(update={"rule_id": uuid4(), "fixed_version": "9.0"})
    )
    assert finding(inventory, feed).verdict == "NEEDS_REVIEW"


def test_absence_partial_unknown_and_unsupported_are_not_safe():
    inventory, feed = inputs()
    feed.advisories = []
    results = UbuntuAssessmentEngine().assess(inventory, feed)
    assert {r.processing_status for r in results} == {"NO_MATCHING_RECORD", "NOT_INSTALLED"}
    assert all(r.verdict is None for r in results)
    inventory.collection_status = "PARTIAL"
    inventory.coverage.package_list_complete = False
    assert "PARTIAL_COLLECTION" in {
        r.processing_status for r in UbuntuAssessmentEngine().assess(inventory, feed)
    }
    inventory.os.version_id = "26.04"
    assert finding(inventory, feed).processing_status == "OUT_OF_SCOPE"
    inventory.collection_status = "FAILED"
    assert (
        UbuntuAssessmentEngine().assess(inventory, feed)[0].processing_status == "COLLECTION_FAILED"
    )


def test_explicit_unaffected_rule_and_reproducibility():
    inventory, feed = inputs()
    feed.advisories[0].rules[0].status = "NOT_AFFECTED"
    analysis_id = uuid4()
    first = finding(inventory, feed, analysis_id=analysis_id, evaluated_at=NOW)
    assert first.verdict == "NOT_AFFECTED"
    assert finding(inventory, feed, analysis_id=analysis_id, evaluated_at=NOW) == first
    feed.advisories[0].rules[0].status = "UNKNOWN"
    assert finding(inventory, feed).verdict == "NEEDS_REVIEW"


def test_candidate_binary_name_cannot_substitute_source_identity():
    inventory, feed = inputs()
    inventory.packages[0].source_name = None
    assert finding(inventory, feed).verdict == "NEEDS_REVIEW"
    inventory.packages[0].origin_evidence_ref = None
    assert "UNKNOWN_ORIGIN" in finding(inventory, feed).reason_codes


def test_incomplete_identity_cannot_prove_target_absent_in_a_complete_list():
    inventory, feed = inputs()
    inventory.packages[0].source_name = None
    inventory.packages[0].binary_name = "unrecognized-binary"
    results = UbuntuAssessmentEngine().assess(inventory, feed)
    assert "NOT_INSTALLED" not in {r.processing_status for r in results}
    assert sum(r.processing_status == "PARTIAL_COLLECTION" for r in results) == 2


def test_binary_rules_are_not_applied_to_a_whole_source_package():
    inventory, feed = inputs()
    feed.advisories[0].rules[0].package_kind = "BINARY"
    result = finding(inventory, feed)
    assert result.verdict == "NEEDS_REVIEW"
    assert "UNSUPPORTED_RULE" in result.reason_codes
