import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.init_env import initialize, read_values

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_root(tmp_path):
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    return tmp_path


def test_copied_template_is_repaired_and_existing_secrets_are_preserved(config_root):
    target = config_root / ".env"
    shutil.copy(config_root / ".env.example", target)
    assert initialize(config_root)
    first = target.read_text()
    values = read_values(first)
    assert len(values["DEV_API_TOKEN"]) >= 32
    assert values["POSTGRES_PASSWORD"]
    assert not initialize(config_root)
    assert target.read_text() == first


def test_missing_fields_are_added_without_changing_a_quoted_token(config_root):
    token = "test-token-with-at-least-32-characters"
    target = config_root / ".env"
    target.write_text(f"# existing configuration\nDEV_API_TOKEN='{token}' # keep\n")
    initialize(config_root)
    assert f"DEV_API_TOKEN='{token}' # keep" in target.read_text()
    assert read_values(target.read_text())["DEV_API_TOKEN"] == token


def test_hash_inside_an_unquoted_token_is_preserved(config_root):
    token = "synthetic-token-with-32-characters#literal-suffix"
    target = config_root / ".env"
    target.write_text(f"DEV_API_TOKEN={token} # trailing comment\n")
    initialize(config_root)
    assert read_values(target.read_text())["DEV_API_TOKEN"] == token


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DEV_API_TOKEN", "invalid-private-token"),
        ("WEB_PORT", "70000"),
        ("WORKER_POLL_SECONDS", "nan"),
        ("APP_ENV", "production"),
        ("DATABASE_URL", ""),
    ],
)
def test_invalid_settings_fail_without_rewriting_or_echoing_values(config_root, field, value):
    target = config_root / ".env"
    target.write_text((config_root / ".env.example").read_text())
    initialize(config_root)
    before = target.read_text()
    lines = [
        f"{field}={value}" if line.startswith(f"{field}=") else line for line in before.splitlines()
    ]
    invalid = "\n".join(lines) + "\n"
    target.write_text(invalid)
    with pytest.raises(ValueError, match=field) as error:
        initialize(config_root)
    assert value not in str(error.value) if value else True
    assert target.read_text() == invalid


def test_initializer_cli_reports_a_nonzero_exit_for_invalid_existing_config(config_root):
    (config_root / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "init_env.py", config_root / "scripts" / "init_env.py")
    (config_root / ".env").write_text("DEV_API_TOKEN=too-short\n")
    result = subprocess.run(
        [sys.executable, "scripts/init_env.py"], cwd=config_root, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "DEV_API_TOKEN" in result.stderr
    assert "too-short" not in result.stdout + result.stderr
