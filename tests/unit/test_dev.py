import socket
from types import SimpleNamespace

import pytest

from scripts.dev import check_port, run_lock, uv_commands


def test_a_busy_port_has_a_specific_diagnostic():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="busy"):
            check_port(listener.getsockname()[1])


def test_checkout_lock_rejects_a_second_run_and_is_reusable_after_release(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already running"), run_lock(tmp_path):
            pass
    with run_lock(tmp_path):
        pass


@pytest.mark.parametrize("extra", [None, "dense", "dense-cuda"])
@pytest.mark.parametrize("langchain", [False, True])
def test_launcher_keeps_the_requested_retrieval_extra_for_every_uv_command(extra, langchain):
    sync, run = uv_commands("uv", extra, langchain)
    selection = ["--extra", extra] if extra else []
    if langchain:
        selection += ["--extra", "langchain"]
    assert sync == ["uv", "sync", "--frozen", *selection]
    assert run == ["uv", "run", "--frozen", *selection]


@pytest.mark.parametrize(
    ("mode", "missing"),
    [("dense", "numpy"), ("langchain", "numpy"), ("langchain", "langchain_core")],
)
def test_retrieval_configuration_reports_missing_dependencies(monkeypatch, capsys, mode, missing):
    from scripts import check_env

    monkeypatch.setattr(
        check_env,
        "get_settings",
        lambda: SimpleNamespace(database_url="sqlite:///test.db", retrieval_mode=mode),
    )
    monkeypatch.setattr(
        check_env.importlib.util, "find_spec", lambda name: None if name == missing else object()
    )

    assert check_env.main() == 1
    assert f"{mode} retrieval dependencies are missing" in capsys.readouterr().err
