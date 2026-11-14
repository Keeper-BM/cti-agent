import pytest

from backend.collectors.service_status import parse_service
from tests.fixtures.ssh_server import APACHE_SERVICE


@pytest.mark.parametrize(
    ("load", "active", "sub", "enabled", "expected"),
    [
        ("loaded", "active", "running", "enabled", "OBSERVED"),
        ("loaded", "inactive", "dead", "disabled", "OBSERVED"),
        ("loaded", "failed", "failed", "enabled", "OBSERVED"),
        ("masked", "inactive", "dead", "masked", "OBSERVED"),
        ("not-found", "inactive", "dead", "", "NOT_FOUND"),
        ("loaded", "activating", "start", "enabled-runtime", "OBSERVED"),
    ],
)
def test_service_observation_preserves_states_without_package_or_security_inference(
    load, active, sub, enabled, expected
):
    text = (
        f"Id=apache2.service\nLoadState={load}\nActiveState={active}\n"
        f"SubState={sub}\nUnitFileState={enabled}\n"
    )
    result = parse_service("apache2.service", 0, text)
    assert result.status == expected
    assert result.load_state == load and result.active_state == active
    assert result.sub_state == sub and result.unit_file_state == (enabled or None)
    assert result.error_code is None


@pytest.mark.parametrize("code", [1, 124, 126, 127, 137])
def test_failed_command_cannot_assert_service_is_stopped_or_absent(code):
    result = parse_service("apache2.service", code, APACHE_SERVICE)
    assert result.status == "UNKNOWN" and result.error_code == "COMMAND_FAILED"
    assert result.active_state is None and result.load_state is None


@pytest.mark.parametrize(
    "output",
    [
        "",
        APACHE_SERVICE.replace("Id=apache2.service", "Id=mysql.service"),
        APACHE_SERVICE.replace("ActiveState=active\n", ""),
        APACHE_SERVICE + "ActiveState=inactive\n",
        APACHE_SERVICE + "ExecStart=/bin/echo private-data\n",
        APACHE_SERVICE.replace("SubState=running", "SubState=bad value"),
        APACHE_SERVICE.replace("LoadState=loaded", "LoadState=not-found"),
        APACHE_SERVICE.replace("UnitFileState=enabled", "UnitFileState=" + "x" * 100),
    ],
)
def test_malformed_or_inconsistent_output_is_unknown(output):
    result = parse_service("apache2.service", 0, output)
    assert result.status == "UNKNOWN" and result.error_code == "OUTPUT_INVALID"
    assert result.active_state is None and result.unit_file_state is None
