import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.inventory_upload import MAX_INVENTORY_BYTES
from backend.api.main import create_app
from backend.models.tables import InventoryRecord

SAMPLE = json.loads(
    Path("frontend/public/examples/inventory.sample.json").read_text(encoding="utf-8")
)


@pytest.fixture
def asset_path(client, headers):
    response = client.post(
        "/api/v1/assets",
        headers=headers,
        json={"asset_name": "inventory-lab", "exposure_source": "test"},
    )
    return f"/api/v1/assets/{response.json()['id']}/inventories"


def test_import_preserves_data_and_survives_new_app_session(client, headers, asset_path, engine):
    response = client.post(asset_path, json=SAMPLE, headers=headers)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["os"] == SAMPLE["os"]
    assert saved["collection_method"] == "JSON"
    assert saved["collection_status"] == "PARTIAL"
    assert saved["is_synthetic"] is True
    assert saved["collected_at"] == "2026-11-09T00:00:00Z"
    assert saved["packages"][0]["binary_version"] == "2.4.52-1ubuntu4.4"
    assert saved["packages"][0]["source_version"] == "2.4.52-1ubuntu4.4"
    assert saved["packages"][0]["origin_description"] == SAMPLE["packages"][0]["origin"]
    assert saved["packages"][0]["origin_status"] == "USER_DECLARED"
    assert saved["packages"][0]["origin_evidence_ref"] is None
    assert saved["packages"][1]["binary_version"] is None
    assert saved["packages"][1]["origin_status"] == "UNKNOWN"
    assert "packages[1].binary_version" in saved["coverage"]["missing_fields"]
    with Session(engine) as db:
        assert db.get(InventoryRecord, saved["inventory_id"]).payload == saved
    with TestClient(create_app()) as reconnected:
        detail = reconnected.get(f"{asset_path}/{saved['inventory_id']}", headers=headers)
        assert detail.json() == saved
        history = reconnected.get(asset_path, headers=headers).json()
        assert history["total"] == 1
        assert history["items"][0]["package_count"] == 2
        assert history["items"][0]["ingested_at"].endswith("Z")
        assert "packages" not in history["items"][0]


def test_each_import_appends_history_and_old_snapshot_is_unchanged(client, headers, asset_path):
    first = client.post(asset_path, json=SAMPLE, headers=headers).json()
    changed = copy.deepcopy(SAMPLE)
    changed["packages"][0]["binary_version"] = "2.4.52-1ubuntu4.5"
    second = client.post(asset_path, json=changed, headers=headers).json()
    third = client.post(asset_path, json=changed, headers=headers).json()
    assert len({first["inventory_id"], second["inventory_id"], third["inventory_id"]}) == 3
    listing = client.get(f"{asset_path}?limit=2", headers=headers).json()
    assert listing["total"] == 3
    assert [i["inventory_id"] for i in listing["items"]] == [
        third["inventory_id"],
        second["inventory_id"],
    ]
    older = client.get(f"{asset_path}?limit=2&offset=2", headers=headers).json()
    assert older["items"][0]["inventory_id"] == first["inventory_id"]
    assert client.get(f"{asset_path}/{first['inventory_id']}", headers=headers).json() == first


@pytest.mark.parametrize(
    "change",
    [
        {"os": {"id": "windows", "version_id": "22.04"}},
        {"collected_at": "2026-11-09T09:00:00"},
        {"collected_at": 12345},
        {"asset_id": str(uuid4())},
        {"inventory_id": str(uuid4())},
        {"collection_method": "SSH"},
        {"apache_http2": {"service_active": True, "module_loaded": True}},
        {"verification_id": str(uuid4())},
        {"package_list_complete": "true"},
        {"packages": []},
        {"packages": [SAMPLE["packages"][0]] * 2},
        {"packages": [{"binary_name": "   "}]},
        {"packages": [{"binary_name": "apache2", "binary_version": 24}]},
        {"packages": [{"binary_name": "apache2", "binary_version": "1.0;whoami"}]},
        {"packages": [{"binary_name": "apache2", "source_version": "1.0"}]},
        {"packages": [{"binary_name": "apache2", "origin_status": "SUPPORTED_ORIGIN"}]},
        {"packages": [{"binary_name": "apache2", "package_id": str(uuid4())}]},
    ],
)
def test_invalid_input_cannot_change_existing_inventory(client, headers, asset_path, change):
    saved = client.post(asset_path, json=SAMPLE, headers=headers).json()
    response = client.post(asset_path, json={**SAMPLE, **change}, headers=headers)
    assert response.status_code == 422, response.text
    assert client.get(asset_path, headers=headers).json()["total"] == 1
    assert client.get(f"{asset_path}/{saved['inventory_id']}", headers=headers).json() == saved


def test_asset_scope_auth_and_inactive_asset(client, headers, asset_path):
    saved = client.post(asset_path, json=SAMPLE, headers=headers).json()
    assert client.post(asset_path, json=SAMPLE).status_code == 401
    assert client.get(asset_path).status_code == 401
    assert client.get(f"{asset_path}/{saved['inventory_id']}").status_code == 401
    other = client.post(
        "/api/v1/assets",
        headers=headers,
        json={"asset_name": "other-asset", "exposure_source": "test"},
    ).json()
    other_path = f"/api/v1/assets/{other['id']}/inventories"
    assert client.get(f"{other_path}/{saved['inventory_id']}", headers=headers).status_code == 404
    assert client.get(other_path, headers=headers).json()["total"] == 0
    assert (
        client.post(
            f"/api/v1/assets/{uuid4()}/inventories", json=SAMPLE, headers=headers
        ).status_code
        == 404
    )
    client.patch(
        asset_path.removesuffix("/inventories"), json={"is_active": False}, headers=headers
    )
    assert client.post(asset_path, json=SAMPLE, headers=headers).status_code == 409
    assert client.get(f"{asset_path}/{saved['inventory_id']}", headers=headers).status_code == 200


@pytest.mark.parametrize("raw", [b"{broken", b'{"x": 1, "x": 2}', b'{"x": NaN}', b"\xff"])
def test_malformed_json_is_rejected(client, headers, asset_path, raw, engine):
    response = client.post(
        asset_path, content=raw, headers={**headers, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INVENTORY_JSON"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(InventoryRecord)) == 0


def test_body_limit_without_content_length(client, headers, asset_path):
    chunks = (b" " * 65536 for _ in range(MAX_INVENTORY_BYTES // 65536 + 1))
    response = client.post(
        asset_path, content=chunks, headers={**headers, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert client.get(asset_path, headers=headers).json()["total"] == 0


def test_multiarc_packages_allowed_and_list_completeness_is_preserved(client, headers, asset_path):
    payload = copy.deepcopy(SAMPLE)
    payload["packages"] = [
        payload["packages"][0],
        {**payload["packages"][0], "architecture": "arm64"},
    ]
    payload["package_list_complete"] = True
    response = client.post(asset_path, json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["coverage"]["package_list_complete"] is True
    assert response.json()["collection_status"] == "COMPLETE"
    assert all(p["origin_status"] == "USER_DECLARED" for p in response.json()["packages"])
