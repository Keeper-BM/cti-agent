import copy
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.models.tables import ComparisonRun
from backend.sources.service import sync_source_job
from backend.worker.runner import run_once
from tests.integration import test_assessments as assessment_tests
from tests.integration import test_sources as source_tests
from tests.integration.test_inventories import SAMPLE

source_wire = source_tests.source_wire


def setup(client, headers, engine):
    source_tests.execute(client, headers, engine, "ubuntu")
    original = assessment_tests.inventory(client, headers)
    baseline = assessment_tests.enqueue(client, headers, original)
    run_once(engine)
    changed = copy.deepcopy(SAMPLE)
    changed["packages"][0]["binary_version"] = "2.4.52-1ubuntu4.1"
    changed["packages"][0]["source_version"] = "2.4.52-1ubuntu4.1"
    newer = client.post(
        f"/api/v1/assets/{original['asset_id']}/inventories", headers=headers, json=changed
    ).json()
    return original, baseline, newer


def request(client, headers, baseline, target, key=None):
    return client.post(
        "/api/v1/comparisons",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "baseline_analysis_id": baseline["id"],
            "target_inventory_id": target["inventory_id"],
        },
    )


def test_fixed_baseline_and_comparison_inputs_survive_new_feed(
    client, headers, engine, source_wire
):
    before, baseline, after = setup(client, headers, engine)
    response = request(client, headers, baseline, after, "compare-one")
    assert response.status_code == 202, response.text
    run = response.json()
    assert request(client, headers, baseline, after, "compare-one").json()["id"] == run["id"]
    source_wire["ubuntu"]["vulns"][0]["affected"][0]["ranges"][0]["events"][1]["fixed"] = (
        "2.4.52-1ubuntu4.99"
    )
    source_job = source_tests.enqueue(client, headers, "ubuntu")
    sync_source_job(engine, source_job)
    while run_once(engine):
        pass
    saved = client.get("/api/v1/comparisons/" + run["id"], headers=headers).json()
    assert saved["job"]["status"] == "SUCCEEDED"
    result = saved["result"]
    assert result["source_snapshot_ids"] == [s["id"] for s in baseline["sources"]]
    row = next(r for r in result["rows"] if r["cve_id"])
    assert row["change"] == "CHANGED"
    assert (
        row["before"][0]["version_comparison"] == "MEETS_FIX"
        and row["after"][0]["version_comparison"] == "BELOW_FIX"
    )
    assert (
        row["before"][0]["fixed_version"] == row["after"][0]["fixed_version"] == "2.4.52-1ubuntu4.4"
    )
    assert row["after"][0]["verdict"] == "NEEDS_REVIEW"
    assert row["after"][0]["remediation"]["priority"] == "HIGH_REVIEW"
    assert client.get("/api/v1/comparisons", headers=headers).json()["total"] == 1
    assert request(client, headers, baseline, before).status_code == 422
    assert request(client, headers, baseline, after, "compare-one").json()["id"] == run["id"]


def test_invalid_tampered_or_other_asset_comparison(client, headers, engine, source_wire):
    before, baseline, after = setup(client, headers, engine)
    other = assessment_tests.inventory(client, headers, name="other")
    assert request(client, headers, baseline, other).status_code == 404
    run = request(client, headers, baseline, after).json()
    with Session(engine) as db, db.begin():
        db.get(ComparisonRun, run["id"]).input_sha256 = "wrong"
    run_once(engine)
    failed = client.get("/api/v1/comparisons/" + run["id"], headers=headers).json()
    assert failed["job"]["error_code"] == "COMPARISON_INPUT_CHANGED" and failed["result"] is None
    assert client.get("/api/v1/comparisons").status_code == 401
