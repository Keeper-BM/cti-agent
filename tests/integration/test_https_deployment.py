"""Opt-in HTTPS/real-browser acceptance; creates and removes its own Compose project."""

import hashlib
import os
import socket
import ssl
import subprocess
import time
from contextlib import ExitStack

import httpx
import pytest

from backend.auth.session import token_hash
from tests.fixtures.compose_accounts import command, login, request, require
from tests.fixtures.https_stack import HTTPSStack
from tests.integration.test_account_restore_compose import assert_scope, resource

pytestmark = pytest.mark.skipif(
    os.getenv("TEST_HTTPS_DEPLOYMENT") != "1" or os.name != "posix",
    reason="Requires explicit disposable HTTPS Compose acceptance on POSIX",
)


@pytest.fixture(scope="module")
def https_stack(tmp_path_factory):
    stack = HTTPSStack(tmp_path_factory.mktemp("https-deployment"))
    try:
        stack.start()
        yield stack
    finally:
        stack.close()


def test_tls_trust_cookie_roles_csrf_expiry_and_logout(https_stack, record_testsuite_property):
    stack = https_stack
    with ExitStack() as clients:

        def client():
            return clients.enter_context(stack.client())

        # A trusted CA and matching hostname are mandatory, never verify=False.
        with pytest.raises(httpx.ConnectError):
            httpx.get(stack.url + "/api/v1/readiness", timeout=10, trust_env=False)
        plain = httpx.get(
            stack.url.replace("https:", "http:") + "/api/v1/auth/status",
            timeout=10,
            trust_env=False,
        )
        require(plain.status_code == 400, "TLS listener accepted plaintext application traffic")
        with socket.create_connection(("127.0.0.1", stack.port), timeout=10) as raw:
            with pytest.raises(ssl.SSLCertVerificationError):
                stack.context.wrap_socket(raw, server_hostname="wrong.invalid")
        for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
            context = ssl.create_default_context(cafile=str(stack.directory / "ca.pem"))
            context.minimum_version = context.maximum_version = version
            with socket.create_connection(("127.0.0.1", stack.port), timeout=10) as raw:
                with context.wrap_socket(raw, server_hostname="localhost") as tls:
                    require(tls.version() in {"TLSv1.2", "TLSv1.3"}, "Unexpected TLS version")

        admin, operator, viewer = client(), client(), client()
        readiness = request(admin, "GET", "/readiness")
        require(readiness.headers["strict-transport-security"] == "max-age=86400", "HSTS missing")
        request(
            admin, "GET", "/assets", 401, headers={"Authorization": "Bearer " + stack.dev_token}
        )
        response = request(
            admin,
            "POST",
            "/auth/login",
            json={
                "username": "https-admin",
                "password": stack.password,
            },
            headers={"Origin": stack.url},
        )
        cookie = response.headers["set-cookie"]
        require(
            all(
                x in cookie
                for x in ("Secure", "HttpOnly", "SameSite=strict", "Path=/api", "Max-Age=")
            ),
            "Session cookie lacks required attributes",
        )
        admin.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        ids = {}
        for name, role in (
            ("https-operator", "OPERATOR"),
            ("https-viewer", "VIEWER"),
            ("https-disabled", "VIEWER"),
        ):
            ids[name] = request(
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
            ).json()["id"]
        allowed, hidden = resource(admin, "https-allowed"), resource(admin, "https-hidden")
        for name in ("https-operator", "https-viewer"):
            request(
                admin,
                "POST",
                f"/admin/assets/{allowed['asset']['id']}/grants",
                json={"user_id": ids[name]},
            )
        login(operator, "https-operator", stack.password)
        login(viewer, "https-viewer", stack.password)
        assert_scope(operator, allowed, hidden)
        assert_scope(viewer, allowed, hidden)
        request(
            viewer, "PATCH", "/assets/" + allowed["asset"]["id"], 403, json={"is_active": False}
        )
        report = request(viewer, "GET", "/reports/" + allowed["report"]["id"] + "/markdown")
        require(
            hashlib.sha256(report.content).hexdigest() == allowed["report"]["markdown_sha256"],
            "Report differs",
        )

        no_csrf = client()
        no_csrf.cookies.update(admin.cookies)
        payload = {"asset_name": "should-be-denied", "exposure_source": "test"}
        request(no_csrf, "POST", "/assets", 403, json=payload)
        for origin in ("https://other.invalid", stack.url.replace("https:", "http:"), "null"):
            request(admin, "POST", "/assets", 403, json=payload, headers={"Origin": origin})
        # Secure cookies must not be selected for HTTP by a standards-aware HTTP client.
        insecure = admin.build_request(
            "GET", stack.url.replace("https:", "http:") + "/api/v1/auth/me"
        )
        require("cookie" not in insecure.headers, "Secure cookie selected for HTTP")

        expired, disabled = client(), client()
        login(expired, "https-viewer", stack.password)
        login(disabled, "https-disabled", stack.password)
        stack.db.sql(
            stack.db.database,
            "UPDATE login_sessions SET expires_at=now()-interval '1 second' "
            f"WHERE id='{token_hash(expired.cookies.get('cti_session'))}';",
        )
        request(expired, "GET", "/auth/me", 401)
        request(admin, "PATCH", "/admin/users/" + ids["https-disabled"], json={"is_active": False})
        request(disabled, "GET", "/auth/me", 401)
        cookie_before_logout = operator.cookies.get("cti_session")
        request(operator, "POST", "/auth/logout")
        request(operator, "GET", "/auth/me", 401)
        replay = client()
        request(
            replay,
            "GET",
            "/auth/me",
            401,
            headers={"Cookie": "cti_session=" + cookie_before_logout},
        )
        failures = client()
        for _ in range(10):
            request(
                failures,
                "POST",
                "/auth/login",
                401,
                json={"username": "https-missing", "password": "wrong"},
            )
        request(
            failures,
            "POST",
            "/auth/login",
            429,
            json={"username": "https-missing", "password": "wrong"},
        )
        record_testsuite_property("https.tls_versions", "TLSv1.2,TLSv1.3")
        record_testsuite_property("https.roles", "ADMIN,OPERATOR,VIEWER")


