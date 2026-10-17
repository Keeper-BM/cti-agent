from uuid import uuid4

import pytest

ASSET = {
    "asset_name": "lab-web-01",
    "host": "192.0.2.10",
    "exposure_source": "synthetic test fixture",
}


@pytest.mark.parametrize("path", ["/assets", "/jobs", "/capabilities"])
def test_business_routes_require_auth(client, path):
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_public_health_and_database_readiness(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert client.get("/api/v1/readiness").json()["status"] == "ready"


def test_create_read_deactivate_and_persist(client, headers):
    response = client.post("/api/v1/assets", json=ASSET, headers=headers)
    assert response.status_code == 201
    asset = response.json()
    assert asset["created_at"].endswith("Z") or asset["created_at"].endswith("+00:00")
    assert asset["collection_method"] == "MANUAL"
    listing = client.get("/api/v1/assets", headers=headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == asset["id"]
    updated = client.patch(
        f"/api/v1/assets/{asset['id']}", json={"is_active": False}, headers=headers
    )
    assert updated.status_code == 200
    detail = client.get(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert detail.json()["is_active"] is False


def test_duplicate_name_and_unknown_asset(client, headers):
    client.post("/api/v1/assets", json=ASSET, headers=headers)
    duplicate = client.post("/api/v1/assets", json=ASSET, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_ASSET"
    assert client.get(f"/api/v1/assets/{uuid4()}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"asset_name": "   "},
        {"host": "http://192.0.2.10/path"},
        {"host": "host; whoami"},
        {"collection_method": "SSH"},
        {"ssh_private_key": "PRIVATE-KEY-MUST-NOT-BE-ECHOED"},
    ],
)
def test_invalid_input_is_rejected_without_echoing_values(client, headers, patch):
    response = client.post("/api/v1/assets", json={**ASSET, **patch}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "PRIVATE-KEY-MUST-NOT-BE-ECHOED" not in response.text


def test_collection_is_explicitly_unimplemented(client, headers):
    asset = client.post("/api/v1/assets", json=ASSET, headers=headers).json()
    response = client.post(f"/api/v1/assets/{asset['id']}/collections", headers=headers)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "FEATURE_NOT_IMPLEMENTED"
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 0


def test_job_submission_is_idempotent(client, headers):
    headers = {**headers, "Idempotency-Key": "same-request"}
    first = client.post("/api/v1/jobs/system-checks", headers=headers)
    second = client.post("/api/v1/jobs/system-checks", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "QUEUED"
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 1


def test_missing_idempotency_key_and_invalid_pagination(client, headers):
    assert client.post("/api/v1/jobs/system-checks", headers=headers).status_code == 422
    assert client.get("/api/v1/assets?limit=101", headers=headers).status_code == 422
    assert client.get("/api/v1/assets?offset=-1", headers=headers).status_code == 422


def test_wrong_token_and_capabilities(client, headers):
    rejected = client.get("/api/v1/assets", headers={"Authorization": "Bearer incorrect"})
    assert rejected.status_code == 401
    features = client.get("/api/v1/capabilities", headers=headers).json()["features"]
    assert features["assessment"] is False
    assert features["worker_system_check"] is True
