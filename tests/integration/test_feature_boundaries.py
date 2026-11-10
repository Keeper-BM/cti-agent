"""Invalid or inaccessible question scopes must never enqueue AI work."""

from uuid import uuid4

import pytest

FIXTURE_ID = str(uuid4())


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/questions", {"analysis_ids": [FIXTURE_ID], "question": "근거를 알려줘"}),
    ],
)
def test_feature_boundaries_require_auth_and_do_not_enqueue_work(
    client, headers, method, path, payload
):
    kwargs = {"json": payload} if payload is not None else {}
    assert client.request(method, f"/api/v1{path}", **kwargs).status_code == 401
    response = client.request(
        method, f"/api/v1{path}", headers={**headers, "Idempotency-Key": "missing-scope"}, **kwargs
    )
    assert response.status_code == 404
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"analysis_ids": [], "question": "근거를 알려줘"},
        {"analysis_ids": [FIXTURE_ID], "question": "   "},
        {"analysis_ids": [FIXTURE_ID], "question": "근거를 알려줘", "command": "whoami"},
        {"analysis_ids": [FIXTURE_ID, FIXTURE_ID], "question": "근거를 알려줘"},
        {"analysis_ids": [FIXTURE_ID], "question": "dcu_llm_secret-key"},
    ],
)
def test_questions_require_asset_scope_and_nonempty_text(client, headers, payload):
    response = client.post(
        "/api/v1/questions", headers={**headers, "Idempotency-Key": "invalid"}, json=payload
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
