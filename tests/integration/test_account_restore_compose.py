"""Real HTTP account permissions and reports survive a PostgreSQL dump/restore.

Creates separate databases and API/worker containers inside an explicit test
Compose project. No external LLM, SSH server, model or security feed is used.
"""

import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest

from backend.auth.passwords import verify_password
from backend.auth.session import token_hash
from scripts.postgres_backup import backup, restore
from tests.fixtures.compose_accounts import (
    account_stack,
    command,
    completed,
    enqueue,
    login,
    request,
    require,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_COMPOSE_PROJECT"),
    reason="Requires an explicit Compose test project",
)


def resource(client, label):
    asset = request(
        client,
        "POST",
        "/assets",
        201,
        json={
            "asset_name": label,
            "exposure_source": "synthetic account recovery acceptance",
        },
    ).json()
    payload = json.loads(Path("frontend/public/examples/inventory.sample.json").read_text())
    payload["is_synthetic"] = True
    inventory = request(
        client, "POST", f"/assets/{asset['id']}/inventories", 201, json=payload
    ).json()
    analysis = enqueue(client, "/analyses", {"inventory_id": inventory["inventory_id"]})
    analysis = completed(client, "/analyses/" + analysis["id"])
    report = enqueue(client, "/reports", {"analysis_id": analysis["id"]})
    report = completed(client, "/reports/" + report["id"])
    require(report["is_synthetic"], "Recovery fixture must remain marked synthetic")
    return {"asset": asset, "inventory": inventory, "analysis": analysis, "report": report}


def paths(data):
    return [
        "/assets/" + data["asset"]["id"],
        f"/assets/{data['asset']['id']}/inventories/{data['inventory']['inventory_id']}",
        "/analyses/" + data["analysis"]["id"],
        "/reports/" + data["report"]["id"],
        "/reports/" + data["report"]["id"] + "/markdown",
        "/jobs/" + data["report"]["job"]["id"],
    ]


def assert_scope(client, allowed, hidden):
    assets = request(client, "GET", "/assets").json()
    require([a["id"] for a in assets["items"]] == [allowed["asset"]["id"]], "Asset scope changed")
    for path in paths(allowed):
        request(client, "GET", path)
    for path in paths(hidden):
        request(client, "GET", path, 404)
    expected_jobs = set()
    for endpoint in ("/analyses", "/reports", "/findings"):
        listing = request(client, "GET", endpoint).json()
        require(listing["items"], "Expected scoped history")
        require(
            all(x["asset_id"] == allowed["asset"]["id"] for x in listing["items"]),
            "Unassigned history leaked",
        )
        if endpoint in {"/analyses", "/reports"}:
            expected_jobs.update(item["job"]["id"] for item in listing["items"])
    jobs = request(client, "GET", "/jobs").json()
    require({item["id"] for item in jobs["items"]} == expected_jobs, "Job scope differs")
    for path in ("/admin/users", "/audit"):
        request(client, "GET", path, 403)


