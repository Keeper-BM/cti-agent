"""Loopback-only SSH protocol fixture. It never runs a shell or real system commands."""

import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import paramiko

from backend.collectors.ssh_protocol import COMMANDS

APACHE = "apache2-bin\t2.4.58-1ubuntu8.1\tapache2\t2.4.58-1ubuntu8.1\tamd64\tinstalled\tok\n"
MYSQL = "mysql-server-8.0\t8.0.36-2ubuntu3\tmysql-8.0\t8.0.36-2ubuntu3\tamd64\tinstalled\tok\n"
APACHE_SERVICE = (
    "Id=apache2.service\nLoadState=loaded\nActiveState=active\nSubState=running\n"
    "UnitFileState=enabled\n"
)
MYSQL_SERVICE = (
    "Id=mysql.service\nLoadState=loaded\nActiveState=inactive\nSubState=dead\n"
    "UnitFileState=disabled\n"
)
DEFAULT_OUTPUTS = {
    "os_release": (0, 'ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n'),
    "architecture": (0, "amd64\n"),
    "packages": (0, APACHE + MYSQL),
    "apt_policy": (
        0,
        "apache2-bin:\n  Installed: 2.4.58-1ubuntu8.1\n  Candidate: 2.4.58-1ubuntu8.2\n",
    ),
    "service_apache2": (0, APACHE_SERVICE),
    "service_mysql": (0, MYSQL_SERVICE),
}


@contextmanager
def ssh_server(tmp_path, *, outputs=None, auth=True, slow=False):
    host_key = paramiko.RSAKey.generate(2048)
    user_key = paramiko.RSAKey.generate(2048)
    key_file = tmp_path / "lab_key"
    user_key.write_private_key_file(str(key_file))
    key_file.chmod(0o600)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    state = SimpleNamespace(
        host_key=host_key,
        key_file=key_file,
        port=port,
        commands=[],
        auth_calls=0,
        outputs=outputs or dict(DEFAULT_OUTPUTS),
        transports=[],
        errors=[],
        slow=slow,
    )
    stop = threading.Event()

    class Server(paramiko.ServerInterface):
        def get_allowed_auths(self, username):
            return "publickey"

        def check_auth_publickey(self, username, key):
            state.auth_calls += 1
            return (
                paramiko.AUTH_SUCCESSFUL
                if auth and username == "collector" and key == user_key
                else paramiko.AUTH_FAILED
            )

        def check_channel_request(self, kind, chanid):
            return (
                paramiko.OPEN_SUCCEEDED
                if kind == "session"
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_exec_request(self, channel, command):
            command = command.decode("utf-8")
            state.commands.append(command)
            name = next((n for n, c in COMMANDS.items() if c == command), None)
            if name is None:
                return False

            def send():
                try:
                    if state.slow:
                        stop.wait(7)
                    else:
                        time.sleep(0.02)
                    if stop.is_set():
                        return
                    code, content = state.outputs[name]
                    channel.sendall(content.encode("utf-8"))
                    if code:
                        channel.sendall_stderr(b"PRIVATE-REMOTE-ERROR-must-not-be-stored")
                    channel.send_exit_status(code)
                    channel.close()
                except (OSError, EOFError):
                    pass

            threading.Thread(target=send, daemon=True).start()
            return True

    def serve():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            transport = paramiko.Transport(conn)
            state.transports.append(transport)
            transport.add_server_key(host_key)
            try:
                transport.start_server(server=Server())
                channels = []
                while transport.is_active() and not stop.is_set():
                    channel = transport.accept(0.2)
                    if channel is not None:
                        channels.append(channel)
            except (OSError, EOFError, paramiko.SSHException):
                pass
            finally:
                transport.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        stop.set()
        listener.close()
        for transport in state.transports:
            transport.close()
        thread.join(timeout=2)
