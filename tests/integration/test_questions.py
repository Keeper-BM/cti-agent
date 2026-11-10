import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.core.config import get_settings
from backend.llm.client import SchoolLLM
from backend.llm.contracts import SCHOOL_BASE_URL
from backend.models.tables import AnalysisRun, Job, QuestionRun, TextChunk
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.integration import test_assessments as assessments
from tests.integration import test_auth as auth_tests
from tests.integration import test_sources as sources

source_wire = sources.source_wire
accounts = auth_tests.accounts


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", SCHOOL_BASE_URL)
    monkeypatch.setenv("LLM_MODEL", "Qwen/test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-only-question-key")
    get_settings.cache_clear()
    state = {"calls": [], "status": 200, "bad": False, "version_first": False}

    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body["messages"][1]["content"])
        state["calls"].append(context)
        output = {
            "facts_digest": context["facts_digest"],
            "insufficient_evidence": False,
            "answer": [
                {
                    "text": (
                        "저장된 분석에는 추가 확인 항목이 있습니다. "
                        "공식 자료와 설치 파일의 출처를 함께 확인하세요."
                    ),
                    "evidence_ids": ["A1", "E999" if state["bad"] else "E1"],
                }
            ],
        }
        if state["version_first"] and len(state["calls"]) == 1:
            output["answer"][0]["text"] = "Ubuntu 24.04의 저장된 분석과 공식 자료를 확인하세요."
        return httpx.Response(
            state["status"],
            json={
                "model": "Qwen/test-model",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
                "usage": {"total_tokens": 60},
            },
        )

    monkeypatch.setattr(
        "backend.retrieval.service.SchoolLLM",
        lambda settings: SchoolLLM(settings, transport=httpx.MockTransport(respond)),
    )
    return state


def analysis(client, headers, engine, name="question asset"):
    value = assessments.enqueue(client, headers, assessments.inventory(client, headers, name=name))
    run_once(engine)
    return value


def ask(client, headers, ids, question="이 분석의 취약점과 수정 근거를 설명해줘", key=None):
    return client.post(
        "/api/v1/questions",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"analysis_ids": ids, "question": question},
    )


def test_retrieval_pinned_facts_chunks_restart_and_invalid_answers(
    client, headers, engine, source_wire, wire
):
    sources.execute(client, headers, engine, "ubuntu")
    baseline = analysis(client, headers, engine)
    response = ask(client, headers, [baseline["id"]], key="question-one")
    assert response.status_code == 202, response.text
    first = response.json()
    assert ask(client, headers, [baseline["id"]], key="question-one").json()["id"] == first["id"]
    assert ask(client, headers, [baseline["id"]]).status_code == 409
    with Session(engine) as db:
        frozen = db.get(QuestionRun, first["id"]).input_payload
        assert not frozen["insufficient_evidence"] and frozen["facts"]
        snapshot_ids = set(db.get(AnalysisRun, baseline["id"]).source_snapshot_ids)
        for citation in frozen["citations"]:
            if citation["id"].startswith("E"):
                assert citation["snapshot_id"] in snapshot_ids
                chunk = db.get(TextChunk, citation["chunk_id"])
                assert chunk.text == citation["excerpt"]
                assert chunk.end_offset - chunk.start_offset == len(chunk.text)
    run_once(engine)
    saved = client.get("/api/v1/questions/" + first["id"], headers=headers).json()
    assert saved["job"]["status"] == "SUCCEEDED", saved
    assert saved["result"]["status"] == "ANSWERED" and saved["result"]["facts"] == frozen["facts"]
    assert "input_payload" not in saved and "test-only-question-key" not in json.dumps(saved)
    assert "asset_ids" not in wire["calls"][0]
    wire["bad"] = True
    second = ask(client, headers, [baseline["id"]]).json()
    run_once(engine)
    failed = client.get("/api/v1/questions/" + second["id"], headers=headers).json()
    assert failed["job"]["error_code"] == "QUESTION_CITATION_INVALID" and failed["result"] is None
    wire["bad"] = False
    wire["status"] = 429
    third = ask(client, headers, [baseline["id"]]).json()
    run_once(engine)
    assert (
        client.get("/api/v1/questions/" + third["id"], headers=headers).json()["job"]["error_code"]
        == "LLM_RATE_LIMIT"
    )
    with TestClient(create_app()) as fresh:
        assert fresh.get("/api/v1/questions/" + first["id"], headers=headers).json() == saved
        assert fresh.get("/api/v1/questions?limit=1&offset=1", headers=headers).json()["total"] == 3


