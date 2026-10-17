"""Connected example contracts and invalid-reference regression checks."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.examples.assessment import AssessmentExample, load_assessment_example
from backend.models.contracts import FeedSnapshot, Finding, InventorySnapshot


def test_one_cve_has_distinct_package_results_and_cited_explanation():
    example = load_assessment_example()
    affected, fixed = example.expected_findings
    assert affected.cve_id == fixed.cve_id
    assert affected.package_ref != fixed.package_ref
    assert affected.verdict == "AFFECTED"
    assert fixed.verdict == "FIXED"
    assert example.expected_answer.citations == affected.evidence_refs
    assert example.is_synthetic and example.feed.is_synthetic


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package_ref", str(uuid4())),
        ("matched_rule_id", str(uuid4())),
        ("installed_version", "wrong-version"),
        ("feed_snapshot_id", str(uuid4())),
    ],
)
def test_broken_example_links_are_rejected(field, value):
    data = load_assessment_example().model_dump(mode="json")
    data["expected_findings"][0][field] = value
    with pytest.raises(ValidationError):
        AssessmentExample.model_validate(data)


def test_answer_cannot_cite_unrelated_evidence():
    data = load_assessment_example().model_dump(mode="json")
    data["expected_answer"]["citations"][0]["document_version_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        AssessmentExample.model_validate(data)


def test_definite_verdict_requires_package_identity_and_comparison_context():
    data = load_assessment_example().expected_findings[0].model_dump(mode="json")
    for field in ("package_ref", "installed_version", "comparison_basis", "matched_rule_id"):
        incomplete = {**data, field: None}
        with pytest.raises(ValidationError):
            Finding.model_validate(incomplete)


def test_duplicate_package_and_rule_ids_are_rejected():
    example = load_assessment_example()
    inventory = example.inventory.model_dump(mode="json")
    inventory["packages"][1]["package_id"] = inventory["packages"][0]["package_id"]
    with pytest.raises(ValidationError):
        InventorySnapshot.model_validate(inventory)
    feed = example.feed.model_dump(mode="json")
    feed["advisories"].append(deepcopy(feed["advisories"][0]))
    with pytest.raises(ValidationError):
        FeedSnapshot.model_validate(feed)


def test_released_fix_requires_a_full_version():
    data = load_assessment_example().feed.model_dump(mode="json")
    data["advisories"][0]["rules"][0]["fixed_version"] = None
    with pytest.raises(ValidationError):
        FeedSnapshot.model_validate(data)
