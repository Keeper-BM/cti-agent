import os
import runpy
import shlex
import subprocess
import sys

import pytest

from backend.collectors.ssh_protocol import COMMANDS
from scripts.render_ssh_guard import render_guard


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "id",
        "sudo id",
        "sftp",
        COMMANDS["os_release"] + "; id",
        COMMANDS["os_release"] + "\nid",
        " " + COMMANDS["os_release"],
        COMMANDS["service_mysql"].replace("mysql.service", "ssh.service"),
    ],
)
def test_guard_rejects_shell_and_modified_commands_without_echoing_input(tmp_path, command):
    guard = tmp_path / "guard.py"
    guard.write_text(render_guard(), encoding="utf-8")
    # Keep Windows' process bootstrap variables; -I isolates Python itself.
    env = {key: value for key, value in os.environ.items() if key != "SSH_ORIGINAL_COMMAND"}
    if command is not None:
        env["SSH_ORIGINAL_COMMAND"] = command
    result = subprocess.run(
        [sys.executable, "-I", str(guard)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 126
    assert result.stdout == ""
    assert result.stderr == "Only fixed CTI read commands are allowed\n"


@pytest.mark.parametrize("command", COMMANDS.values())
def test_exact_commands_exec_without_a_shell_or_inherited_environment(
    tmp_path, monkeypatch, command
):
    guard = tmp_path / "guard.py"
    guard.write_text(render_guard(), encoding="utf-8")
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", command)
    monkeypatch.setenv("PRIVATE_SENTINEL", "must-not-reach-child")
    calls = []

    def execve(executable, args, env):
        calls.append((executable, args, env))
        raise SystemExit(0)

    monkeypatch.setattr(os, "execve", execve)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(guard), run_name="__main__")
    assert result.value.code == 0
    assert calls == [("/usr/bin/env", shlex.split(command), {})]


def test_file_verification_is_explicit_and_only_allows_the_bundled_program(tmp_path, monkeypatch):
    from backend.verification.service import HASHER

    guard = tmp_path / "guard.py"
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", HASHER)
    guard.write_text(render_guard(), encoding="utf-8")
    with pytest.raises(SystemExit) as denied:
        runpy.run_path(str(guard), run_name="__main__")
    assert denied.value.code == 126

    calls = []

    def execve(executable, args, env):
        calls.append((executable, args, env))
        raise SystemExit(0)

    monkeypatch.setattr(os, "execve", execve)
    guard.write_text(render_guard(include_file_verification=True), encoding="utf-8")
    with pytest.raises(SystemExit) as allowed:
        runpy.run_path(str(guard), run_name="__main__")
    assert allowed.value.code == 0
    assert calls == [("/usr/bin/env", shlex.split(HASHER), {})]
