from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.models.tables import CollectionRun, Job, SourceRun
from backend.reports.batch import build_batch_report
from backend.reports.markdown import text
from backend.worker.runner import run_once
from tests.fixtures.ssh_server import APACHE, DEFAULT_OUTPUTS, MYSQL, ssh_server
from tests.integration import test_auth as auth
from tests.integration import test_workflows as workflows

lab = workflows.lab
source_wire = workflows.source_wire
accounts = auth.accounts

BATCH = "/api/v1/workflow-batches"


def register(client, headers, asset_name):
    result = client.post(
        "/api/v1/assets",
        headers=headers,
        json={"asset_name": asset_name, "exposure_source": "test"},
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def add_profile(client, headers, asset_id, body):
    result = client.put(f"/api/v1/assets/{asset_id}/ssh-profile", headers=headers, json=body)
    assert result.status_code == 200, result.text


def request_batch(client, headers, ids, key="first-request"):
    return client.post(BATCH, headers={**headers, "Idempotency-Key": key}, json={"asset_ids": ids})


def settle(client, headers, engine, batch_id):
    path = f"{BATCH}/{batch_id}"
    for _ in range(45):
        run_once(engine)
        result = client.get(path, headers=headers)
        assert result.status_code == 200, result.text
        batch = result.json()
        if batch["status"] != "RUNNING":
            return batch
    raise AssertionError("batch did not settle")


@pytest.fixture
def archive_without_artifacts(monkeypatch):
    monkeypatch.setattr(
        "backend.verification.service.ArchiveClient",
        lambda *_: SimpleNamespace(resolve=lambda _inventory: {}, close=lambda: None),
    )


def test_batch_shares_sources_and_keeps_partial_report_when_retrying(
    client, headers, engine, lab, source_wire, tmp_path, monkeypatch, archive_without_artifacts
):
    first, asset, _, profile = lab
    second_id = register(client, headers, "Review server")
    missing_id = register(client, headers, "Third server")
    scope = source_wire["ubuntu"]["vulns"][0]["affected"][0]
    scope["package"]["ecosystem"] = "Ubuntu:24.04:LTS"
    scope["ranges"][0]["events"][-1]["fixed"] = "2.4.58-1ubuntu8.2"
    scope["versions"] = ["2.4.58-1ubuntu8.1"]
    # Test only the version comparison with two loopback protocol fixtures.
    fixed_apache = APACHE.replace("2.4.58-1ubuntu8.1", "2.4.58-1ubuntu8.3")
    first.outputs["packages"] = (0, fixed_apache + MYSQL)
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    with ssh_server(second_dir, outputs=dict(DEFAULT_OUTPUTS)) as second:
        second_key = tmp_path / "other_key"
        second.key_file.replace(second_key)
        monkeypatch.setenv("SSH_ALLOWED_TARGETS", f"127.0.0.1:{first.port},127.0.0.1:{second.port}")
        get_settings.cache_clear()
        add_profile(
            client,
            headers,
            second_id,
            {
                **profile,
                "port": second.port,
                "key_alias": second_key.name,
                "host_fingerprint": second.host_key.fingerprint,
            },
        )
        ids = [asset["id"], second_id, missing_id]
        result = request_batch(client, headers, ids)
        assert result.status_code == 202, result.text
        batch_id = result.json()["id"]
        path = f"{BATCH}/{batch_id}"
        assert request_batch(client, headers, ids[::-1]).json()["id"] == batch_id
        assert request_batch(client, headers, ids[:2]).status_code == 409
        assert request_batch(client, headers, [ids[0], ids[0]]).status_code == 422
        assert client.get(f"{path}/markdown", headers=headers).status_code == 409

        batch = settle(client, headers, engine, batch_id)
        assert batch["status"] == "PARTIAL" and batch["report_summary"], batch
        assert batch["report_status"] == "READY"
        assert batch["evaluated_cve_count"] == 1 and batch["affected_cve_count"] == 0
        members = {member["asset_id"]: member for member in batch["assets"]}
        assert members[second_id]["verdict_counts"]["NEEDS_REVIEW"] >= 1
        assert members[second_id]["coverage"] == "EVALUATED"
        assert members[second_id]["package_count"] == 2
        assert members[missing_id]["status"] == "FAILED"
        assert not members[missing_id]["analysis_id"]
        assert "SSH" in members[missing_id]["error"]
        assert first.commands and second.commands
        with Session(engine) as db:
            source_jobs = list(
                db.scalars(
                    select(SourceRun)
                    .join(Job)
                    .where(Job.idempotency_key.startswith(f"batch-{batch_id}-source-"))
                )
            )
            assert len(source_jobs) >= 4
            assert len(source_jobs) == len({(s.source_id, s.scope_key) for s in source_jobs})
        snapshots = []
        for asset_id in ids[:2]:
            view = client.get(f"/api/v1/assets/{asset_id}/workspace", headers=headers).json()
            snapshots.append({item["snapshot_id"] for item in view["latest"]["sources"]})
        assert snapshots[0] == snapshots[1] and None not in snapshots[0]
        assert {source["snapshot_id"] for source in batch["sources"]} == snapshots[0]
        assert all(len(source["asset_names"]) == 2 for source in batch["sources"])

        comparison = client.get(f"{path}/comparison", headers=headers).json()
        assert comparison["cve_id"] == workflows.sources.CVE
        compared = {row["asset_id"]: row for row in comparison["items"]}
        assert set(compared) == set(ids[:2])
        assert compared[ids[0]]["binary_version"] == "2.4.58-1ubuntu8.3"
        assert compared[ids[1]]["binary_version"] == "2.4.58-1ubuntu8.1"
        assert compared[ids[0]]["fixed_version"] == "2.4.58-1ubuntu8.2"
        assert compared[ids[0]]["ubuntu_snapshot_id"] == compared[ids[1]]["ubuntu_snapshot_id"]
        assert compared[ids[0]]["captured_at"]
        for priority in batch["report_summary"]["priorities"]:
            assert priority["finding_id"] == compared[priority["asset_id"]]["finding_id"]
            evidence = client.get(f"/api/v1/findings/{priority['finding_id']}", headers=headers)
            assert evidence.json()["cve_id"] == priority["cve_id"]
        assert client.get(f"{path}/comparison?cve_id=CVE-2024-1000", headers=headers).json() == {
            "cve_id": "CVE-2024-1000",
            "items": [],
        }

        original = client.get(f"{path}/markdown", headers=headers)
        assert original.status_code == 200
        assert original.headers["X-Content-SHA256"] == sha256(original.content).hexdigest()
        assert "선택 3대 · 평가 결과 있음 2대 · 미평가 0대 · 분석 실패 1대" in original.text
        assert "공식 자료 조회 결과" in original.text
        assert text("기준 시각 (KST)") in original.text
        assert all(text(member["asset_name"]) in original.text for member in members.values())
        assert f"### {text(workflows.sources.CVE)}" in original.text
        assert "추가 확인 필요" in original.text
        assert "수정 기준 이상" in original.text and "수정 기준보다 낮음" in original.text
        assert "https://" in original.text and "공식 근거" in original.text

        add_profile(client, headers, missing_id, profile)
        retry = client.post(f"{path}/retry", headers={**headers, "Idempotency-Key": str(uuid4())})
        assert retry.status_code == 202, retry.text
        retry_id = retry.json()["id"]
        retried = settle(client, headers, engine, retry_id)
        assert retried["status"] == "COMPLETED" and retried["parent_id"] == batch_id, retried
        assert {item["status"] for item in retried["sources"]} >= {"UPDATED", "REUSED"}
        for member in retried["assets"]:
            if member["asset_id"] == missing_id:
                assert member["analysis_id"] and not member["carried"]
            else:
                assert member["carried"]
                assert member["analysis_id"] == members[member["asset_id"]]["analysis_id"]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CollectionRun)) == 3
        assert client.get(f"{path}/markdown", headers=headers).content == original.content
        assert client.get(path, headers=headers).json()["retry_id"] == retry_id
        assert client.get(f"{BATCH}/{retry_id}/markdown", headers=headers).status_code == 200


