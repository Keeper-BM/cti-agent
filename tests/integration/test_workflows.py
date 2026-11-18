from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.tables import AssetWorkflow, Job, ReportRun
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.integration import test_assessments as assessments
from tests.integration import test_auth as auth
from tests.integration import test_collections as collections
from tests.integration import test_reports as reports
from tests.integration import test_sources as sources

lab = collections.lab
accounts = auth.accounts
source_wire = sources.source_wire


def start(client, headers, asset_id, body, key="demo"):
    return client.post(
        f"/api/v1/assets/{asset_id}/workflows",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )


def finish(client, headers, engine, asset_id):
    stages = set()
    for _ in range(20):
        run_once(engine)
        state = client.get(f"/api/v1/assets/{asset_id}/workspace", headers=headers)
        assert state.status_code == 200, state.text
        run = state.json()["latest"]
        stages.add(run["stage"])
        if run["status"] != "RUNNING":
            return run, stages
    raise AssertionError("workflow did not reach a terminal state")


def test_registered_ssh_to_report(client, headers, engine, source_wire, lab, monkeypatch):
    server, asset, profile, _ = lab
    # Exercise the verifier job and its partial-evidence path without a live Ubuntu archive.
    from types import SimpleNamespace

    monkeypatch.setattr("backend.verification.queue.gpg_executable", lambda *_: "gpg")
    monkeypatch.setattr(
        "backend.verification.service.ArchiveClient",
        lambda *_: SimpleNamespace(resolve=lambda _inventory: {}, close=lambda: None),
    )
    source_wire["ubuntu"]["vulns"][0]["affected"][0]["package"]["ecosystem"] = "Ubuntu:24.04:LTS"
    aid = asset["id"]
    probe = client.post(f"/api/v1/assets/{aid}/ssh-profile/{profile['id']}/check", headers=headers)
    assert probe.status_code == 200 and probe.json()["verified"]
    assert not server.commands
    assert (
        client.get(f"/api/v1/assets/{aid}/workspace", headers=headers).json()["connection_status"]
        == "verified"
    )
    queued = start(client, headers, aid, {})
    assert queued.status_code == 202, queued.text
    assert start(client, headers, aid, {}).json()["id"] == queued.json()["id"]
    assert start(client, headers, aid, {}, "another").status_code == 409
    run, stages = finish(client, headers, engine, aid)
    assert run["status"] == "COMPLETED", run
    assert stages == {"inventory", "sources", "analysis", "report"}
    assert run["mode"] == "ssh" and run["package_count"] > 0 and run["is_synthetic"] is False
    assert "verification" in run["timeline"]
    assert {s["source"] for s in run["sources"]} >= {"ubuntu", "apache", "kev", "nvd"}
    assert all(s["status"] == "UPDATED" for s in run["sources"]), run
    analysis = client.get(f"/api/v1/analyses/{run['analysis_id']}", headers=headers).json()
    assert {s["id"] for s in analysis["sources"]} == {s["snapshot_id"] for s in run["sources"]}
    assert analysis["inventory_id"] == run["inventory_id"]
    assert client.get(
        f"/api/v1/assets/{aid}/inventories/{run['inventory_id']}", headers=headers
    ).json()["verification_id"]
    report = client.get(f"/api/v1/reports/{run['report_id']}/markdown", headers=headers)
    assert report.status_code == 200 and sources.CVE in report.text
    assert start(client, headers, aid, {}).json()["report_id"] == run["report_id"]
    with Session(engine) as db:
        assert len(list(db.scalars(select(ReportRun.id)))) == 1


def test_saved_input_handles_failed_refresh_and_records_previous_snapshot(
    client, headers, engine, source_wire
):
    inv = assessments.inventory(client, headers)
    aid, body = inv["asset_id"], {"inventory_id": inv["inventory_id"]}
    assert start(client, headers, aid, {}).status_code == 409
    assert start(client, headers, aid, {"inventory_id": str(uuid4())}).status_code == 404
    source_wire["fail"] = "ubuntu"
    assert start(client, headers, aid, body).status_code == 202
    run, _ = finish(client, headers, engine, aid)
    assert run["status"] == "FAILED" and run["stage"] == "sources" and not run["report_id"]
    source_wire["fail"] = None
    snap = sources.execute(client, headers, engine, "ubuntu")
    sources.execute(client, headers, engine, "ubuntu", {"release": "22.04", "package": "mysql-8.0"})
    source_wire["fail"] = "ubuntu"
    assert start(client, headers, aid, body, "retry").status_code == 202
    run, _ = finish(client, headers, engine, aid)
    assert run["status"] == "COMPLETED" and run["mode"] == "saved"
    ubuntu = next(s for s in run["sources"] if s["source"] == "ubuntu")
    assert ubuntu["status"] == "CACHED" and ubuntu["snapshot_id"] == snap
    report = client.get(f"/api/v1/reports/{run['report_id']}/markdown", headers=headers)
    assert "갱신 실패" in report.text


