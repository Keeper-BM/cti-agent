import copy
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.tables import Job, SecuritySnapshot, SourceDocument, SourceRecord
from backend.sources.http import APACHE_URL, KEV_URL, NVD_URL, OSV_URL, SourceHTTP
from backend.sources.service import sync_source_job
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.fixtures.security_sources import APACHE, CVE, KEV, NVD, ORACLE, OTHER_CVE, UBUNTU


@pytest.fixture
def source_wire(monkeypatch):
    state = {
        "ubuntu": copy.deepcopy(UBUNTU),
        "nvd": copy.deepcopy(NVD),
        "kev": copy.deepcopy(KEV),
        "apache": APACHE,
        "oracle": ORACLE,
        "fail": None,
    }

    def respond(request):
        origin = str(request.url).split("?", 1)[0]
        key = {OSV_URL: "ubuntu", NVD_URL: "nvd", KEV_URL: "kev", APACHE_URL: "apache"}.get(
            origin, "oracle"
        )
        if state["fail"] == key:
            return httpx.Response(503)
        value = state[key]
        return (
            httpx.Response(200, text=value)
            if isinstance(value, str)
            else httpx.Response(200, json=value)
        )

    monkeypatch.setattr("backend.sources.http._nvd_next_request", 0)
    monkeypatch.setattr(
        "backend.sources.service.SourceHTTP",
        lambda key: SourceHTTP(key, transport=httpx.MockTransport(respond)),
    )
    return state


def enqueue(client, headers, source, payload=None, key=None):
    response = client.post(
        f"/api/v1/sources/{source}/sync",
        json=payload or {},
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def execute(client, headers, engine, source, payload=None):
    job = enqueue(client, headers, source, payload)
    assert run_once(engine)
    result = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
    assert result["status"] == "SUCCEEDED", result
    return result["result"]["snapshot_id"]


def test_five_sources_join_by_cve_and_preserve_originals(client, headers, engine, source_wire):
    for source, payload in [
        ("ubuntu", {}),
        ("nvd", {"cve_id": CVE}),
        ("kev", {}),
        ("apache", {}),
        ("oracle", {"url": "https://www.oracle.com/security-alerts/cpujan2024.html"}),
    ]:
        execute(client, headers, engine, source, payload)
    detail = client.get(f"/api/v1/sources/cves/{CVE}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert {r["source_id"] for r in data["records"]} == {"ubuntu", "nvd", "kev", "apache", "oracle"}
    assert data["kev_status"] == "LISTED"
    assert data["oracle_urls"] == ["https://www.oracle.com/security-alerts/cpujan2024.html"]
    assert (
        next(r for r in data["records"] if r["source_id"] == "ubuntu")["data"]["fixed_version"]
        == "2.4.52-1ubuntu4.4"
    )
    for record in data["records"]:
        raw = client.get(f"/api/v1/sources/documents/{record['document']['id']}", headers=headers)
        assert raw.status_code == 200 and raw.json()["sha256"] == record["document"]["sha256"]
        assert "raw_text" not in record["document"]
    assert (
        client.get("/api/v1/sources/records?cve=CVE-2099&limit=2", headers=headers).json()["total"]
        == 5
    )
    assert len(client.get("/api/v1/sources/status", headers=headers).json()["items"]) == 5


def test_revision_selection_and_failed_refresh_preserve_previous_data(
    client, headers, engine, source_wire
):
    old = execute(client, headers, engine, "ubuntu")
    source_wire["ubuntu"]["vulns"][0]["details"] = "New description"
    new = execute(client, headers, engine, "ubuntu")
    latest = client.get("/api/v1/sources/records?source_id=ubuntu", headers=headers).json()
    assert latest["total"] == 1 and latest["items"][0]["snapshot_id"] == new
    previous = client.get(f"/api/v1/sources/records?snapshot_id={old}", headers=headers).json()
    assert previous["items"][0]["data"]["description"] != "New description"
    source_wire["fail"] = "ubuntu"
    job = enqueue(client, headers, "ubuntu")
    run_once(engine)
    assert client.get(f"/api/v1/jobs/{job}", headers=headers).json()["status"] == "FAILED"
    status = client.get("/api/v1/sources/status", headers=headers).json()["items"][0]
    assert status["latest_job"]["error_code"] == "SOURCE_HTTP_ERROR"
    assert status["latest_snapshot"]["id"] == new
    assert client.get("/api/v1/sources/snapshots", headers=headers).json()["total"] == 2


def test_missing_and_unlisted_kev_are_distinct(client, headers, engine, source_wire):
    execute(client, headers, engine, "ubuntu")
    assert (
        client.get(f"/api/v1/sources/cves/{CVE}", headers=headers).json()["kev_status"]
        == "NOT_FETCHED"
    )
    source_wire["kev"]["vulnerabilities"][0]["cveID"] = OTHER_CVE
    execute(client, headers, engine, "kev")
    assert (
        client.get(f"/api/v1/sources/cves/{CVE}", headers=headers).json()["kev_status"]
        == "NOT_LISTED"
    )


def test_idempotency_auth_scope_and_no_automatic_external_fetch(
    client, headers, engine, source_wire
):
    assert client.get("/api/v1/sources/status").status_code == 401
    assert client.post("/api/v1/sources/ubuntu/sync", json={}).status_code == 401
    first = enqueue(client, headers, "ubuntu", key="same")
    assert enqueue(client, headers, "ubuntu", key="same") == first
    assert enqueue(client, headers, "ubuntu", key="pending") == first
    response = client.post(
        "/api/v1/sources/nvd/sync",
        headers={**headers, "Idempotency-Key": "same"},
        json={"cve_id": CVE},
    )
    assert response.status_code == 409
    response = client.post(
        "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "same"}
    )
    assert response.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SourceDocument)) == 0
    assert client.get(f"/api/v1/sources/cves/{CVE}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    ("source", "body"),
    [
        ("nvd", {}),
        ("ubuntu", {"package": "unapproved"}),
        ("ubuntu", {"release": "26.04"}),
        ("kev", {"cve_id": CVE}),
        ("oracle", {"url": "http://localhost/secrets"}),
        ("ubuntu", {"command": "anything"}),
    ],
)
def test_invalid_source_request_is_not_enqueued(client, headers, source, body):
    response = client.post(
        f"/api/v1/sources/{source}/sync",
        json=body,
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 422
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 0


def test_pagination_failure_cannot_publish_partial_snapshot(client, headers, engine, source_wire):
    source_wire["ubuntu"]["next_page_token"] = "repeated-token"
    job = enqueue(client, headers, "ubuntu")
    run_once(engine)
    assert client.get(f"/api/v1/jobs/{job}", headers=headers).json()["status"] == "FAILED"
    with Session(engine) as db:
        for model in [SecuritySnapshot, SourceRecord, SourceDocument]:
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_committed_snapshot_and_job_survive_worker_restart(client, headers, engine, source_wire):
    job_id = enqueue(client, headers, "ubuntu")
    with Session(engine) as db, db.begin():
        db.get(Job, job_id).status = "RUNNING"
    # Simulate process termination after the source transaction, before runner finalization.
    sync_source_job(engine, job_id)
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert db.scalar(select(Job)).status == "SUCCEEDED"
        assert db.scalar(select(func.count()).select_from(SecuritySnapshot)) == 1
