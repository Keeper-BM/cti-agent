import copy
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.assessment.service import assess_job
from backend.models.tables import AnalysisRun, FindingRecord, Job
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.fixtures.security_sources import CVE
from tests.integration.test_inventories import SAMPLE
from tests.integration.test_sources import execute, source_wire  # noqa: F401

# Register the shared wire fixture without a same-name test argument shadowing its import.
source_fixture = source_wire


def inventory(client, headers, name="assessment-lab", **changes):
    asset = client.post(
        "/api/v1/assets",
        headers=headers,
        json={"asset_name": name, "exposure_source": "test", "expected_release": "22.04"},
    ).json()
    response = client.post(
        f"/api/v1/assets/{asset['id']}/inventories",
        headers=headers,
        json={**copy.deepcopy(SAMPLE), **changes},
    )
    assert response.status_code == 201, response.text
    return response.json()


def enqueue(client, headers, inv, key=None):
    response = client.post(
        "/api/v1/analyses",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"inventory_id": inv["inventory_id"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def results(client, headers, analysis):
    return client.get(f"/api/v1/findings?analysis_id={analysis['id']}", headers=headers).json()


def test_frozen_sources_versions_risks_raw_evidence_and_restart(
    client, headers, engine, source_wire
):
    for source, body in [("ubuntu", {}), ("nvd", {"cve_id": CVE}), ("kev", {}), ("apache", {})]:
        execute(client, headers, engine, source, body)
    inv = inventory(client, headers)
    old = enqueue(client, headers, inv)
    # Publish another Ubuntu revision while the analysis remains queued.
    source_wire["ubuntu"]["vulns"][0]["affected"][0]["ranges"][0]["events"][1]["fixed"] = (
        "2.4.52-1ubuntu4.99"
    )
    from backend.sources.service import sync_source_job
    from tests.integration.test_sources import enqueue as enqueue_source

    new_source_job = enqueue_source(client, headers, "ubuntu")
    sync_source_job(engine, new_source_job)
    assert run_once(engine)
    listing = results(client, headers, old)
    item = next(i for i in listing["items"] if i["cve_id"])
    assert item["fixed_version"] == "2.4.52-1ubuntu4.4"
    assert item["version_comparison"] == "MEETS_FIX"
    assert item["verdict"] == "NEEDS_REVIEW"
    assert item["kev_status"] == "LISTED" and item["nvd_metrics"][0]["score"] == 9.8
    detail = client.get(f"/api/v1/findings/{item['finding_id']}", headers=headers).json()
    assert {r["source_id"] for r in detail["related_records"]} == {"ubuntu", "nvd", "kev", "apache"}
    for record in detail["related_records"]:
        raw = client.get(f"/api/v1/sources/documents/{record['document']['id']}", headers=headers)
        assert raw.status_code == 200
    newer = enqueue(client, headers, inv)
    run_once(engine)
    assert (
        next(i for i in results(client, headers, newer)["items"] if i["cve_id"])[
            "version_comparison"
        ]
        == "BELOW_FIX"
    )
    with TestClient(create_app()) as fresh:
        assert results(fresh, headers, old) == listing
        assert fresh.get(f"/api/v1/findings/{item['finding_id']}", headers=headers).json() == detail
    history = client.get(
        f"/api/v1/analyses?asset_id={inv['asset_id']}&limit=1", headers=headers
    ).json()
    assert history["total"] == 2 and history["items"][0]["id"] == newer["id"]
    assert history["items"][0]["completed_at"].endswith("Z")


def test_missing_sources_and_partial_inventory_do_not_turn_safe(client, headers, engine):
    inv = inventory(client, headers, packages=[SAMPLE["packages"][0]])
    analysis = enqueue(client, headers, inv)
    run_once(engine)
    listing = results(client, headers, analysis)
    assert {i["processing_status"] for i in listing["items"]} == {
        "NO_MATCHING_RECORD",
        "PARTIAL_COLLECTION",
    }
    assert all(i["verdict"] is None for i in listing["items"])
    assert analysis["is_synthetic"] and analysis["warnings"]
    assert results(client, headers, analysis)["total"] == 2
    assert (
        client.get(
            f"/api/v1/findings?analysis_id={analysis['id']}&search=%25", headers=headers
        ).json()["total"]
        == 0
    )


def test_idempotency_authorization_scope_inactive_and_unknown(client, headers, engine):
    inv = inventory(client, headers)
    body = {"inventory_id": inv["inventory_id"]}
    assert client.post("/api/v1/analyses", json=body).status_code == 401
    assert client.get("/api/v1/findings").status_code == 401
    assert client.get("/api/v1/analyses").status_code == 401
    first = enqueue(client, headers, inv, "analysis-key")
    assert enqueue(client, headers, inv, "analysis-key")["id"] == first["id"]
    other = inventory(client, headers, name="second")
    response = client.post(
        "/api/v1/analyses",
        headers={**headers, "Idempotency-Key": "analysis-key"},
        json={"inventory_id": other["inventory_id"]},
    )
    assert response.status_code == 409
    assert (
        client.post(
            "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "analysis-key"}
        ).status_code
        == 409
    )
    client.patch(f"/api/v1/assets/{other['asset_id']}", headers=headers, json={"is_active": False})
    assert (
        client.post(
            "/api/v1/analyses",
            headers={**headers, "Idempotency-Key": "inactive"},
            json={"inventory_id": other["inventory_id"]},
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/analyses/{uuid4()}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/findings/{uuid4()}", headers=headers).status_code == 404
    run_once(engine)
    assert (
        client.get(
            f"/api/v1/findings?analysis_id={first['id']}&asset_id={other['asset_id']}",
            headers=headers,
        ).json()["total"]
        == 0
    )


def test_failure_is_atomic_and_previous_results_survive(
    client, headers, engine, source_wire, monkeypatch
):
    execute(client, headers, engine, "ubuntu")
    inv = inventory(client, headers)
    first = enqueue(client, headers, inv)
    run_once(engine)
    old_results = results(client, headers, first)
    second = enqueue(client, headers, inv)
    monkeypatch.setattr("backend.assessment.engine.MAX_FINDINGS", 1)
    run_once(engine)
    failed = client.get(f"/api/v1/analyses/{second['id']}", headers=headers).json()
    assert failed["job"]["status"] == "FAILED" and failed["job"]["error_code"] == "ANALYSIS_LIMIT"
    assert failed["completed_at"] is None
    assert results(client, headers, second)["total"] == 0
    assert results(client, headers, first) == old_results


def test_committed_results_survive_worker_restart(client, headers, engine):
    analysis = enqueue(client, headers, inventory(client, headers))
    with Session(engine) as db, db.begin():
        db.get(Job, analysis["job"]["id"]).status = "RUNNING"
    assess_job(engine, analysis["job"]["id"])
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert db.get(Job, analysis["job"]["id"]).status == "SUCCEEDED"
        assert db.get(AnalysisRun, analysis["id"]).feed_payload
        assert db.scalar(select(func.count()).select_from(FindingRecord)) == 2


def test_finding_priority_is_global_stable_and_preserves_search_and_filters(
    client, headers, engine
):
    from backend.assessment.contracts import AssessmentFinding
    from tests.unit.test_assessment import finding, inputs

    inv = inventory(client, headers)
    analysis = enqueue(client, headers, inv)
    run_once(engine)
    template = finding(*inputs()).model_dump(mode="json")
    # Deliberately insert findings in a different order from both CVE and display priority.
    cases = [
        (11, None, "OUT_OF_SCOPE", None, "apt"),
        (6, "NOT_AFFECTED", "EVALUATED", "CVE-2099-10001", "mysql-server-8.0"),
        (5, "FIXED", "EVALUATED", "CVE-2099-20001", "apache2"),
        (4, "NEEDS_REVIEW", "EVALUATED", "CVE-2099-50001", "apache2"),
        (3, "AFFECTED", "EVALUATED", "CVE-2099-90001", "apache2-bin"),
        (2, "AFFECTED", "EVALUATED", "CVE-2099-90001", "apache2"),
        (1, "AFFECTED", "EVALUATED", "CVE-2099-90001", "apache2"),
        (10, None, "NOT_INSTALLED", None, "mysql-8.0"),
        (9, None, "NO_MATCHING_RECORD", None, "apache2"),
        (8, None, "PARTIAL_COLLECTION", None, "mysql-8.0"),
        (7, None, "COLLECTION_FAILED", None, None),
    ]
    original = {}
    with Session(engine) as db, db.begin():
        db.execute(delete(FindingRecord).where(FindingRecord.analysis_id == analysis["id"]))
        for number, verdict, status, cve, package in cases:
            payload = AssessmentFinding.model_validate(
                {
                    **template,
                    "finding_id": str(UUID(int=number)),
                    "analysis_id": analysis["id"],
                    "asset_id": inv["asset_id"],
                    "inventory_id": inv["inventory_id"],
                    "verdict": verdict,
                    "processing_status": status,
                    "cve_id": cve,
                    "package_name": package,
                }
            ).model_dump(mode="json")
            original[payload["finding_id"]] = payload
            db.add(
                FindingRecord(
                    id=payload["finding_id"],
                    analysis_id=analysis["id"],
                    asset_id=inv["asset_id"],
                    package_name=package,
                    cve_id=cve,
                    processing_status=status,
                    verdict=verdict,
                    payload=payload,
                )
            )

    def query(**filters):
        response = client.get(
            "/api/v1/findings",
            headers=headers,
            params={"analysis_id": analysis["id"], **filters},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def ids(items):
        return [UUID(item["finding_id"]).int for item in items]

    all_items = query()["items"]
    assert ids(all_items) == list(range(1, 12))
    pages = [query(limit=2, offset=offset) for offset in range(0, 12, 2)]
    assert all(page["total"] == 11 for page in pages)
    assert [item for page in pages for item in page["items"]] == all_items
    assert query()["items"] == all_items
    assert ids(query(search="apache2")["items"]) == [1, 2, 3, 4, 5, 9]
    assert ids(query(verdict="AFFECTED", limit=2, offset=1)["items"]) == [2, 3]
    assert ids(query(processing_status="OUT_OF_SCOPE")["items"]) == [11]
    assert query(search="not-present")["total"] == 0
    assert {item["finding_id"]: item for item in all_items} == original
