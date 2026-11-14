"""Disposable account-mode API/worker processes for Compose recovery acceptance."""

import json
import re
import secrets
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.postgres_backup import ComposePostgres, database_name


def require(value, message):
    if not value:
        raise AssertionError(message)


def command(args, *, input=None, check=True, timeout=90):
    result = subprocess.run(
        args,
        input=input,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    # Never print subprocess output: bootstrap stdin and container env contain credentials.
    if check and result.returncode:
        raise RuntimeError(f"Compose acceptance command failed (exit {result.returncode})")
    return result.stdout


def database_code(name):
    name = database_name(name)
    return (
        "import os; from sqlalchemy.engine import make_url; "
        f"os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL'])"
        f".set(database={name!r}).render_as_string(hide_password=False); "
    )


class AccountStack:
    def __init__(self, project, env_file):
        self.db = ComposePostgres(project, Path(env_file))
        self.source = "cti_accounts_" + uuid4().hex
        self.target = "cti_restored_" + uuid4().hex
        self.password = secrets.token_urlsafe(32)
        self.containers = []
        self.databases = []
        self.worker = None

    def initialize(self):
        self.db.create_database(self.source)
        self.databases.append(self.source)
        bootstrap = database_code(self.source) + (
            "import json,sys; from alembic import command; from alembic.config import Config; "
            "command.upgrade(Config('alembic.ini'), 'head'); "
            "from backend.core.database import get_engine; "
            "from backend.auth.passwords import hash_password; "
            "from backend.models.tables import User; from sqlalchemy.orm import Session; "
            "password=json.load(sys.stdin)['password']; "
            "db=Session(get_engine()); "
            "db.add(User(username='restore-admin',display_name='Recovery admin',role='ADMIN',"
            "password_hash=hash_password(password))); db.commit(); db.close()"
        )
        command(
            [*self.db.compose, "run", "--rm", "-T", "--no-deps", "api", "python", "-c", bootstrap],
            input=json.dumps({"password": self.password}).encode(),
        )
        self.db.database = self.source

    def start(self, database, *, worker=False):
        name = "cti-account-check-" + uuid4().hex
        self.containers.append(name)
        args = [*self.db.compose, "run", "--detach", "--no-deps", "--name", name]
        for value in (
            "AUTH_MODE=accounts",
            "SESSION_COOKIE_SECURE=false",
            "WORKER_POLL_SECONDS=0.2",
            "LLM_BASE_URL=",
            "LLM_API_KEY=",
            "LLM_MODEL=",
            "SSH_ALLOWED_TARGETS=",
        ):
            args.extend(["--env", value])
        if not worker:
            args.extend(["--publish", "127.0.0.1::8000"])
        code = database_code(database) + (
            "import runpy; runpy.run_module('backend.worker',run_name='__main__')"
            if worker
            else "import uvicorn; uvicorn.run('backend.api.main:app',host='0.0.0.0',port=8000)"
        )
        command([*args, "worker" if worker else "api", "python", "-c", code])
        if worker:
            self.worker = name
            return name
        address = command(["docker", "port", name, "8000/tcp"]).decode().strip()
        require(re.fullmatch(r"127\.0\.0\.1:[0-9]+", address), "Expected a loopback API binding")
        url = "http://" + address
        deadline = time.monotonic() + 45
        with httpx.Client(base_url=url, timeout=3) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get("/api/v1/readiness").status_code == 200:
                        return url
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
        raise RuntimeError("Account-mode API did not become ready")

    def stop_worker(self):
        command(["docker", "stop", self.worker])

    def resume_worker(self):
        command(["docker", "start", self.worker])

    def close(self):
        # Names are generated only by this instance; never remove an existing project service.
        try:
            for name in reversed(self.containers):
                command(["docker", "rm", "--force", name], check=False)
        finally:
            for name in reversed(self.databases):
                self.db.drop_created_database(name)


@contextmanager
def account_stack(project, env_file):
    stack = AccountStack(project, env_file)
    try:
        stack.initialize()
        yield stack
    finally:
        stack.close()


def request(client, method, path, status=200, **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    require(response.status_code == status, f"{method} {path}: HTTP {response.status_code}")
    return response


def login(client, username, password):
    response = request(
        client, "POST", "/auth/login", json={"username": username, "password": password}
    )
    cookie = response.headers.get("set-cookie", "")
    require(
        "HttpOnly" in cookie and "SameSite=strict" in cookie, "Missing session cookie protections"
    )
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["user"]


def enqueue(client, path, payload):
    return request(
        client, "POST", path, 202, headers={"Idempotency-Key": str(uuid4())}, json=payload
    ).json()


def completed(client, path, *, expected="SUCCEEDED"):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        data = request(client, "GET", path).json()
        job = data.get("job", data)
        if job["status"] not in {"QUEUED", "RUNNING"}:
            require(job["status"] == expected, f"Unexpected terminal status at {path}")
            return data
        time.sleep(0.25)
    raise RuntimeError("Worker did not finish the acceptance job")
