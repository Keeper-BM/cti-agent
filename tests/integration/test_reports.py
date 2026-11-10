import copy
import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.llm.service import explain_job
from backend.models.tables import AnalysisRun, FindingRecord, Job, ReportRun
from backend.reports.contracts import ReportContent
from backend.reports.markdown import render_markdown
from backend.reports.service import report_job
from backend.worker.runner import recover_interrupted_jobs, run_once
from tests.integration import test_explanations as explanation_tests
from tests.integration import test_sources as source_tests

source_wire = source_tests.source_wire
llm_wire = explanation_tests.llm_wire
report_finding = explanation_tests.finding


def enqueue(client, headers, finding, include=False, key=None):
    response = client.post(
        "/api/v1/reports",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"analysis_id": finding["analysis_id"], "include_ai_explanations": include},
    )
    assert response.status_code == 202, response.text
    return response.json()


def detail(client, headers, report):
    response = client.get(f"/api/v1/reports/{report['id']}", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_report_preview_download_counts_and_persistence(
    client, headers, engine, report_finding, llm_wire
):
    report = enqueue(client, headers, report_finding)
    assert report["job"]["status"] == "QUEUED" and report["explanation_count"] == 0
    assert (
        client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers).status_code == 409
    )
    run_once(engine)
    saved = detail(client, headers, report)
    assert saved["job"]["status"] == "SUCCEEDED"
    content = ReportContent.model_validate(saved["content"])
    assert content.is_synthetic and not content.package_list_complete
    assert content.summary.package_count == 2 and content.summary.finding_count == 2
    assert content.summary.cve_count == 1
    assert content.summary.verdict_counts["NEEDS_REVIEW"] == 1
    assert content.summary.verdict_counts["AFFECTED"] == 0
    assert content.summary.comparison_counts["MEETS_FIX"] == 1
    assert content.summary.processing_counts["NO_MATCHING_RECORD"] == 1
    assert content.explanations == [] and not llm_wire["calls"]
    exported = client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers)
    assert exported.status_code == 200
    assert exported.text == render_markdown(content)
    assert hashlib.sha256(exported.content).hexdigest() == saved["markdown_sha256"]
    assert exported.headers["x-content-sha256"] == saved["markdown_sha256"]
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in exported.headers["content-disposition"]
    assert exported.headers["x-content-type-options"] == "nosniff"
    assert "가상 입력 보고서" in exported.text and "추가 확인 필요" in exported.text
    with TestClient(create_app()) as fresh:
        assert detail(fresh, headers, report) == saved
        listing = fresh.get(
            f"/api/v1/reports?asset_id={report_finding['asset_id']}", headers=headers
        ).json()
        assert listing["total"] == 1 and "content" not in listing["items"][0]
    assert "input_payload" not in saved and "markdown" not in saved


def test_ai_selection_and_all_facts_are_frozen_before_worker(
    client, headers, engine, report_finding, llm_wire
):
    first_ai = explanation_tests.enqueue(client, headers, report_finding)
    run_once(engine)
    report = enqueue(client, headers, report_finding, include=True)
    assert report["explanation_count"] == 1
    # Generate a newer explanation while the report is queued; it must not replace the pinned one.
    newer_ai = explanation_tests.enqueue(client, headers, report_finding)
    with Session(engine) as db, db.begin():
        db.get(Job, newer_ai["job"]["id"]).status = "RUNNING"
    explain_job(engine, newer_ai["job"]["id"])
    with Session(engine) as db, db.begin():
        analysis = db.get(AnalysisRun, report_finding["analysis_id"])
        analysis.asset_name = "CHANGED AFTER REQUEST"
        row = db.get(FindingRecord, report_finding["finding_id"])
        data = copy.deepcopy(row.payload)
        data["reasons"] = ["CHANGED AFTER REQUEST"]
        row.payload = data
    run_once(engine)
    saved = detail(client, headers, report)
    assert saved["content"]["asset_name"] != "CHANGED AFTER REQUEST"
    assert saved["content"]["explanations"][0]["id"] == first_ai["id"]
    assert all("CHANGED AFTER REQUEST" not in f["reasons"] for f in saved["content"]["findings"])
    assert len(llm_wire["calls"]) == 2
    raw = client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers).text
    assert "AI 생성" in raw and "인용:" in raw and "Qwen/test" in raw
    assert "test-llm-private-key" not in raw
    assert first_ai["id"].replace("-", "\\-") in raw


def test_no_successful_ai_never_invents_explanation(
    client, headers, engine, report_finding, llm_wire
):
    llm_wire["bad_citation"] = True
    explanation_tests.enqueue(client, headers, report_finding)
    run_once(engine)
    report = enqueue(client, headers, report_finding, include=True)
    run_once(engine)
    saved = detail(client, headers, report)
    assert saved["content"]["explanations"] == [] and saved["explanation_count"] == 0
    assert len(llm_wire["calls"]) == 1
    assert (
        "생성 완료된 AI Summary가 없습니다"
        in client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers).text
    )