def test_account_permissions_sessions_and_reports_survive_postgres_restore(
    tmp_path, record_testsuite_property
):
    with (
        account_stack(
            os.environ["TEST_POSTGRES_COMPOSE_PROJECT"],
            os.environ["TEST_POSTGRES_COMPOSE_ENV_FILE"],
        ) as stack,
        ExitStack() as clients,
    ):
        url = stack.start(stack.source)
        stack.start(stack.source, worker=True)

        def client(base=url):
            return clients.enter_context(httpx.Client(base_url=base, timeout=15))

        admin, operator, viewer = client(), client(), client()
        request(admin, "GET", "/assets", 401)
        # Read token into memory only; account mode must reject the development credential.
        token = (
            command([*stack.db.compose, "exec", "-T", "api", "printenv", "DEV_API_TOKEN"])
            .decode()
            .strip()
        )
        request(admin, "GET", "/assets", 401, headers={"Authorization": "Bearer " + token})
        login(admin, "restore-admin", stack.password)
        user_ids = {}
        for name, role in [
            ("restore-operator", "OPERATOR"),
            ("restore-viewer", "VIEWER"),
            ("restore-disabled", "VIEWER"),
        ]:
            user = request(
                admin,
                "POST",
                "/admin/users",
                201,
                json={
                    "username": name,
                    "display_name": name,
                    "password": stack.password,
                    "role": role,
                },
            ).json()
            user_ids[name] = user["id"]
            require("password" not in json.dumps(user).lower(), "Password fields exposed")
        allowed, hidden = resource(admin, "allowed"), resource(admin, "hidden")
        for name in ("restore-operator", "restore-viewer"):
            request(
                admin,
                "POST",
                f"/admin/assets/{allowed['asset']['id']}/grants",
                json={"user_id": user_ids[name]},
            )
        login(operator, "restore-operator", stack.password)
        login(viewer, "restore-viewer", stack.password)
        assert_scope(operator, allowed, hidden)
        assert_scope(viewer, allowed, hidden)
        request(
            viewer, "PATCH", "/assets/" + allowed["asset"]["id"], 403, json={"is_active": False}
        )
        request(
            viewer,
            "POST",
            "/reports",
            403,
            headers={"Idempotency-Key": "viewer-denied"},
            json={"analysis_id": allowed["analysis"]["id"]},
        )
        request(
            operator,
            "POST",
            "/assets",
            403,
            json={"asset_name": "denied", "exposure_source": "test"},
        )
        # Check real HTTP CSRF enforcement with an authenticated cookie and no CSRF header.
        no_csrf = client()
        no_csrf.cookies.update(admin.cookies)
        request(
            no_csrf,
            "POST",
            "/assets",
            403,
            json={"asset_name": "denied", "exposure_source": "test"},
        )
        request(
            admin,
            "POST",
            "/assets",
            403,
            headers={"Origin": "https://other.invalid"},
            json={"asset_name": "denied", "exposure_source": "test"},
        )
        own_report = enqueue(operator, "/reports", {"analysis_id": allowed["analysis"]["id"]})
        completed(operator, "/reports/" + own_report["id"])

        # Revocation must also block a queued job in the separate worker process.
        grant_path = f"/admin/assets/{hidden['asset']['id']}/grants"
        request(admin, "POST", grant_path, json={"user_id": user_ids["restore-operator"]})
        stack.stop_worker()
        denied_report = enqueue(operator, "/reports", {"analysis_id": hidden["analysis"]["id"]})
        request(admin, "DELETE", grant_path + "/" + user_ids["restore-operator"])
        stack.resume_worker()
        failed = completed(admin, "/reports/" + denied_report["id"], expected="FAILED")
        require(
            failed["job"]["error_code"] == "JOB_ACCESS_REVOKED", "Worker ignored revoked access"
        )
        request(operator, "GET", "/jobs/" + failed["job"]["id"], 404)

        logged_out, expired, disabled = client(), client(), client()
        login(logged_out, "restore-operator", stack.password)
        logged_out_cookie = logged_out.cookies.get("cti_session")
        request(logged_out, "POST", "/auth/logout")
        request(logged_out, "GET", "/auth/me", 401)
        login(expired, "restore-viewer", stack.password)
        expired_cookie = expired.cookies.get("cti_session")
        login(disabled, "restore-disabled", stack.password)
        disabled_cookie = disabled.cookies.get("cti_session")
        request(
            admin,
            "PATCH",
            "/admin/users/" + user_ids["restore-disabled"],
            json={"is_active": False},
        )
        request(disabled, "GET", "/auth/me", 401)
        failures = client()
        for _ in range(10):
            request(
                failures,
                "POST",
                "/auth/login",
                401,
                json={"username": "restore-missing", "password": "wrong-password"},
            )
        request(
            failures,
            "POST",
            "/auth/login",
            429,
            json={"username": "restore-missing", "password": "wrong-password"},
        )
        # Expire after the last successful login, which otherwise purges expired sessions.
        stack.db.sql(
            stack.source,
            "UPDATE login_sessions SET expires_at=now()-interval '1 second' "
            f"WHERE id='{token_hash(expired_cookie)}';",
        )
        request(expired, "GET", "/auth/me", 401)

        hashes = json.loads(
            stack.db.sql(stack.source, "SELECT json_object_agg(username,password_hash) FROM users;")
        )
        require(len(hashes) == 4, "Missing persisted accounts")
        require(
            all(verify_password(stack.password, value) for value in hashes.values()),
            "Stored password hash failed verification",
        )
        require(
            all(value != stack.password for value in hashes.values()), "Plaintext password stored"
        )
        saved = {
            path: request(admin, "GET", path).content for path in paths(allowed) + paths(hidden)
        }
        saved["/reports/" + failed["id"]] = request(
            admin, "GET", "/reports/" + failed["id"]
        ).content
        users = request(admin, "GET", "/admin/users").json()
        audit = request(admin, "GET", "/audit", params={"limit": 100}).json()
        actions = {item["action"] for item in audit["items"]}
        require(
            {
                "login.succeeded",
                "login.failed",
                "login.rate_limited",
                "logout",
                "asset.access_revoked",
            }
            <= actions,
            "Missing audit history",
        )
        require(stack.password not in json.dumps(audit), "Password leaked into audit history")
        stack.stop_worker()
        archive = tmp_path / "accounts.dump"
        metadata = backup(stack.db, archive)
        counts = {t.name: t.rows for t in metadata.database.tables}
        require(
            counts["users"] == 4 and counts["reports"] == 4, "Account/report backup is incomplete"
        )
        require(
            counts["login_sessions"] > 0 and counts["audit_events"] > 0,
            "Session/audit backup is empty",
        )
        restore(stack.db, archive, stack.target)
        stack.databases.append(stack.target)
        restored_url = stack.start(stack.target)
        restored_admin, restored_operator, restored_viewer = (
            client(restored_url),
            client(restored_url),
            client(restored_url),
        )
        # Check restored sessions first: login intentionally changes audit/session rows.
        for original, fresh in [
            (admin, restored_admin),
            (operator, restored_operator),
            (viewer, restored_viewer),
        ]:
            fresh.cookies.update(original.cookies)
            fresh.headers["X-CSRF-Token"] = original.headers["X-CSRF-Token"]
            require(
                request(fresh, "GET", "/auth/me").json()
                == request(original, "GET", "/auth/me").json(),
                "Restored session differs",
            )
        require(
            request(restored_admin, "GET", "/admin/users").json() == users, "Restored users differ"
        )
        require(
            request(restored_admin, "GET", "/audit", params={"limit": 100}).json() == audit,
            "Restored audit differs",
        )
        for path, value in saved.items():
            require(
                request(restored_admin, "GET", path).content == value,
                "Restored resource differs: " + path,
            )
        report_path = "/reports/" + allowed["report"]["id"] + "/markdown"
        exported = request(restored_viewer, "GET", report_path)
        require(
            hashlib.sha256(exported.content).hexdigest() == allowed["report"]["markdown_sha256"],
            "Restored report checksum differs",
        )
        assert_scope(restored_operator, allowed, hidden)
        assert_scope(restored_viewer, allowed, hidden)
        request(
            restored_viewer,
            "POST",
            "/reports",
            403,
            headers={"Idempotency-Key": "restored-viewer-denied"},
            json={"analysis_id": allowed["analysis"]["id"]},
        )
        for cookie in (logged_out_cookie, expired_cookie, disabled_cookie):
            rejected = client(restored_url)
            rejected.cookies.set("cti_session", cookie, path="/api")
            request(rejected, "GET", "/auth/me", 401)
        request(
            client(restored_url),
            "POST",
            "/auth/login",
            429,
            json={"username": "restore-missing", "password": "wrong-password"},
        )
        # Check password verification through a new login in the restored application.
        new_login = client(restored_url)
        login(new_login, "restore-operator", stack.password)
        request(new_login, "POST", "/auth/logout")
        request(new_login, "GET", "/auth/me", 401)
        request(restored_operator, "GET", "/auth/me")
        revoked_path = (
            f"/admin/assets/{allowed['asset']['id']}/grants/{user_ids['restore-operator']}"
        )
        request(restored_admin, "DELETE", revoked_path)
        request(restored_operator, "GET", report_path, 404)
        # Restored DB mutations must not alter the still-running original DB.
        request(operator, "GET", report_path)
        for name, value in {
            "tables": len(metadata.database.tables),
            "users": counts["users"],
            "reports": counts["reports"],
            "sessions": counts["login_sessions"],
            "audit_events": counts["audit_events"],
            "saved_responses": len(saved),
            "dump_sha256": metadata.sha256,
        }.items():
            record_testsuite_property("account_restore." + name, value)
