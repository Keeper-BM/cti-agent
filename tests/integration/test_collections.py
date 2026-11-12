import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.collectors.ssh_protocol import CommandResult
from backend.core.config import get_settings
from backend.models.tables import CollectionRun, InventoryRecord, Job
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.fixtures.ssh_server import APACHE, APACHE_SERVICE, ssh_server
from tests.integration import test_sources as source_tests

source_wire = source_tests.source_wire


@pytest.fixture
def lab(client, headers, engine, tmp_path, monkeypatch):
    with ssh_server(tmp_path) as server:
        monkeypatch.setenv("SSH_ALLOWED_TARGETS", f"127.0.0.1:{server.port}")
        monkeypatch.setenv("SSH_KEY_DIRECTORY", str(tmp_path))
        get_settings.cache_clear()
        asset = client.post(
            "/api/v1/assets",
            headers=headers,
            json={"asset_name": "ssh-lab", "exposure_source": "test"},
        ).json()
        body = {
            "host": "127.0.0.1",
            "port": server.port,
            "username": "collector",
            "key_alias": server.key_file.name,
            "host_fingerprint": server.host_key.fingerprint,
        }
        response = client.put(
            f"/api/v1/assets/{asset['id']}/ssh-profile", headers=headers, json=body
        )
        assert response.status_code == 200, response.text
        yield server, asset, response.json(), body


def enqueue(client, headers, asset, profile, key=None):
    response = client.post(
        f"/api/v1/assets/{asset['id']}/collections",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"profile_id": profile["id"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def get_run(client, headers, asset, run):
    return client.get(
        f"/api/v1/assets/{asset['id']}/collections/{run['id']}", headers=headers
    ).json()


def test_loopback_collection_persists_inventory_and_readonly_evidence(client, headers, engine, lab):
    server, asset, profile, _ = lab
    run = enqueue(client, headers, asset, profile, "one")
    assert not server.commands
    assert enqueue(client, headers, asset, profile, "one")["id"] == run["id"]
    run_once(engine)
    detail = get_run(client, headers, asset, run)
    assert detail["job"]["status"] == "SUCCEEDED"
    snapshot = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{detail['inventory_id']}", headers=headers
    ).json()
    assert snapshot["collection_method"] == "SSH" and len(snapshot["packages"]) == 2
    assert all(p["origin_status"] == "UNKNOWN" for p in snapshot["packages"])
    assert detail["evidence"]["verified_host_fingerprint"] == profile["host_fingerprint"]
    assert detail["evidence"]["services"][0]["active_state"] == "active"
    assert detail["evidence"]["services"][1]["active_state"] == "inactive"
    assert "PRIVATE-REMOTE" not in str(detail)
    assert "PRIVATE KEY" not in str(detail)
    with TestClient(create_app()) as fresh:
        assert get_run(fresh, headers, asset, run) == detail
    assert (
        client.get(f"/api/v1/assets/{asset['id']}/collections", headers=headers).json()["total"]
        == 1
    )


@pytest.mark.parametrize(
    "output",
    [(124, ""), (126, ""), (0, "Id=apache2.service\n"), (0, APACHE_SERVICE * 2)],
)
def test_service_failure_is_partial_but_preserves_complete_packages(
    client, headers, engine, lab, output
):
    server, asset, profile, _ = lab
    first = enqueue(client, headers, asset, profile)
    run_once(engine)
    saved = get_run(client, headers, asset, first)
    server.outputs["service_apache2"] = output
    run = enqueue(client, headers, asset, profile)
    run_once(engine)
    detail = get_run(client, headers, asset, run)
    assert detail["job"]["status"] == "PARTIAL"
    assert detail["evidence"]["services"][0]["status"] == "UNKNOWN"
    assert detail["evidence"]["services"][1]["status"] == "OBSERVED"
    snapshot = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{detail['inventory_id']}", headers=headers
    ).json()
    assert snapshot["collection_status"] == "COMPLETE"
    assert snapshot["coverage"]["package_list_complete"] and len(snapshot["packages"]) == 2
    assert get_run(client, headers, asset, first) == saved