def test_browser_login_reload_secure_cookie_and_logout(https_stack, record_testsuite_property):
    from playwright.sync_api import Error as BrowserError
    from playwright.sync_api import expect, sync_playwright

    stack = https_stack
    with sync_playwright() as playwright:
        # Trust only this disposable leaf key in this isolated browser process. No system
        # CA installation, global certificate-ignore flag, or ignore_https_errors is used.
        browser = playwright.chromium.launch(
            args=["--ignore-certificate-errors-spki-list=" + stack.spki]
        )
        try:
            context = browser.new_context()
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda _error: errors.append("pageerror"))
            page.goto(stack.url)
            page.get_by_label("로그인 이름", exact=True).fill("https-admin")
            page.get_by_label("비밀번호", exact=True).fill(stack.password)
            page.get_by_role("button", name="로그인", exact=True).click()
            expect(page.get_by_role("button", name="로그아웃", exact=True)).to_be_visible()
            require(page.evaluate("window.isSecureContext"), "Browser is not a secure context")
            cookies = [c for c in context.cookies() if c["name"] == "cti_session"]
            require(
                len(cookies) == 1
                and cookies[0]["secure"]
                and cookies[0]["httpOnly"]
                and cookies[0]["sameSite"] == "Strict"
                and cookies[0]["path"] == "/api",
                "Browser cookie differs",
            )
            # Read at /api so Path=/api cannot hide a missing HttpOnly protection.
            context.add_cookies(
                [
                    {
                        "name": "cti-visibility-probe",
                        "value": "visible",
                        "domain": "127.0.0.1",
                        "path": "/api",
                        "secure": True,
                        "httpOnly": False,
                        "sameSite": "Strict",
                    }
                ]
            )
            probe = context.new_page()
            probe.goto(stack.url + "/api/v1/auth/status")
            visible = probe.evaluate("document.cookie")
            require(
                "cti-visibility-probe=visible" in visible and "cti_session=" not in visible,
                "HttpOnly session visibility differs",
            )
            probe.evaluate("document.cookie='cti-visibility-probe=; Max-Age=0; Path=/api; Secure'")
            probe.close()
            page.reload()
            expect(page.get_by_role("button", name="로그아웃", exact=True)).to_be_visible()
            page.get_by_role("button", name="로그아웃", exact=True).click()
            expect(page.get_by_role("button", name="로그인", exact=True)).to_be_visible()
            require(
                not [c for c in context.cookies() if c["name"] == "cti_session"],
                "Cookie survived logout",
            )
            page.reload()
            expect(page.get_by_role("button", name="로그인", exact=True)).to_be_visible()
            require(not errors, "Browser application error")
            record_testsuite_property("https.browser", "Chromium " + browser.version)
        except BrowserError:
            # Playwright's action logs may include the value passed to fill().
            raise AssertionError("HTTPS browser acceptance failed") from None
        finally:
            browser.close()


def test_certificate_reload_and_secure_session_survive_api_recreation(https_stack):
    stack = https_stack
    with stack.client() as client:
        login(client, "https-admin", stack.password)
        before = request(client, "GET", "/assets").content
        # A missing renewal file must fail preflight while the current TLS workers
        # continue serving the previously loaded certificate. Never reload on failure.
        certificate = stack.tls / "fullchain.pem"
        held = stack.tls / "fullchain.held"
        certificate.rename(held)
        try:
            checked = subprocess.run(
                [*stack.compose, "exec", "-T", "web", "nginx", "-t"],
                capture_output=True,
                check=False,
                timeout=20,
            )
            require(checked.returncode != 0, "Missing certificate passed nginx preflight")
            require(
                request(client, "GET", "/assets").content == before,
                "Failed renewal interrupted current TLS service",
            )
        finally:
            held.rename(certificate)
        old_fingerprint = stack.fingerprint
        stack.issue_certificate()
        command([*stack.compose, "exec", "-T", "web", "nginx", "-t"])
        command([*stack.compose, "exec", "-T", "web", "nginx", "-s", "reload"])
        # Poll fresh TLS connections until nginx's new certificate is active.
        deadline = time.monotonic() + 15
        observed = None
        while time.monotonic() < deadline:
            with socket.create_connection(("127.0.0.1", stack.port), timeout=5) as raw:
                with stack.context.wrap_socket(raw, server_hostname="localhost") as tls:
                    observed = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
            if observed == stack.fingerprint:
                break
            time.sleep(0.2)
        require(observed == stack.fingerprint != old_fingerprint, "Renewed certificate not served")
        command(
            [*stack.compose, "up", "-d", "--no-deps", "--force-recreate", "--wait", "api"],
            timeout=120,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = client.get("/api/v1/assets")
            if response.status_code == 200:
                break
            time.sleep(0.5)
        require(
            response.status_code == 200 and response.content == before,
            "HTTPS session/data lost after recreate",
        )
        request(client, "POST", "/auth/logout")
