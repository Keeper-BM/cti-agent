import socket

import pytest

from scripts.dev import check_port, run_lock


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