def test_missing_unit_is_a_successful_observation_not_missing_package(client, headers, engine, lab):
    server, asset, profile, _ = lab
    server.outputs["service_apache2"] = (
        0,
        "Id=apache2.service\nLoadState=not-found\nActiveState=inactive\nSubState=dead\nUnitFileState=\n",
    )
    run = enqueue(client, headers, asset, profile)
    run_once(engine)
    detail = get_run(client, headers, asset, run)
    assert detail["job"]["status"] == "SUCCEEDED"
    assert detail["evidence"]["services"][0]["status"] == "NOT_FOUND"
    snapshot = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{detail['inventory_id']}", headers=headers
    ).json()
    assert snapshot["packages"][0]["install_status"] == "installed"


def test_old_evidence_remains_readable_without_fabricating_service_states(
    client, headers, engine, lab
):
    _, asset, profile, _ = lab
    run = enqueue(client, headers, asset, profile)
    run_once(engine)
    with Session(engine) as db, db.begin():
        record = db.get(CollectionRun, run["id"])
        evidence = dict(record.evidence)
        evidence.pop("services")
        evidence["commands"] = [
            c for c in evidence["commands"] if not c["name"].startswith("service_")
        ]
        evidence["collector_version"] = "ubuntu-ssh/1.1"
        wire = "\n".join(
            CommandResult.model_validate(c).model_dump_json() for c in evidence["commands"]
        )
        evidence["output_sha256"] = hashlib.sha256(wire.encode()).hexdigest()
        record.evidence = evidence
    detail = get_run(client, headers, asset, run)
    assert detail["evidence"]["services"] == []
    assert detail["evidence"]["collector_version"] == "ubuntu-ssh/1.1"
    with Session(engine) as db:
        assert "services" not in db.get(CollectionRun, run["id"]).evidence


def test_queued_old_collector_version_requires_new_request(client, headers, engine, lab):
    server, asset, profile, _ = lab
    run = enqueue(client, headers, asset, profile)
    with Session(engine) as db, db.begin():
        db.get(CollectionRun, run["id"]).collector_version = "ubuntu-ssh/1.1"
    run_once(engine)
    detail = get_run(client, headers, asset, run)
    assert detail["job"]["status"] == "FAILED"
    assert detail["job"]["error_code"] == "COLLECTOR_CHANGED"
    assert detail["inventory_id"] is None and not server.commands


def test_partial_and_failure_preserve_previous_inventory(client, headers, engine, lab):
    server, asset, profile, _ = lab
    first = enqueue(client, headers, asset, profile)
    run_once(engine)
    first_saved = get_run(client, headers, asset, first)
    server.outputs["packages"] = (1, APACHE + "broken line\n")
    partial = enqueue(client, headers, asset, profile)
    run_once(engine)
    part = get_run(client, headers, asset, partial)
    assert part["job"]["status"] == "PARTIAL"
    snapshot = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{part['inventory_id']}", headers=headers
    ).json()
    assert (
        snapshot["collection_status"] == "PARTIAL"
        and not snapshot["coverage"]["package_list_complete"]
    )
    server.outputs["packages"] = (2, "")
    failure = enqueue(client, headers, asset, profile)
    run_once(engine)
    assert get_run(client, headers, asset, failure)["job"]["status"] == "FAILED"
    assert get_run(client, headers, asset, failure)["inventory_id"] is None
    assert get_run(client, headers, asset, first) == first_saved
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(InventoryRecord)) == 2
        assert db.get(CollectionRun, failure["id"]).active_slot is None


def test_pinned_profile_auth_allowlist_and_asset_scoping(client, headers, engine, lab, monkeypatch):
    server, asset, profile, body = lab
    assert client.get("/api/v1/collections/settings").status_code == 401
    assert client.get("/api/v1/collections/settings", headers=headers).json()["key_aliases"] == [
        "lab_key"
    ]
    old = enqueue(client, headers, asset, profile, "scope-key")
    newer = client.put(
        f"/api/v1/assets/{asset['id']}/ssh-profile",
        headers=headers,
        json={**body, "host_fingerprint": "SHA256:" + "x" * 43},
    ).json()
    run_once(engine)
    assert get_run(client, headers, asset, old)["job"]["status"] == "SUCCEEDED"
    bad = enqueue(client, headers, asset, newer)
    run_once(engine)
    assert get_run(client, headers, asset, bad)["job"]["error_code"] == "SSH_HOST_KEY_MISMATCH"
    collision = client.post(
        "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "scope-key"}
    )
    assert collision.status_code == 409
    other = client.post(
        "/api/v1/assets", headers=headers, json={"asset_name": "other", "exposure_source": "test"}
    ).json()
    assert (
        client.get(
            f"/api/v1/assets/{other['id']}/collections/{old['id']}", headers=headers
        ).status_code
        == 404
    )
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", "")
    get_settings.cache_clear()
    response = client.post(
        f"/api/v1/assets/{asset['id']}/collections",
        headers={**headers, "Idempotency-Key": "revoked"},
        json={"profile_id": profile["id"]},
    )
    assert response.status_code == 409


