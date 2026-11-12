import os
import stat

import httpx
import pytest

from scripts.smoke_ssh_http import save_evidence, verify_snapshots

PATH = (
    "/api/v1/assets/00000000-0000-0000-0000-000000000001"
    "/collections/00000000-0000-0000-0000-000000000002"
)


def test_evidence_file_is_private_and_cannot_overwrite_existing_history(tmp_path):
    path = tmp_path / "evidence.json"
    save_evidence(path, {"original": True})
    original = path.read_bytes()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        save_evidence(path, {"original": False})
    assert path.read_bytes() == original


def test_tampered_evidence_cannot_send_credentials_to_another_host():
    requests = []

    def unexpected_request(request):
        requests.append(request)
        return httpx.Response(200, json={})

    with httpx.Client(
        base_url="http://127.0.0.1:8080",
        headers={"Authorization": "Bearer test-only-token"},
        transport=httpx.MockTransport(unexpected_request),
    ) as client:
        for path in ["https://other.invalid/", "//other.invalid/", PATH + "?redirect=1"]:
            with pytest.raises(RuntimeError, match="Invalid snapshot API path"):
                verify_snapshots(client, {path: {}})
    assert requests == []


def test_snapshot_verification_fails_when_persisted_result_changes():
    with httpx.Client(
        base_url="http://127.0.0.1:8080",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"value": "new"})),
    ) as client:
        with pytest.raises(RuntimeError, match="Saved response changed"):
            verify_snapshots(client, {PATH: {"value": "old"}})
        with pytest.raises(RuntimeError, match="no snapshots"):
            verify_snapshots(client, {})
