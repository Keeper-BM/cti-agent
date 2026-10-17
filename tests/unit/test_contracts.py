import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.models.contracts import Finding, InventorySnapshot


def finding(**changes):
    return Finding(
        **{
            "finding_id": uuid4(),
            "analysis_id": uuid4(),
            "asset_id": uuid4(),
            "inventory_id": uuid4(),
            "processing_status": "NO_MATCHING_RECORD",
            "evaluated_at": datetime.now(UTC),
            "ruleset_version": "test-only",
            **changes,
        }
    )


def test_missing_evidence_is_not_an_unaffected_result():
    result = finding()
    assert result.verdict is None
    with pytest.raises(ValidationError):
        finding(verdict="NOT_AFFECTED")
    with pytest.raises(ValidationError):
        finding(processing_status="EVALUATED", verdict="FIXED")


def test_evaluated_findings_require_a_verdict():
    with pytest.raises(ValidationError):
        finding(processing_status="EVALUATED")
    result = finding(
        processing_status="EVALUATED",
        verdict="NEEDS_REVIEW",
        reason_codes=["NO_OFFICIAL_EVIDENCE"],
    )
    assert result.verdict == "NEEDS_REVIEW"


def test_snapshot_fixture_and_partial_collection_are_distinct():
    path = Path("tests/fixtures/inventory.synthetic.json")
    data = json.loads(path.read_text())
    InventorySnapshot.model_validate(data)
    data["collection_status"] = "PARTIAL"
    with pytest.raises(ValidationError):
        InventorySnapshot.model_validate(data)
    data["coverage"]["package_list_complete"] = False
    assert InventorySnapshot.model_validate(data).collection_status == "PARTIAL"


def test_collection_timestamp_requires_timezone():
    data = json.loads(Path("tests/fixtures/inventory.synthetic.json").read_text())
    data["collected_at"] = "2026-10-10T00:00:00"
    with pytest.raises(ValidationError):
        InventorySnapshot.model_validate(data)