def test_invalid_inputs_never_start_network(client, headers, lab):
    server, asset, profile, body = lab
    for patch in [
        {"host": "example.com"},
        {"key_alias": "../key"},
        {"username": "root;whoami"},
        {"host_fingerprint": "invalid"},
        {"private_key": "PRIVATE"},
        {"port": "22"},
    ]:
        response = client.put(
            f"/api/v1/assets/{asset['id']}/ssh-profile", headers=headers, json={**body, **patch}
        )
        assert response.status_code == 422
    client.patch(f"/api/v1/assets/{asset['id']}", headers=headers, json={"is_active": False})
    response = client.post(
        f"/api/v1/assets/{asset['id']}/collections",
        headers={**headers, "Idempotency-Key": "inactive"},
        json={"profile_id": profile["id"]},
    )
    assert response.status_code == 409 and not server.commands


def test_restart_releases_slot_and_does_not_repeat_remote_command(client, headers, engine, lab):
    server, asset, profile, _ = lab
    run = enqueue(client, headers, asset, profile)
    with Session(engine) as db, db.begin():
        db.get(Job, run["job"]["id"]).status = "RUNNING"
    recover_interrupted_jobs(engine)
    assert get_run(client, headers, asset, run)["job"]["error_code"] == "WORKER_RESTARTED"
    with Session(engine) as db:
        assert db.get(CollectionRun, run["id"]).active_slot is None
    assert not server.commands


def test_allowlist_is_rechecked_by_worker_and_duplicate_jobs_are_blocked(
    client, headers, engine, lab, monkeypatch
):
    server, asset, profile, _ = lab
    run = enqueue(client, headers, asset, profile)
    duplicate = client.post(
        f"/api/v1/assets/{asset['id']}/collections",
        headers={**headers, "Idempotency-Key": "second"},
        json={"profile_id": profile["id"]},
    )
    assert duplicate.status_code == 409
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", "")
    get_settings.cache_clear()
    run_once(engine)
    assert get_run(client, headers, asset, run)["job"]["error_code"] == "SSH_TARGET_NOT_ALLOWED"
    assert not server.commands
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(InventoryRecord)) == 0


def test_ssh_to_analysis_and_report_preserves_unverified_origin(
    client, headers, engine, lab, source_wire
):
    server, asset, profile, _ = lab
    # Real SSH protocol with synthetic command output; this fixture is not an Ubuntu VM.
    server.outputs["os_release"] = (0, 'ID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n')
    source_tests.execute(client, headers, engine, "ubuntu")
    run = enqueue(client, headers, asset, profile)
    run_once(engine)
    saved = get_run(client, headers, asset, run)
    analysis = client.post(
        "/api/v1/analyses",
        headers={**headers, "Idempotency-Key": "ssh-analysis"},
        json={"inventory_id": saved["inventory_id"]},
    )
    assert analysis.status_code == 202, analysis.text
    analysis = analysis.json()
    run_once(engine)
    findings = client.get(f"/api/v1/findings?analysis_id={analysis['id']}", headers=headers).json()
    matched = [item for item in findings["items"] if item["cve_id"]]
    assert matched and all(item["verdict"] == "NEEDS_REVIEW" for item in matched)
    report = client.post(
        "/api/v1/reports",
        headers={**headers, "Idempotency-Key": "ssh-report"},
        json={"analysis_id": analysis["id"]},
    )
    assert report.status_code == 202, report.text
    run_once(engine)
    path = f"/api/v1/reports/{report.json()['id']}"
    content = client.get(path, headers=headers).json()
    assert content["job"]["status"] == "SUCCEEDED"
    downloaded = client.get(f"{path}/markdown", headers=headers)
    assert downloaded.status_code == 200 and "추가 확인 필요" in downloaded.text
    enqueue(client, headers, asset, profile)
    run_once(engine)
    assert client.get(path, headers=headers).json() == content