def test_auth_idempotency_invalid_requests_and_filters(client, headers, engine, report_finding):
    assert client.get("/api/v1/reports").status_code == 401
    assert (
        client.post(
            "/api/v1/reports", json={"analysis_id": report_finding["analysis_id"]}
        ).status_code
        == 401
    )
    first = enqueue(client, headers, report_finding, key="report-key")
    assert enqueue(client, headers, report_finding, key="report-key")["id"] == first["id"]
    collision = client.post(
        "/api/v1/reports",
        headers={**headers, "Idempotency-Key": "report-key"},
        json={"analysis_id": report_finding["analysis_id"], "include_ai_explanations": True},
    )
    assert collision.status_code == 409
    assert (
        client.post(
            "/api/v1/jobs/system-checks", headers={**headers, "Idempotency-Key": "report-key"}
        ).status_code
        == 409
    )
    for body in [
        {"analysis_ids": [report_finding["analysis_id"]]},
        {"analysis_id": report_finding["analysis_id"], "include_ai_explanations": "false"},
        {"analysis_id": report_finding["analysis_id"], "content": "invented"},
    ]:
        assert (
            client.post(
                "/api/v1/reports", headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
            ).status_code
            == 422
        )
    for path in [f"/reports/{uuid4()}", f"/reports/{uuid4()}/markdown"]:
        assert client.get("/api/v1" + path, headers=headers).status_code == 404
    assert client.get(f"/api/v1/reports?asset_id={uuid4()}", headers=headers).json()["total"] == 0
    run_once(engine)
    client.patch(
        f"/api/v1/assets/{report_finding['asset_id']}", headers=headers, json={"is_active": False}
    )
    # Inactive assets retain historical exports, including new reports of old analyses.
    second = enqueue(client, headers, report_finding)
    run_once(engine)
    page = client.get("/api/v1/reports?limit=1&offset=1", headers=headers).json()
    assert page["total"] == 2 and page["items"][0]["id"] == first["id"]
    assert detail(client, headers, second)["job"]["status"] == "SUCCEEDED"


def test_incomplete_analysis_is_rejected_without_new_job(client, headers, engine, report_finding):
    with Session(engine) as db, db.begin():
        analysis = db.get(AnalysisRun, report_finding["analysis_id"])
        analysis.completed_at = None
        before = db.scalar(select(func.count()).select_from(Job))
    response = client.post(
        "/api/v1/reports",
        headers={**headers, "Idempotency-Key": "incomplete"},
        json={"analysis_id": report_finding["analysis_id"]},
    )
    assert response.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Job)) == before


def test_report_failure_is_atomic_and_previous_output_survives(
    client, headers, engine, report_finding, monkeypatch
):
    first = enqueue(client, headers, report_finding)
    run_once(engine)
    saved = detail(client, headers, first)
    second = enqueue(client, headers, report_finding)
    monkeypatch.setattr("backend.reports.service.MAX_REPORT_BYTES", 1)
    run_once(engine)
    failed = detail(client, headers, second)
    assert failed["job"]["error_code"] == "REPORT_SIZE_LIMIT" and failed["content"] is None
    assert failed["completed_at"] is None
    assert (
        client.get(f"/api/v1/reports/{second['id']}/markdown", headers=headers).status_code == 409
    )
    assert detail(client, headers, first) == saved


def test_committed_report_survives_restart_and_pending_integrity_is_checked(
    client, headers, engine, report_finding
):
    first = enqueue(client, headers, report_finding)
    with Session(engine) as db, db.begin():
        db.get(Job, first["job"]["id"]).status = "RUNNING"
    report_job(engine, first["job"]["id"])
    recover_interrupted_jobs(engine)
    assert detail(client, headers, first)["job"]["status"] == "SUCCEEDED"
    second = enqueue(client, headers, report_finding)
    with Session(engine) as db, db.begin():
        run = db.get(ReportRun, second["id"])
        run.input_sha256 = "0" * 64
    run_once(engine)
    assert detail(client, headers, second)["job"]["error_code"] == "REPORT_INPUT_CHANGED"


def test_markdown_escapes_untrusted_asset_and_prose(client, headers, engine, report_finding):
    with Session(engine) as db, db.begin():
        analysis = db.get(AnalysisRun, report_finding["analysis_id"])
        analysis.asset_name = "<img src=x onerror=alert(1)> | [click](javascript:alert(1))"
        row = db.get(FindingRecord, report_finding["finding_id"])
        data = copy.deepcopy(row.payload)
        data["reasons"] = ["first\n# forged heading\n![remote](https://evil.invalid/x)"]
        row.payload = data
    report = enqueue(client, headers, report_finding)
    run_once(engine)
    raw = client.get(f"/api/v1/reports/{report['id']}/markdown", headers=headers).text
    assert "<img" not in raw and "&lt;img" in raw
    assert "\n# forged heading" not in raw and "\\# forged heading" in raw
    assert "![remote]" not in raw and "\\!\\[remote\\]" in raw


def test_summary_counts_packages_separately_from_unique_cves(
    client, headers, engine, report_finding
):
    from tests.integration.test_assessments import enqueue as enqueue_analysis
    from tests.integration.test_inventories import SAMPLE

    data = copy.deepcopy(SAMPLE)
    second_package = copy.deepcopy(data["packages"][0])
    second_package["binary_name"] = "apache2-bin"
    data["packages"].append(second_package)
    imported = client.post(
        f"/api/v1/assets/{report_finding['asset_id']}/inventories", headers=headers, json=data
    ).json()
    analysis = enqueue_analysis(client, headers, imported)
    run_once(engine)
    report = enqueue(client, headers, {"analysis_id": analysis["id"]})
    run_once(engine)
    summary = detail(client, headers, report)["content"]["summary"]
    assert summary["finding_count"] == 3 and summary["package_count"] == 3
    assert summary["cve_count"] == 1
    assert summary["verdict_counts"]["NEEDS_REVIEW"] == 2
