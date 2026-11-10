import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.collectors.ssh_protocol import CommandResult, make_inventory
from backend.core.config import get_settings
from backend.models.tables import CollectionRun, InventoryRecord, Job, VerificationRun
from backend.verification.contracts import PACKAGES
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.fixtures.ssh_server import DEFAULT_OUTPUTS
from tests.integration import test_sources as source_tests

source_wire = source_tests.source_wire


@pytest.fixture
def verification_lab(client, headers, engine, tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_bytes(b"test-key-placeholder")
    key.chmod(0o600)
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", "127.0.0.1:2222")
    monkeypatch.setenv("SSH_KEY_DIRECTORY", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("backend.api.routes.verifications.gpg_executable", lambda config: "test")
    asset = client.post(
        "/api/v1/assets",
        headers=headers,
        json={"asset_name": "verify-lab", "exposure_source": "test"},
    ).json()
    profile = client.put(
        f"/api/v1/assets/{asset['id']}/ssh-profile",
        headers=headers,
        json={
            "host": "127.0.0.1",
            "port": 2222,
            "username": "collector",
            "key_alias": "key",
            "host_fingerprint": "SHA256:" + "x" * 43,
        },
    ).json()
    outputs = [
        CommandResult(name=n, exit_code=c, stdout=t) for n, (c, t) in DEFAULT_OUTPUTS.items()
    ]
    outputs[0].stdout = 'ID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n'
    run_id = str(uuid4())
    inventory, _ = make_inventory(UUID(asset["id"]), run_id, outputs, profile["host_fingerprint"])
    with Session(engine) as db, db.begin():
        job = Job(kind="SSH_COLLECTION", status="SUCCEEDED", idempotency_key=str(uuid4()))
        db.add(job)
        db.flush()
        db.add(
            InventoryRecord(
                inventory_id=str(inventory.inventory_id),
                asset_id=asset["id"],
                collected_at=inventory.collected_at,
                ingested_at=inventory.ingested_at,
                os_release="22.04",
                package_count=len(inventory.packages),
                collection_status="COMPLETE",
                is_synthetic=False,
                payload=inventory.model_dump(mode="json"),
            )
        )
        db.flush()
        db.add(
            CollectionRun(
                id=run_id,
                job_id=job.id,
                asset_id=asset["id"],
                profile_id=profile["id"],
                inventory_id=str(inventory.inventory_id),
                collector_version="test",
            )
        )
    state = {"status": "OK", "hash": "a" * 64, "changed": False}
    monkeypatch.setattr("backend.verification.service.collect_ssh", lambda *_: outputs)

    def resolve(fresh):
        file = {"kind": "file", "sha256": "a" * 64, "mode": 0o755, "uid": 0, "gid": 0}
        return {
            str(p.package_id): {
                "files": {"/usr/bin/example": file},
                "proof": {"package_sha256": "a" * 64},
            }
            for p in fresh.packages
            if p.binary_name in PACKAGES
        }

    def execute(*args):
        packages = next(r.stdout for r in outputs if r.name == "packages")
        value = {
            "before": packages,
            "after": packages + "changed" if state["changed"] else packages,
            "files": {
                "/usr/bin/example": {
                    "kind": "file",
                    "status": state["status"],
                    "sha256": state["hash"],
                    "mode": 0o755,
                    "uid": 0,
                    "gid": 0,
                }
            },
        }
        return [CommandResult(name="files", exit_code=0, stdout=json.dumps(value))]

    monkeypatch.setattr(
        "backend.verification.service.ArchiveClient",
        lambda *_: SimpleNamespace(resolve=resolve, close=lambda: None),
    )
    monkeypatch.setattr("backend.verification.service.run_ssh_commands", execute)
    return asset, inventory, state


def enqueue(client, headers, asset, inv, key=None):
    response = client.post(
        f"/api/v1/assets/{asset['id']}/verifications",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"inventory_id": str(inv.inventory_id)},
    )
    assert response.status_code == 202, response.text
    return response.json()


def detail(client, headers, asset, run):
    return client.get(
        f"/api/v1/assets/{asset['id']}/verifications/{run['id']}", headers=headers
    ).json()


def test_verified_snapshot_is_new_and_frozen_analysis_can_use_it(
    client, headers, engine, verification_lab, source_wire
):
    asset, original, _ = verification_lab
    first = enqueue(client, headers, asset, original, "same-key")
    assert enqueue(client, headers, asset, original, "same-key")["id"] == first["id"]
    run_once(engine)
    run = detail(client, headers, asset, first)
    assert run["job"]["status"] == "SUCCEEDED" and run["verified_inventory_id"] != str(
        original.inventory_id
    )
    old = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{original.inventory_id}", headers=headers
    ).json()
    assert all(p["origin_status"] == "UNKNOWN" for p in old["packages"])
    fresh = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{run['verified_inventory_id']}", headers=headers
    ).json()
    assert all(p["origin_status"] == "OFFICIAL_MATCH" for p in fresh["packages"])
    source_tests.execute(client, headers, engine, "ubuntu")
    response = client.post(
        "/api/v1/analyses",
        headers={**headers, "Idempotency-Key": "analysis"},
        json={"inventory_id": fresh["inventory_id"]},
    )
    assert response.status_code == 202
    analysis = response.json()
    run_once(engine)
    results = client.get(
        "/api/v1/findings",
        headers=headers,
        params={"analysis_id": analysis["id"], "verdict": "FIXED"},
    ).json()
    assert results["total"] == 1
    report = client.post(
        "/api/v1/reports",
        headers={**headers, "Idempotency-Key": "report"},
        json={"analysis_id": analysis["id"]},
    ).json()
    run_once(engine)
    saved = client.get(f"/api/v1/reports/{report['id']}", headers=headers).json()
    assert saved["content"]["verification"]["original_inventory_id"] == str(original.inventory_id)
    assert (
        "공식 패키지 파일 검증"
        in client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers).text
    )


@pytest.mark.parametrize(("status", "digest"), [("OK", "b" * 64), ("UNREADABLE", "a" * 64)])
def test_partial_checks_never_promote_unknown_origin(
    client, headers, engine, verification_lab, status, digest
):
    asset, original, state = verification_lab
    state["status"], state["hash"] = status, digest
    run = enqueue(client, headers, asset, original)
    run_once(engine)
    result = detail(client, headers, asset, run)
    assert result["job"]["status"] == "PARTIAL"
    saved = client.get(
        f"/api/v1/assets/{asset['id']}/inventories/{result['verified_inventory_id']}",
        headers=headers,
    ).json()
    assert all(p["origin_status"] == "UNKNOWN" for p in saved["packages"])


def test_changing_package_state_aborts_and_releases_slot(client, headers, engine, verification_lab):
    asset, original, state = verification_lab
    state["changed"] = True
    run = enqueue(client, headers, asset, original)
    run_once(engine)
    failed = detail(client, headers, asset, run)
    assert (
        failed["job"]["error_code"] == "VERIFICATION_STALE"
        and failed["verified_inventory_id"] is None
    )
    with Session(engine) as db:
        assert db.get(VerificationRun, run["id"]).active_slot is None
    pending = enqueue(client, headers, asset, original)
    with Session(engine) as db, db.begin():
        db.get(Job, pending["job"]["id"]).status = "RUNNING"
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert (
            db.scalar(
                select(VerificationRun).where(VerificationRun.id == pending["id"])
            ).active_slot
            is None
        )