def test_batch_and_report_require_grants_for_every_asset(client, engine, accounts):
    admin = auth.login(client)
    ids = [register(client, admin, "One"), register(client, admin, "Two")]

    def grant(asset_id, identity):
        result = client.post(
            f"/api/v1/admin/assets/{asset_id}/grants",
            headers=admin,
            json={"user_id": accounts[identity]},
        )
        assert result.status_code == 200, result.text

    grant(ids[0], "operator")
    grant(ids[0], "viewer")
    with TestClient(create_app()) as operator:
        operator_headers = auth.login(operator, "operator")
        assert request_batch(operator, operator_headers, ids).status_code == 404
    result = request_batch(client, admin, ids)
    assert result.status_code == 202, result.text
    batch_id = result.json()["id"]
    batch = settle(client, admin, engine, batch_id)
    assert batch["status"] == "FAILED" and batch["report_summary"]["cve_count"] == 0
    path = f"{BATCH}/{batch_id}"
    with TestClient(create_app()) as viewer:
        viewer_headers = auth.login(viewer, "viewer")
        assert viewer.get(BATCH).json()["items"] == []
        assert viewer.get(BATCH).json()["total"] == 0
        assert viewer.get(path).status_code == 404
        assert viewer.get(f"{path}/markdown").status_code == 404
        assert viewer.get(f"{path}/comparison").status_code == 404
        grant(ids[1], "viewer")
        assert viewer.get(BATCH).json()["total"] == 1
        assert viewer.get(path).status_code == 200
        assert viewer.get(f"{path}/markdown").status_code == 200
        assert viewer.get(f"{path}/comparison").json() == {"cve_id": None, "items": []}
        assert viewer.post(f"{path}/report/retry", headers=viewer_headers).status_code == 403
        assert (
            viewer.post(
                f"{path}/retry", headers={**viewer_headers, "Idempotency-Key": "viewer-retry"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("in_scope", [False, True])
def test_batch_distinguishes_unassessed_assets(
    client, headers, engine, lab, source_wire, in_scope, archive_without_artifacts
):
    server, asset, _, profile = lab
    server.outputs["packages"] = (
        0,
        APACHE if in_scope else "bash\t5.2-1ubuntu1\tbash\t5.2-1ubuntu1\tamd64\tinstalled\tok\n",
    )
    other = register(client, headers, "Second Ubuntu")
    add_profile(client, headers, other, profile)
    requested = request_batch(client, headers, [asset["id"], other])
    assert requested.status_code == 202
    batch_id = requested.json()["id"]
    batch = settle(client, headers, engine, batch_id)
    assert batch["status"] == "COMPLETED"
    assert batch["evaluated_cve_count"] == 0
    expected = "NO_EVIDENCE" if in_scope else "NO_TARGET"
    assert all(
        entry["coverage"] == expected and entry["evaluated_pairs"] == 0 for entry in batch["assets"]
    )
    report = client.get(f"{BATCH}/{batch_id}/markdown", headers=headers)
    assert report.status_code == 200
    assert "평가 결과 있음 0대 · 미평가 2대" in report.text
    assert "영향 확인 결과 없음" in report.text and "영향 확인 CVE 0개" not in report.text


def test_rebuild_report_preserves_finished_batch_inputs(
    client, headers, engine, lab, source_wire, monkeypatch, archive_without_artifacts
):
    _, asset, _, profile = lab
    other = register(client, headers, "Second Ubuntu")
    add_profile(client, headers, other, profile)
    source_wire["ubuntu"]["vulns"][0]["affected"][0]["package"]["ecosystem"] = "Ubuntu:24.04:LTS"

    def fail_report(*_):
        raise RuntimeError("Temporary renderer failure for this test")

    monkeypatch.setattr("backend.workflows.batch.build_batch_report", fail_report)
    created = request_batch(client, headers, [asset["id"], other])
    assert created.status_code == 202
    batch_id = created.json()["id"]
    path = f"{BATCH}/{batch_id}"
    assert client.post(f"{path}/report/retry", headers=headers).status_code == 409
    failed = settle(client, headers, engine, batch_id)
    assert failed["status"] == "COMPLETED" and failed["report_status"] == "FAILED"
    assert failed["evaluated_cve_count"] == 1
    assert client.get(f"{path}/markdown", headers=headers).status_code == 409
    with Session(engine) as db:
        child_count = db.scalar(select(func.count()).select_from(Job))

    monkeypatch.setattr("backend.workflows.batch.build_batch_report", build_batch_report)
    for _ in range(2):
        response = client.post(f"{path}/report/retry", headers=headers)
        assert response.status_code == 202 and response.json()["report_status"] == "QUEUED"
    assert run_once(engine) is False
    ready = client.get(path, headers=headers).json()
    assert ready["report_status"] == "READY" and ready["report_error"] is None
    for pinned in ("assets", "sources", "finished_at", "evaluated_cve_count"):
        assert ready[pinned] == failed[pinned]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Job)) == child_count
    original = client.get(f"{path}/markdown", headers=headers)
    assert original.status_code == 200
    assert client.post(f"{path}/report/retry", headers=headers).json()["report_status"] == "READY"
    assert client.get(f"{path}/markdown", headers=headers).content == original.content
