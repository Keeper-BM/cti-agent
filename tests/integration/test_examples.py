from backend.examples.assessment import load_assessment_example


def test_example_is_authenticated_repeatable_and_has_no_database_side_effects(client, headers):
    assert client.get("/api/v1/examples/assessment").status_code == 401
    first = client.get("/api/v1/examples/assessment", headers=headers)
    second = client.get("/api/v1/examples/assessment", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == load_assessment_example().model_dump(mode="json")
    assert client.get("/api/v1/assets", headers=headers).json()["total"] == 0
    assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 0
    features = client.get("/api/v1/capabilities", headers=headers).json()["features"]
    assert features["development_examples"] is True
    assert features["assessment"] is True
    assert client.get("/api/v1/analyses", headers=headers).json()["total"] == 0
    assert client.get("/api/v1/findings", headers=headers).json()["total"] == 0
