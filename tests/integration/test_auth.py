from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.main import create_app
from backend.auth.passwords import hash_password
from backend.core.config import get_settings
from backend.models.tables import Job, LoginSession, User, utcnow
from backend.worker.runner import run_once
from tests.integration import test_explanations as explanation_tests
from tests.integration import test_sources as source_tests

source_wire = source_tests.source_wire
finding = explanation_tests.finding
llm_wire = explanation_tests.llm_wire
PASSWORD = "correct-password-for-tests-123"


@pytest.fixture
def accounts(engine, monkeypatch):
    with Session(engine) as db, db.begin():
        users = []
        hashed = hash_password(PASSWORD)
        for name, role in [("admin", "ADMIN"), ("operator", "OPERATOR"), ("viewer", "VIEWER")]:
            user = User(username=name, display_name=name, password_hash=hashed, role=role)
            db.add(user)
            users.append(user)
        db.flush()
        result = {u.username: u.id for u in users}
    monkeypatch.setenv("AUTH_MODE", "accounts")
    get_settings.cache_clear()
    return result


def login(client, name="admin"):
    result = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
    assert result.status_code == 200, result.text
    cookies = result.headers.get("set-cookie", "")
    assert "HttpOnly" in cookies and "SameSite=strict" in cookies
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def test_login_cookie_csrf_logout_and_session_expiry(client, engine, headers, accounts):
    assert client.get("/api/v1/assets", headers=headers).status_code == 401
    h = login(client)
    cookie = client.cookies.get("cti_session")
    assert cookie
    assert client.get("/api/v1/auth/me").json()["user"]["username"] == "admin"
    assert (
        client.post(
            "/api/v1/assets", json={"asset_name": "test", "exposure_source": "test"}
        ).status_code
        == 403
    )
    rejected = client.post(
        "/api/v1/assets",
        headers={**h, "Origin": "https://evil.invalid"},
        json={"asset_name": "test", "exposure_source": "test"},
    )
    assert rejected.status_code == 403
    created = client.post(
        "/api/v1/assets", headers=h, json={"asset_name": "test", "exposure_source": "test"}
    )
    assert created.status_code == 201
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client)
    with Session(engine) as db, db.begin():
        session = db.scalar(select(LoginSession))
        session.expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/v1/assets").status_code == 401


def test_asset_scope_applies_to_lists_details_jobs_reports_and_revocation(
    client, headers, engine, finding, accounts
):
    target = finding["asset_id"]
    admin = login(client)
    other = client.post(
        "/api/v1/assets", headers=admin, json={"asset_name": "other", "exposure_source": "test"}
    ).json()
    granted = client.post(
        f"/api/v1/admin/assets/{target}/grants",
        headers=admin,
        json={"user_id": accounts["operator"]},
    )
    assert granted.status_code == 200
    with TestClient(create_app()) as operator:
        h = login(operator, "operator")
        listed = operator.get("/api/v1/assets").json()
        assert listed["total"] == 1 and listed["items"][0]["id"] == target
        assert operator.get(f"/api/v1/assets/{other['id']}").status_code == 404
        assert operator.get(f"/api/v1/findings/{finding['finding_id']}").status_code == 200
        assert operator.get("/api/v1/admin/users").status_code == 403
        assert (
            operator.post(
                "/api/v1/sources/kev/sync", headers={**h, "Idempotency-Key": str(uuid4())}, json={}
            ).status_code
            == 403
        )
        assert (
            operator.post(
                "/api/v1/assets", headers=h, json={"asset_name": "bad", "exposure_source": "test"}
            ).status_code
            == 403
        )
        report = operator.post(
            "/api/v1/reports",
            headers={**h, "Idempotency-Key": "operator-report"},
            json={"analysis_id": finding["analysis_id"]},
        )
        assert report.status_code == 202, report.text
        report = report.json()
        with Session(engine) as db:
            assert db.get(Job, report["job"]["id"]).requested_by == accounts["operator"]
        client.delete(f"/api/v1/admin/assets/{target}/grants/{accounts['operator']}", headers=admin)
        assert operator.get("/api/v1/assets").json()["total"] == 0
        assert operator.get(f"/api/v1/findings/{finding['finding_id']}").status_code == 404
        assert operator.get(f"/api/v1/analyses/{finding['analysis_id']}").status_code == 404
        assert operator.get(f"/api/v1/reports/{report['id']}").status_code == 404
        assert operator.get(f"/api/v1/jobs/{report['job']['id']}").status_code == 404
        assert operator.get("/api/v1/findings").json()["total"] == 0
        assert operator.get("/api/v1/reports").json()["total"] == 0
        run_once(engine)
        with Session(engine) as db:
            assert db.get(Job, report["job"]["id"]).error_code == "JOB_ACCESS_REVOKED"


def test_viewer_reads_only_granted_assets_and_cannot_queue(client, engine, accounts):
    admin = login(client)
    asset = client.post(
        "/api/v1/assets", headers=admin, json={"asset_name": "view", "exposure_source": "test"}
    ).json()
    client.post(
        f"/api/v1/admin/assets/{asset['id']}/grants",
        headers=admin,
        json={"user_id": accounts["viewer"]},
    )
    with TestClient(create_app()) as viewer:
        h = login(viewer, "viewer")
        assert viewer.get("/api/v1/assets").json()["total"] == 1
        assert (
            viewer.patch(
                f"/api/v1/assets/{asset['id']}", headers=h, json={"is_active": False}
            ).status_code
            == 403
        )
        assert (
            viewer.post(
                "/api/v1/jobs/system-checks", headers={**h, "Idempotency-Key": "forbidden"}
            ).status_code
            == 403
        )
        assert viewer.get("/api/v1/collections/settings").status_code == 403
        assert viewer.get("/api/v1/audit").status_code == 403
        assert viewer.post("/api/v1/auth/logout", headers=h).status_code == 200


def test_account_changes_revoke_sessions_and_last_admin_cannot_be_removed(client, accounts):
    admin = login(client)
    assert (
        client.patch(
            f"/api/v1/admin/users/{accounts['admin']}", headers=admin, json={"role": "VIEWER"}
        ).status_code
        == 409
    )
    with TestClient(create_app()) as viewer:
        login(viewer, "viewer")
        assert (
            client.patch(
                f"/api/v1/admin/users/{accounts['viewer']}",
                headers=admin,
                json={"is_active": False},
            ).status_code
            == 200
        )
        assert viewer.get("/api/v1/auth/me").status_code == 401
    audit = client.get("/api/v1/audit").json()
    assert any(r["action"] == "user.updated" for r in audit["items"])
    assert PASSWORD not in str(audit)


def test_login_rate_limit_and_no_secret_echo(client, accounts):
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login", json={"username": "missing", "password": "wrong-password-secret"}
        )
        assert response.status_code == 401 and "wrong-password-secret" not in response.text
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "missing", "password": "wrong"}
        ).status_code
        == 429
    )
