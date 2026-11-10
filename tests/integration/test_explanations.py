import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.llm.client import SchoolLLM
from backend.llm.context import context_digest
from backend.llm.contracts import SCHOOL_BASE_URL, ExplanationContext
from backend.llm.service import explain_job
from backend.models.tables import AnalysisRun, ExplanationRun, FindingRecord, Job
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.integration import test_sources as source_tests
from tests.integration.test_assessments import enqueue as enqueue_analysis
from tests.integration.test_assessments import inventory, results
from tests.unit.test_llm import valid_output

source_wire = source_tests.source_wire


@pytest.fixture
def llm_wire(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", SCHOOL_BASE_URL)
    monkeypatch.setenv("LLM_MODEL", "Qwen/test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-private-key")
    get_settings.cache_clear()
    state = {"calls": [], "status": 200, "bad_citation": False}

    def respond(request):
        body = json.loads(request.content)
        state["calls"].append(body)
        data = json.loads(body["messages"][1]["content"])
        output = valid_output(data["facts"])
        if state["bad_citation"]:
            output["meaning"]["evidence_ids"] = ["E999"]
        return httpx.Response(
            state["status"],
            json={
                "model": "Qwen/test-model",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
                "usage": {"total_tokens": 70},
            },
        )

    monkeypatch.setattr(
        "backend.llm.service.SchoolLLM",
        lambda settings: SchoolLLM(settings, transport=httpx.MockTransport(respond)),
    )
    return state


@pytest.fixture
def finding(client, headers, engine, source_wire, llm_wire):
    source_tests.execute(client, headers, engine, "ubuntu")
    analysis = enqueue_analysis(client, headers, inventory(client, headers))
    run_once(engine)
    return next(i for i in results(client, headers, analysis)["items"] if i["cve_id"])


def enqueue(client, headers, finding, key=None):
    response = client.post(
        "/api/v1/explanations",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"finding_id": finding["finding_id"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_generation_history_restart_inputs_and_secrets(client, headers, engine, finding, llm_wire):
    queued = enqueue(client, headers, finding, "explanation-one")
    assert queued["job"]["status"] == "QUEUED" and queued["result"] is None
    assert llm_wire["calls"] == []
    assert enqueue(client, headers, finding, "explanation-one")["id"] == queued["id"]
    duplicate = client.post(
        "/api/v1/explanations",
        headers={**headers, "Idempotency-Key": "another-key"},
        json={"finding_id": finding["finding_id"]},
    )
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "LLM_BUSY"
    with Session(engine) as db:
        run = db.get(ExplanationRun, queued["id"])
        ctx = ExplanationContext.model_validate(run.input_payload)
        assert context_digest(ctx) == run.context_sha256
        assert "test-llm-private-key" not in json.dumps(run.input_payload)
        assert {str(c.snapshot_id) for c in ctx.citations if c.snapshot_id} <= set(
            db.get(AnalysisRun, finding["analysis_id"]).source_snapshot_ids
        )
    original = client.get(f"/api/v1/findings/{finding['finding_id']}", headers=headers).json()
    run_once(engine)
    detail = client.get(f"/api/v1/explanations/{queued['id']}", headers=headers).json()
    assert detail["job"]["status"] == "SUCCEEDED"
    assert detail["result"]["facts"]["verdict"] == "NEEDS_REVIEW"
    assert detail["completed_at"].endswith("Z") and detail["usage"] == {"total_tokens": 70}
    assert "test-llm-private-key" not in json.dumps(detail)
    assert "input_payload" not in detail
    assert (
        client.get(f"/api/v1/findings/{finding['finding_id']}", headers=headers).json() == original
    )
    with TestClient(create_app()) as fresh:
        assert fresh.get(f"/api/v1/explanations/{queued['id']}", headers=headers).json() == detail
        assert (
            fresh.get(
                f"/api/v1/explanations?finding_id={finding['finding_id']}", headers=headers
            ).json()["total"]
            == 1
        )
    assert len(llm_wire["calls"]) == 1


@pytest.mark.parametrize("failure", ["bad_citation", "rate_limit"])
def test_failures_never_publish_invalid_text_or_replace_old_explanations(
    client, headers, engine, finding, llm_wire, failure
):
    first = enqueue(client, headers, finding)
    run_once(engine)
    saved = client.get(f"/api/v1/explanations/{first['id']}", headers=headers).json()
    if failure == "bad_citation":
        llm_wire["bad_citation"] = True
    else:
        llm_wire["status"] = 429
    second = enqueue(client, headers, finding)
    run_once(engine)
    failed = client.get(f"/api/v1/explanations/{second['id']}", headers=headers).json()
    assert failed["job"]["status"] == "FAILED" and failed["result"] is None
    with Session(engine) as db:
        assert db.get(ExplanationRun, second["id"]).active_slot is None
    assert failed["job"]["error_code"] == (
        "LLM_CITATION_INVALID" if failure == "bad_citation" else "LLM_RATE_LIMIT"
    )
    assert client.get(f"/api/v1/explanations/{first['id']}", headers=headers).json() == saved
    listing = client.get(
        f"/api/v1/explanations?finding_id={finding['finding_id']}&limit=1&offset=1", headers=headers
    ).json()
    assert listing["total"] == 2 and listing["items"][0]["id"] == first["id"]


def test_auth_missing_configuration_invalid_scope_and_keys(
    client, headers, engine, finding, llm_wire, monkeypatch
):
    assert client.get("/api/v1/explanations/status").status_code == 401
    assert (
        client.post("/api/v1/explanations", json={"finding_id": finding["finding_id"]}).status_code
        == 401
    )
    assert client.get("/api/v1/explanations/status", headers=headers).json()["configured"]
    first = enqueue(client, headers, finding, "unique-key")
    collision = client.post(
        "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "unique-key"}
    )
    assert collision.status_code == 409
    run_once(engine)
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    assert not client.get("/api/v1/explanations/status", headers=headers).json()["configured"]
    assert enqueue(client, headers, finding, "unique-key")["id"] == first["id"]
    response = client.post(
        "/api/v1/explanations",
        headers={**headers, "Idempotency-Key": "missing-key"},
        json={"finding_id": finding["finding_id"]},
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/explanations/{uuid4()}", headers=headers).status_code == 404
    assert len(llm_wire["calls"]) == 1


def test_non_cve_and_inactive_assets_do_not_enqueue(client, headers, engine, finding, llm_wire):
    with Session(engine) as db:
        other = db.scalar(select(FindingRecord).where(FindingRecord.cve_id.is_(None)))
        other_id = other.id
    bad = client.post(
        "/api/v1/explanations",
        headers={**headers, "Idempotency-Key": "not-cve"},
        json={"finding_id": other_id},
    )
    assert bad.status_code == 409
    client.patch(
        f"/api/v1/assets/{finding['asset_id']}", headers=headers, json={"is_active": False}
    )
    inactive = client.post(
        "/api/v1/explanations",
        headers={**headers, "Idempotency-Key": "inactive"},
        json={"finding_id": finding["finding_id"]},
    )
    assert inactive.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ExplanationRun)) == 0
    assert llm_wire["calls"] == []


def test_changed_config_fails_without_request_and_committed_job_survives_restart(
    client, headers, engine, finding, llm_wire, monkeypatch
):
    queued = enqueue(client, headers, finding)
    monkeypatch.setenv("LLM_MODEL", "Qwen/changed")
    get_settings.cache_clear()
    run_once(engine)
    failed = client.get(f"/api/v1/explanations/{queued['id']}", headers=headers).json()
    assert failed["job"]["error_code"] == "LLM_CONFIG_CHANGED" and not llm_wire["calls"]
    monkeypatch.setenv("LLM_MODEL", "Qwen/test-model")
    get_settings.cache_clear()
    new = enqueue(client, headers, finding)
    with Session(engine) as db, db.begin():
        db.get(Job, new["job"]["id"]).status = "RUNNING"
    explain_job(engine, new["job"]["id"])
    recover_interrupted_jobs(engine)
    assert (
        client.get(f"/api/v1/explanations/{new['id']}", headers=headers).json()["job"]["status"]
        == "SUCCEEDED"
    )


def test_interrupted_call_releases_slot_without_automatic_retry(
    client, headers, engine, finding, llm_wire
):
    queued = enqueue(client, headers, finding)
    with Session(engine) as db, db.begin():
        db.get(Job, queued["job"]["id"]).status = "RUNNING"
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert db.get(ExplanationRun, queued["id"]).active_slot is None
        assert db.get(Job, queued["job"]["id"]).error_code == "WORKER_RESTARTED"
    assert not llm_wire["calls"]
    assert enqueue(client, headers, finding)["id"] != queued["id"]
