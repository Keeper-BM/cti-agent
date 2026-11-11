"""Opt-in acceptance test against an explicitly configured Ubuntu/MySQL SSH lab.

The remote collector executes only its fixed read commands. VM provisioning,
service changes and VM snapshot restoration belong to the separate lab procedure.
"""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.api.schemas.collections import SSHProfileInput
from backend.collectors.ssh_protocol import COMMANDS, CommandResult
from backend.core.config import get_settings
from backend.core.database import get_engine
from backend.worker.runner import run_once
from scripts.database_backup import backup, restore, verify


@pytest.mark.skipif(
    not os.getenv("TEST_MYSQL_SSH_PROFILE"), reason="Requires an explicit Ubuntu/MySQL SSH lab"
)
def test_real_mysql_collection_failure_history_and_database_restore(
    client, headers, engine, tmp_path, monkeypatch, record_property
):
    profile = SSHProfileInput.model_validate_json(
        Path(os.environ["TEST_MYSQL_SSH_PROFILE"]).read_text(encoding="utf-8")
    )
    host = f"[{profile.host}]" if ":" in profile.host else profile.host
    monkeypatch.setenv("SSH_ALLOWED_TARGETS", f"{host}:{profile.port}")
    monkeypatch.setenv("SSH_KEY_DIRECTORY", os.environ["TEST_MYSQL_KEY_DIRECTORY"])
    get_settings.cache_clear()

    def request(method, path, expected=200, **kwargs):
        response = getattr(client, method)(path, headers=headers, **kwargs)
        assert response.status_code == expected, response.text
        return response.json()

    asset = request(
        "post",
        "/api/v1/assets",
        201,
        json={"asset_name": "mysql-acceptance", "exposure_source": "isolated-test-vm"},
    )
    base = f"/api/v1/assets/{asset['id']}"
    saved_profile = request("put", f"{base}/ssh-profile", json=profile.model_dump())

    def collect(profile_id):
        response = client.post(
            f"{base}/collections",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"profile_id": profile_id},
        )
        assert response.status_code == 202, response.text
        assert run_once(engine)
        return request("get", f"{base}/collections/{response.json()['id']}")

    first = collect(saved_profile["id"])
    assert first["job"]["status"] == "SUCCEEDED", first["job"]
    inventory_path = f"{base}/inventories/{first['inventory_id']}"
    inventory = request("get", inventory_path)
    assert inventory["collection_method"] == "SSH"
    assert inventory["collection_status"] == "COMPLETE"
    assert inventory["is_synthetic"] is False
    assert inventory["coverage"]["package_list_complete"] is True
    assert inventory["os"]["id"] == "ubuntu"
    mysql = [p for p in inventory["packages"] if p["source_name"] == "mysql-8.0"]
    assert {"mysql-server-8.0", "mysql-server-core-8.0", "mysql-client-core-8.0"} <= {
        p["binary_name"] for p in mysql
    }
    assert all(p["install_status"] == "installed" and p["binary_version"] for p in mysql)
    assert all(p["origin_status"] == "UNKNOWN" for p in mysql)
    evidence = first["evidence"]
    assert evidence["verified_host_fingerprint"] == profile.host_fingerprint
    services = {service["unit"]: service for service in evidence["services"]}
    assert set(services) == {"apache2.service", "mysql.service"}
    assert all(service["status"] != "UNKNOWN" for service in services.values())
    assert services["mysql.service"]["status"] == "OBSERVED"
    assert services["mysql.service"]["active_state"] == os.getenv(
        "TEST_MYSQL_SERVICE_STATE", "active"
    )
    if expected_apache := os.getenv("TEST_APACHE_SERVICE_STATE"):
        assert services["apache2.service"]["status"] == "OBSERVED"
        assert services["apache2.service"]["active_state"] == expected_apache
        assert any(
            p["binary_name"] == "apache2-bin" and p["install_status"] == "installed"
            for p in inventory["packages"]
        )
    commands = [CommandResult.model_validate(value) for value in evidence["commands"]]
    assert [command.name for command in commands] == list(COMMANDS)
    assert all(command.exit_code == 0 for command in commands)
    wire = "\n".join(command.model_dump_json() for command in commands)
    assert hashlib.sha256(wire.encode()).hexdigest() == evidence["output_sha256"]

    bad_profile = request(
        "put",
        f"{base}/ssh-profile",
        json={**profile.model_dump(), "host_fingerprint": "SHA256:" + "A" * 43},
    )
    failed = collect(bad_profile["id"])
    assert failed["job"]["status"] == "FAILED"
    assert failed["job"]["error_code"] == "SSH_HOST_KEY_MISMATCH"
    assert failed["inventory_id"] is None
    assert request("get", inventory_path) == inventory
    assert request("get", f"{base}/inventories")["total"] == 1

    # Back up actual collected data and its error history, then serve the restored DB.
    original_url = str(engine.url)
    backup_path, restored_path = tmp_path / "backup.db", tmp_path / "restored.db"
    metadata = backup(Path(engine.url.database), backup_path)
    assert verify(backup_path) == metadata
    restore(backup_path, restored_path)
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{restored_path}")
    get_engine.cache_clear()
    get_settings.cache_clear()
    restored_engine = get_engine()
    try:
        with TestClient(create_app()) as fresh:
            assert fresh.get("/api/v1/readiness").status_code == 200
            for path, expected in (
                (inventory_path, inventory),
                (f"{base}/collections/{first['id']}", first),
                (f"{base}/collections/{failed['id']}", failed),
            ):
                response = fresh.get(path, headers=headers)
                assert response.status_code == 200
                assert response.json() == expected
    finally:
        restored_engine.dispose()
        monkeypatch.setenv("DATABASE_URL", original_url)
        get_engine.cache_clear()
        get_settings.cache_clear()

    # Machine-readable evidence in --junitxml; no private keys or credentials.
    record_property("os", json.dumps(inventory["os"], sort_keys=True))
    record_property("package_count", len(inventory["packages"]))
    record_property("collection_sha256", evidence["output_sha256"])
    record_property("services", json.dumps(evidence["services"], sort_keys=True))
    record_property(
        "apache_packages",
        json.dumps(
            [
                {
                    key: p[key]
                    for key in ("binary_name", "binary_version", "source_version", "architecture")
                }
                for p in inventory["packages"]
                if p["source_name"] == "apache2"
            ],
            sort_keys=True,
        ),
    )
    record_property("backup_sha256", metadata["sha256"])
    record_property(
        "mysql_packages",
        json.dumps(
            [
                {
                    key: p[key]
                    for key in ("binary_name", "binary_version", "source_version", "architecture")
                }
                for p in mysql
            ],
            sort_keys=True,
        ),
    )