def test_restart_does_not_repeat_interrupted_ssh_job(client, headers, engine, lab):
    _, asset, _, _ = lab
    run = start(client, headers, asset["id"], {}).json()
    with Session(engine) as db, db.begin():
        job = db.scalar(select(Job).where(Job.kind == "SSH_COLLECTION"))
        job.status = "RUNNING"
    recover_interrupted_jobs(engine)
    result, _ = finish(client, headers, engine, asset["id"])
    assert result["id"] == run["id"] and result["status"] == "FAILED"
    with Session(engine) as db:
        assert not db.get(AssetWorkflow, run["id"]).active_slot


def test_roles_and_revocation_apply_to_the_whole_workflow(client, engine, accounts):
    admin = auth.login(client)
    inv = assessments.inventory(client, admin)
    aid = inv["asset_id"]
    target = f"/api/v1/assets/{aid}/workspace"
    for name in ("viewer", "operator"):
        assert (
            client.post(
                f"/api/v1/admin/assets/{aid}/grants",
                headers=admin,
                json={"user_id": accounts[name]},
            ).status_code
            == 200
        )
    viewer = auth.login(client, "viewer")
    assert client.get(target).status_code == 200
    assert start(client, viewer, aid, {"inventory_id": inv["inventory_id"]}).status_code == 403
    operator = auth.login(client, "operator")
    run = start(client, operator, aid, {"inventory_id": inv["inventory_id"]}).json()
    admin = auth.login(client)
    assert (
        client.delete(
            f"/api/v1/admin/assets/{aid}/grants/{accounts['operator']}", headers=admin
        ).status_code
        < 300
    )
    run_once(engine)
    assert client.get(target, headers=admin).json()["latest"]["status"] == "FAILED"
    auth.login(client, "operator")
    assert client.get(target).status_code == 404
    assert client.get(f"/api/v1/assets/{aid}/workflows/{run['id']}").status_code == 404


def test_workspace_pins_run_report_and_hides_old_results_while_running(
    client, headers, engine, source_wire
):
    inv = assessments.inventory(client, headers)
    aid = inv["asset_id"]
    path = f"/api/v1/assets/{aid}/workspace"
    body = {"inventory_id": inv["inventory_id"]}
    start(client, headers, aid, body)
    first, _ = finish(client, headers, engine, aid)
    assert first["status"] == "COMPLETED"
    copy = reports.enqueue(client, headers, {"analysis_id": first["analysis_id"]})
    assert run_once(engine)
    assert copy["id"] != first["report_id"]
    new = start(client, headers, aid, body, "second").json()
    live = client.get(path, headers=headers).json()
    assert live["selection"]["workflow"]["id"] == new["id"]
    assert live["selection"]["analysis"] is None
    historic = client.get(
        path, params={"analysis_id": first["analysis_id"]}, headers=headers
    ).json()
    assert historic["latest"]["id"] == new["id"]
    assert historic["selection"]["workflow"] == first
    assert historic["selection"]["analysis"]["report_id"] == first["report_id"]
    assert historic["selection"]["analysis"]["workflow_id"] == first["id"]
    other = assessments.inventory(client, headers, "other-asset")
    assert (
        client.get(
            f"/api/v1/assets/{other['asset_id']}/workspace",
            params={"analysis_id": first["analysis_id"]},
            headers=headers,
        ).status_code
        == 404
    )


def test_manual_history_can_be_opened_beyond_recent_page(client, headers, engine):
    inv = assessments.inventory(client, headers)
    first = assessments.enqueue(client, headers, inv)
    assert run_once(engine)
    report = reports.enqueue(client, headers, {"analysis_id": first["id"]})
    assert run_once(engine)
    for _ in range(8):
        assessments.enqueue(client, headers, inv)
        assert run_once(engine)
    path = f"/api/v1/assets/{inv['asset_id']}/workspace"
    view = client.get(path, headers=headers, params={"analysis_id": first["id"]}).json()
    assert first["id"] not in [row["id"] for row in view["history"]]
    assert view["selection"]["workflow"] is None
    assert view["selection"]["analysis"]["id"] == first["id"]
    assert view["selection"]["analysis"]["report_id"] == report["id"]
