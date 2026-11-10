from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api.schemas.collections import SSHProfileInput
from backend.collectors.ssh_config import allowed_targets, key_path
from backend.collectors.ssh_protocol import COMMANDS, CommandResult, make_inventory, parse_os
from backend.collectors.ssh_transport import collect_ssh
from backend.core.config import Settings
from backend.core.errors import AppError
from tests.fixtures.ssh_server import APACHE, DEFAULT_OUTPUTS, ssh_server


def config(tmp_path, port=2222):
    return Settings(
        _env_file=None,
        dev_api_token="x" * 32,
        ssh_allowed_targets=f"127.0.0.1:{port}",
        ssh_key_directory=str(tmp_path),
        ssh_timeout_seconds=5,
    )


def profile(server):
    return SimpleNamespace(
        host="127.0.0.1",
        port=server.port,
        username="collector",
        key_alias=server.key_file.name,
        host_fingerprint=server.host_key.fingerprint,
    )


def make(outputs=None):
    outputs = outputs or DEFAULT_OUTPUTS
    return make_inventory(
        uuid4(),
        str(uuid4()),
        [CommandResult(name=n, exit_code=c, stdout=t) for n, (c, t) in outputs.items()],
        "SHA256:" + "x" * 43,
    )


def test_full_package_source_versions_and_origin_remain_separate():
    inventory, evidence = make()
    assert inventory.collection_method == "SSH" and inventory.collection_status == "COMPLETE"
    assert inventory.coverage.package_list_complete and not inventory.is_synthetic
    assert inventory.packages[0].source_name == "apache2"
    assert inventory.packages[1].source_name == "mysql-8.0"
    assert all(p.origin_status == "UNKNOWN" for p in inventory.packages)
    assert evidence.origin_verification == "NOT_VERIFIED"


def test_partial_output_and_optional_command_failures():
    outputs = dict(DEFAULT_OUTPUTS)
    outputs["packages"] = (1, APACHE + "not\ta\tvalid\trow\n")
    outputs["architecture"] = (1, "")
    outputs["apt_policy"] = (1, "")
    inventory, evidence = make(outputs)
    assert len(inventory.packages) == 1
    assert inventory.collection_status == "PARTIAL" and not inventory.coverage.package_list_complete
    assert "os.architecture" in inventory.coverage.missing_fields
    assert len(evidence.warnings) >= 3


def test_optional_apt_timeout_keeps_complete_package_list_without_verifying_origin():
    inventory, evidence = make({**DEFAULT_OUTPUTS, "apt_policy": (124, "")})
    assert inventory.coverage.package_list_complete
    assert inventory.collection_status == "COMPLETE"
    assert all(p.origin_status == "UNKNOWN" for p in inventory.packages)
    assert any("APT" in warning for warning in evidence.warnings)


@pytest.mark.parametrize(
    "change",
    [
        {"os_release": (0, 'ID=debian\nVERSION_ID="12"\n')},
        {"os_release": (0, 'ID=ubuntu\nVERSION_ID="26.04"\n')},
        {"os_release": (1, "")},
        {"packages": (2, "")},
        {"packages": (0, APACHE + APACHE)},
    ],
)
def test_unusable_inputs_fail_without_inventory(change):
    with pytest.raises(AppError):
        make({**DEFAULT_OUTPUTS, **change})


def test_os_file_is_data_not_shell_and_apt_credentials_are_redacted():
    os_info = parse_os('ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="$(rm everything)"\n')
    assert os_info.version_id == "22.04"
    _, evidence = make(
        {**DEFAULT_OUTPUTS, "apt_policy": (0, "https://user:private-password@repo.invalid/ubuntu")}
    )
    assert "private-password" not in evidence.model_dump_json()
    assert "REDACTED" in evidence.commands[-1].stdout


@pytest.mark.parametrize(
    "host",
    ["example.com", "169.254.169.254", "0.0.0.0", "224.0.0.1", "fe80::1%eth0", "127.0.0.1;whoami"],
)
def test_profile_rejects_hostname_and_special_addresses(host):
    with pytest.raises(ValueError):
        SSHProfileInput(
            host=host, username="collector", key_alias="key", host_fingerprint="SHA256:" + "x" * 43
        )


def test_key_path_and_target_boundaries(tmp_path):
    settings = config(tmp_path)
    assert allowed_targets(settings) == {("127.0.0.1", 2222)}
    for alias in ["../key", "a/b", "C:\\secret", "missing"]:
        with pytest.raises(AppError):
            key_path(settings, alias)
    settings.ssh_allowed_targets = "example.com:22"
    with pytest.raises(AppError):
        allowed_targets(settings)


def test_real_loopback_ssh_checks_host_key_and_runs_only_fixed_commands(tmp_path):
    with ssh_server(tmp_path) as server:
        results = collect_ssh(profile(server), config(tmp_path, server.port))
        inventory, _ = make_inventory(uuid4(), str(uuid4()), results, server.host_key.fingerprint)
        assert len(inventory.packages) == 2 and server.commands == list(COMMANDS.values())
        assert server.auth_calls == 1


def test_host_key_mismatch_stops_before_authentication(tmp_path):
    with ssh_server(tmp_path) as server:
        target = profile(server)
        target.host_fingerprint = "SHA256:" + "x" * 43
        with pytest.raises(AppError) as failure:
            collect_ssh(target, config(tmp_path, server.port))
        assert failure.value.code == "SSH_HOST_KEY_MISMATCH"
        assert server.commands == [] and server.auth_calls == 0


def test_authentication_failure_does_not_run_commands(tmp_path):
    with ssh_server(tmp_path, auth=False) as server:
        with pytest.raises(AppError) as failure:
            collect_ssh(profile(server), config(tmp_path, server.port))
        assert failure.value.code == "SSH_AUTH_FAILED" and not server.commands


def test_command_timeout_and_size_limits(tmp_path, monkeypatch):
    with ssh_server(tmp_path, slow=True) as server:
        with pytest.raises(AppError) as failure:
            collect_ssh(profile(server), config(tmp_path, server.port))
        assert failure.value.code == "SSH_TIMEOUT"
    monkeypatch.setattr("backend.collectors.ssh_transport.MAX_OUTPUT_BYTES", 10)
    with ssh_server(tmp_path) as server:
        with pytest.raises(AppError) as failure:
            collect_ssh(profile(server), config(tmp_path, server.port))
        assert failure.value.code == "SSH_OUTPUT_LIMIT"