def test_no_evidence_needs_no_key_and_recovery_frees_slot(client, headers, engine, source_wire):
    sources.execute(client, headers, engine, "ubuntu")
    baseline = analysis(client, headers, engine)
    first = ask(
        client, headers, [baseline["id"]], question="CVE-2099-999999에 대한 근거는 있나요?"
    ).json()
    run_once(engine)
    saved = client.get("/api/v1/questions/" + first["id"], headers=headers).json()
    assert saved["job"]["status"] == "SUCCEEDED"
    assert saved["result"]["status"] == "INSUFFICIENT_EVIDENCE" and not saved["result"]["facts"]
    next_run = ask(
        client, headers, [baseline["id"]], question="CVE-2099-999999 설명해 주세요"
    ).json()
    with Session(engine) as db, db.begin():
        db.get(Job, next_run["job"]["id"]).status = "RUNNING"
    recover_interrupted_jobs(engine)
    with Session(engine) as db:
        assert db.get(QuestionRun, next_run["id"]).active_slot is None
    assert (
        ask(client, headers, [baseline["id"]], question="CVE-2099-999999 설명해 주세요").status_code
        == 202
    )


def test_multi_asset_questions_require_every_grant_including_execution(
    client, headers, engine, source_wire, wire, monkeypatch
):
    sources.execute(client, headers, engine, "ubuntu")
    left = analysis(client, headers, engine, "left")
    right = analysis(client, headers, engine, "right")
    # Build accounts after creating isolated token-mode fixtures.
    from backend.auth.passwords import hash_password
    from backend.models.tables import AssetGrant, User

    with Session(engine) as db, db.begin():
        user = User(
            username="operator",
            display_name="operator",
            role="OPERATOR",
            password_hash=hash_password(auth_tests.PASSWORD),
        )
        db.add(user)
        db.flush()
        uid = user.id
        for item in [left, right]:
            db.add(AssetGrant(user_id=uid, asset_id=item["asset_id"]))
    monkeypatch.setenv("AUTH_MODE", "accounts")
    get_settings.cache_clear()
    h = auth_tests.login(client, "operator")
    created = ask(client, h, [left["id"], right["id"]])
    assert created.status_code == 202, created.text
    run = created.json()
    assert client.get("/api/v1/questions").json()["total"] == 1
    with Session(engine) as db, db.begin():
        # Revoke the second scope, leaving the job's primary asset accessible.
        primary = db.get(QuestionRun, run["id"]).asset_id
        removed = next(a["asset_id"] for a in [left, right] if a["asset_id"] != primary)
        db.delete(db.get(AssetGrant, (uid, removed)))
    assert client.get("/api/v1/questions").json()["total"] == 0
    assert client.get("/api/v1/questions/" + run["id"]).status_code == 404
    assert client.get("/api/v1/jobs/" + run["job"]["id"]).status_code == 404
    assert all(j["id"] != run["job"]["id"] for j in client.get("/api/v1/jobs").json()["items"])
    assert ask(client, h, [left["id"], right["id"]]).status_code == 404
    run_once(engine)
    assert not wire["calls"]
    with Session(engine) as db:
        assert db.get(Job, run["job"]["id"]).error_code == "JOB_ACCESS_REVOKED"


def test_rejected_version_prose_is_repaired_once_without_weakening_validation(
    client, headers, engine, source_wire, wire
):
    sources.execute(client, headers, engine, "ubuntu")
    baseline = analysis(client, headers, engine)
    wire["version_first"] = True
    queued = ask(client, headers, [baseline["id"]]).json()
    run_once(engine)
    saved = client.get("/api/v1/questions/" + queued["id"], headers=headers).json()
    assert saved["job"]["status"] == "SUCCEEDED"
    assert len(wire["calls"]) == 2
    assert saved["usage"]["generation_attempts"] == 2
    assert saved["usage"]["total_tokens"] == 120
    assert all("24.04" not in part["text"] for part in saved["result"]["answer"])


def test_question_keeps_affected_binary_as_cve_representative(
    client, headers, engine, source_wire, wire
):
    from sqlalchemy import select

    from backend.assessment.contracts import AssessmentFinding
    from backend.models.tables import FindingRecord, QuestionRun

    sources.execute(client, headers, engine, "ubuntu")
    baseline = analysis(client, headers, engine)
    with Session(engine) as db, db.begin():
        row = db.scalar(
            select(FindingRecord).where(
                FindingRecord.analysis_id == baseline["id"], FindingRecord.cve_id.is_not(None)
            )
        )
        data = {
            **row.payload,
            "finding_id": str(uuid4()),
            "package_name": "apache2-bin",
            "verdict": "AFFECTED",
            "version_comparison": "BELOW_FIX",
            "installed_version": "2.4.52-1ubuntu4.3",
            "origin_status": "VERIFIED_LAB",
            "reasons": ["Synthetic confirmed condition for retrieval selection test"],
        }
        finding = AssessmentFinding.model_validate(data)
        db.add(
            FindingRecord(
                id=str(finding.finding_id),
                analysis_id=baseline["id"],
                asset_id=row.asset_id,
                package_name=finding.package_name,
                cve_id=finding.cve_id,
                processing_status=finding.processing_status,
                verdict=finding.verdict,
                payload=finding.model_dump(mode="json"),
            )
        )
    queued = ask(client, headers, [baseline["id"]]).json()
    with Session(engine) as db:
        facts = db.get(QuestionRun, queued["id"]).input_payload["facts"]
        assert len(facts) == 1 and facts[0]["package_name"] == "apache2-bin"
        assert facts[0]["verdict"] == "AFFECTED"
