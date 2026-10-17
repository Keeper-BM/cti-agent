"""Unimplemented endpoints must not produce assessment or AI results."""

from uuid import uuid4

import pytest

FIXTURE_ID = str(uuid4())


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/findings", None),
        ("get", f"/findings/{FIXTURE_ID}", None),
        (
            "post",
            "/analyses",
            {"inventory_id": FIXTURE_ID, "feed_snapshot_id": FIXTURE_ID},
        ),
        ("post", "/questions", {"requested_asset_ids": [FIXTURE_ID], "question": "근거는?"}),
        ("post", "/reports", {"analysis_ids": [FIXTURE_ID]}),
        ("get", f"/reports/{FIXTURE_ID}", None),
        ("get", f"/reports/{FIXTURE_ID}/markdown", None),
        ("get", "/sources/status", None),
        ("post", "/sources/ubuntu/sync", None),
    ],
)
def test_feature_boundaries_require_auth_and_do_not_enqueue_work(
    client, headers, method, path, payload
):
    kwargs = {"json": payload} if payload is not None else {}
    assert client.request(method, f"/api/v1{path}", **kwargs).status_code == 401
    response = client.request(method, f"/api/v1{path}", headers=headers, **kwargs)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "FEATURE_NOT_IMPLEMENTED"
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"requested_asset_ids": [], "question": "근거는?"},
        {"requested_asset_ids": [FIXTURE_ID], "question": "   "},
        {"requested_asset_ids": [FIXTURE_ID], "question": "근거는?", "command": "whoami"},
    ],
)
def test_questions_require_asset_scope_and_nonempty_text(client, headers, payload):
    response = client.post("/api/v1/questions", headers=headers, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
