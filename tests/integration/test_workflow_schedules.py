from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.models.tables import FindingRecord
from backend.worker.runner import run_once
from backend.workflows.schedules import advance_schedules, next_occurrence
from tests.integration import test_auth as auth
from tests.integration import test_workflow_batches as batches

lab = batches.lab
source_wire = batches.source_wire
archive_without_artifacts = batches.archive_without_artifacts
accounts = auth.accounts

SCHEDULES = "/api/v1/workflow-schedules"
BATCHES = "/api/v1/workflow-batches"
NOW = datetime(2026, 11, 25, tzinfo=UTC)  # Wednesday, 09:00 KST


def configuration(ids, **options):
    return {
        "name": "운영 점검",
        "asset_ids": ids,
        "frequency": "DAILY",
        "local_time": "09:05",
    } | options


def create(client, headers, ids, **options):
    result = client.post(SCHEDULES, headers=headers, json=configuration(ids, **options))
    assert result.status_code == 201, result.text
    return result.json()


def runs(client, headers, schedule_id):
    result = client.get(f"{SCHEDULES}/{schedule_id}/runs", headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def changes(client, headers, schedule_id, run, **params):
    result = client.get(
        f"{SCHEDULES}/{schedule_id}/runs/{run['id']}/changes", headers=headers, params=params
    )
    assert result.status_code == 200, result.text
    return result.json()


def change_fixture_finding(db, finding, verdict):
    finding.verdict = verdict
    finding.payload = {**finding.payload, "verdict": verdict}
    db.add(finding)


@pytest.mark.parametrize(
    ("time", "weekday", "expected"),
    [
        ("09:05", None, NOW + timedelta(minutes=5)),
        ("09:00", None, NOW + timedelta(days=1)),
        ("09:00", 2, NOW + timedelta(days=7)),
        ("09:30", 2, NOW + timedelta(minutes=30)),
        ("00:00", 3, NOW + timedelta(hours=15)),
    ],
)
def test_occurrence_uses_kst_and_a_strict_future_slot(time, weekday, expected):
    assert next_occurrence(time, weekday, NOW) == expected


def test_create_edit_pause_and_catch_up_once(client, headers, engine, lab, monkeypatch):
    _, asset, _, profile = lab
    monkeypatch.setattr("backend.api.routes.workflow_schedules.utcnow", lambda: NOW)
    missing = batches.register(client, headers, "No SSH setup")
    other = batches.register(client, headers, "Second server")
    batches.add_profile(client, headers, other, profile)
    first = asset["id"]
    for payload, status in (
        (configuration([missing]), 409),
        (configuration([first, first]), 422),
        (configuration([first], frequency="WEEKLY"), 422),
        (configuration([first], weekday=0), 422),
        (configuration([first], local_time="24:05"), 422),
    ):
        assert client.post(SCHEDULES, headers=headers, json=payload).status_code == status
    schedule = create(client, headers, [first])
    schedule_id = schedule["id"]
    path = f"{SCHEDULES}/{schedule_id}"
    created_for = datetime.fromisoformat(schedule["next_run_at"])
    assert created_for == NOW + timedelta(minutes=5)
    advance_schedules(engine, created_for - timedelta(seconds=1))
    assert runs(client, headers, schedule_id) == {"items": [], "total": 0}

    assert (
        client.patch(path, headers=headers, json={"enabled": False}).json()["next_run_at"] is None
    )
    advance_schedules(engine, created_for + timedelta(days=3))
    assert runs(client, headers, schedule_id)["total"] == 0
    edited = client.put(path, headers=headers, json=configuration([first, other]))
    assert edited.status_code == 200, edited.text
    assert edited.json()["next_run_at"] is None
    assert {row["id"] for row in edited.json()["assets"]} == {first, other}
    assert client.patch(path, headers=headers, json={"enabled": True}).json()["next_run_at"]
    advance_schedules(engine, created_for + timedelta(days=3, minutes=1))
    advance_schedules(engine, created_for + timedelta(days=3, minutes=1))
    history = runs(client, headers, schedule_id)
    assert history["total"] == 1
    run = history["items"][0]
    assert run["status"] == "RUNNING" and run["batch_id"]
    assert datetime.fromisoformat(run["scheduled_for"]) == created_for + timedelta(days=3)
    assert client.get(f"{BATCHES}/{run['batch_id']}", headers=headers).json()["assets"]
    next_run_at = client.get(path, headers=headers).json()["next_run_at"]
    assert datetime.fromisoformat(next_run_at) == created_for + timedelta(days=4)
    advance_schedules(engine, created_for + timedelta(days=4))
    assert runs(client, headers, schedule_id)["items"][0]["status"] == "SKIPPED"


def test_scheduled_worker_compares_to_last_fresh_result(
    client, headers, engine, lab, source_wire, archive_without_artifacts, monkeypatch
):
    server, asset, _, _ = lab
    scoped = source_wire["ubuntu"]["vulns"][0]["affected"][0]
    scoped["package"]["ecosystem"] = "Ubuntu:24.04:LTS"
    scoped["ranges"][0]["events"][-1]["fixed"] = "2.4.58-1ubuntu8.2"
    scoped["versions"] = ["2.4.58-1ubuntu8.1"]
    monkeypatch.setattr("backend.api.routes.workflow_schedules.utcnow", lambda: NOW)
    schedule = create(client, headers, [asset["id"]])
    schedule_id = schedule["id"]
    due = datetime.fromisoformat(schedule["next_run_at"])

    def finish_occurrence(due_at):
        monkeypatch.setattr("backend.workflows.schedules.utcnow", lambda: due_at)
        assert run_once(engine)
        queued = runs(client, headers, schedule_id)["items"][0]
        assert queued["status"] == "RUNNING"
        batch = batches.settle(client, headers, engine, queued["batch_id"])
        assert batch["status"] == "COMPLETED", batch
        return runs(client, headers, schedule_id)["items"][0], batch["assets"][0]["analysis_id"]

    baseline, before_id = finish_occurrence(due)
    assert changes(client, headers, schedule_id, baseline)["assets"][0]["status"] == "BASELINE"
    # Seed persisted verdicts for the comparison test. The protocol fixture runs no commands.
    with Session(engine) as db, db.begin():
        row = db.scalar(
            select(FindingRecord).where(
                FindingRecord.analysis_id == before_id,
                FindingRecord.cve_id == batches.workflows.sources.CVE,
            )
        )
        change_fixture_finding(db, row, "AFFECTED")
        for cve_id in ("CVE-2099-11001",):
            db.add(
                FindingRecord(
                    id=str(uuid4()),
                    analysis_id=before_id,
                    asset_id=asset["id"],
                    package_name=row.package_name,
                    cve_id=cve_id,
                    processing_status="EVALUATED",
                    verdict="AFFECTED",
                    payload={**row.payload, "cve_id": cve_id},
                )
            )

    source_wire["fail"] = "ubuntu"
    cached, _ = finish_occurrence(due + timedelta(days=1))
    cached_comparison = changes(client, headers, schedule_id, cached)
    assert cached_comparison["assets"][0]["status"] == "UNAVAILABLE"
    assert cached_comparison["total"] == 0
    source_wire["fail"] = None
    current, current_id = finish_occurrence(due + timedelta(days=2))
    with Session(engine) as db, db.begin():
        row = db.scalar(
            select(FindingRecord).where(
                FindingRecord.analysis_id == current_id,
                FindingRecord.cve_id == batches.workflows.sources.CVE,
            )
        )
        change_fixture_finding(db, row, "FIXED")
        db.add(
            FindingRecord(
                id=str(uuid4()),
                analysis_id=current_id,
                asset_id=asset["id"],
                package_name=row.package_name,
                cve_id="CVE-2099-11002",
                processing_status="EVALUATED",
                verdict="AFFECTED",
                payload={**row.payload, "cve_id": "CVE-2099-11002", "verdict": "AFFECTED"},
            )
        )
    result = changes(client, headers, schedule_id, current)
    assert result["assets"][0]["previous_analysis_id"] == before_id
    assert result["counts"] == {"NEW_AFFECTED": 1, "FIXED": 1, "RECHECK": 1}
    assert [row["kind"] for row in result["items"]] == ["NEW_AFFECTED", "FIXED", "RECHECK"]
    assert result["items"][-1]["verdict"] is None and result["items"][-1]["finding_id"] is None
    assert changes(client, headers, schedule_id, current, kind="FIXED")["total"] == 1
    assert (
        changes(client, headers, schedule_id, current, limit=1, offset=1)["items"][0]["kind"]
        == "FIXED"
    )
    assert server.auth_calls >= 3
    report = client.get(f"{BATCHES}/{current['batch_id']}/markdown", headers=headers)
    assert report.status_code == 200


def test_worker_rechecks_owner_grants_and_hides_ungranted_history(
    client, headers, engine, lab, accounts, monkeypatch
):
    _, asset, _, _ = lab
    aid = asset["id"]
    operator_id = accounts["operator"]
    admin = auth.login(client)
    path = f"/api/v1/admin/assets/{aid}/grants"
    assert client.post(path, headers=admin, json={"user_id": operator_id}).status_code == 200
    monkeypatch.setattr("backend.api.routes.workflow_schedules.utcnow", lambda: NOW)
    with TestClient(create_app()) as operator:
        token = auth.login(operator, "operator")
        result = create(operator, token, [aid])
        schedule_id = result["id"]
        due = datetime.fromisoformat(result["next_run_at"])
        advance_schedules(engine, due)
        history = runs(operator, token, schedule_id)
        assert history["total"] == 1 and history["items"][0]["status"] == "RUNNING"
        old_run_id = history["items"][0]["id"]
        assert client.delete(f"{path}/{operator_id}", headers=admin).status_code < 300
        run_once(engine)
        run_once(engine)
        assert runs(operator, token, schedule_id) == {"items": [], "total": 0}
        assert (
            operator.get(f"{SCHEDULES}/{schedule_id}/runs/{old_run_id}/changes").status_code == 404
        )
        advance_schedules(engine, due + timedelta(days=1))
        history = runs(operator, token, schedule_id)
        assert history["total"] == 1
        skipped = history["items"][0]
        assert skipped["status"] == "SKIPPED" and "권한" in skipped["error"]
        mine = operator.get(f"{SCHEDULES}/{schedule_id}").json()
        assert mine["assets"] == [] and mine["inaccessible_asset_count"] == 1
        assert (
            operator.patch(
                f"{SCHEDULES}/{schedule_id}", headers=token, json={"enabled": False}
            ).status_code
            == 200
        )
    with TestClient(create_app()) as viewer:
        token = auth.login(viewer, "viewer")
        assert viewer.get(f"{SCHEDULES}/{schedule_id}").status_code == 404
        assert viewer.post(SCHEDULES, headers=token, json=configuration([aid])).status_code == 403
