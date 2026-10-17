import logging


def test_unhandled_error_logs_location_and_request_id_without_secret_values(client, caplog):
    secret = "SENTINEL-PRIVATE-DATABASE-CREDENTIAL"

    @client.app.get("/test-unhandled-error")
    def trigger_failure():
        raise RuntimeError(f"private URL and input: {secret}")

    with caplog.at_level(logging.ERROR, logger="backend.api.main"):
        response = client.get("/test-unhandled-error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    request_id = response.json()["error"]["request_id"]
    assert response.headers["x-request-id"] == request_id
    assert request_id in caplog.text
    assert "builtins.RuntimeError" in caplog.text
    assert "trigger_failure" in caplog.text
    assert "test_diagnostics.py:" in caplog.text
    assert secret not in caplog.text + response.text
