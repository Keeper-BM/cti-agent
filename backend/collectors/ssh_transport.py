"""Pinned host-key SSH transport with bounded fixed-command collection."""

import hmac
import socket
import time
from threading import Event, Timer

import paramiko

from backend.collectors.ssh_config import check_target, key_path
from backend.collectors.ssh_protocol import COMMANDS, MAX_OUTPUT_BYTES, CommandResult, parse_os
from backend.core.errors import AppError


class FingerprintPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        if not hmac.compare_digest(key.fingerprint, self.expected):
            raise AppError(
                "SSH_HOST_KEY_MISMATCH",
                "서버 호스트 키가 등록한 지문과 다릅니다. 접속을 중단했습니다.",
                409,
            )


def collect_ssh(profile, settings) -> list[CommandResult]:
    return run_ssh_commands(profile, settings, COMMANDS)


def run_ssh_commands(profile, settings, commands, inputs=None) -> list[CommandResult]:
    """Internal fixed-command transport. API callers cannot supply command strings."""
    check_target(settings, profile.host, profile.port)
    path = key_path(settings, profile.key_alias)
    try:
        # Read keys only from the configured directory, never from request-supplied paths.
        key = paramiko.PKey.from_path(path, settings.ssh_key_password.get_secret_value() or None)
    except (OSError, ValueError, paramiko.SSHException):
        raise AppError(
            "SSH_KEY_INVALID", "인증키 형식·읽기 권한·암호 설정을 확인하세요.", 409
        ) from None
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(FingerprintPolicy(profile.host_fingerprint))
    deadline = time.monotonic() + settings.ssh_timeout_seconds
    timed_out = Event()
    sock = socket.socket(
        socket.AF_INET6 if ":" in profile.host else socket.AF_INET, socket.SOCK_STREAM
    )
    sock.settimeout(min(10, settings.ssh_timeout_seconds))

    def expire():
        timed_out.set()
        sock.close()
        client.close()

    timer = Timer(settings.ssh_timeout_seconds, expire)
    timer.daemon = True
    timer.start()
    results, total = [], 0
    try:
        sock.connect((profile.host, profile.port))
        client.connect(
            hostname=profile.host,
            port=profile.port,
            username=profile.username,
            pkey=key,
            sock=sock,
            look_for_keys=False,
            allow_agent=False,
            timeout=min(10, settings.ssh_timeout_seconds),
            auth_timeout=min(20, settings.ssh_timeout_seconds),
            banner_timeout=min(20, settings.ssh_timeout_seconds),
            channel_timeout=min(20, settings.ssh_timeout_seconds),
        )
        for name, command in commands.items():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            transport = client.get_transport()
            if transport is None:
                raise EOFError()
            channel = transport.open_session(timeout=min(remaining, 20))
            try:
                channel.settimeout(min(remaining, 20))
                channel.exec_command(command)
                if inputs and name in inputs:
                    data = inputs[name]
                    if len(data) > 512 * 1024:
                        raise AppError(
                            "SSH_INPUT_LIMIT", "검사 입력 크기가 제한을 초과합니다.", 422
                        )
                    channel.sendall(data)
                channel.shutdown_write()
                output = bytearray()
                stderr_present = False
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    if channel.recv_ready():
                        chunk = channel.recv(32768)
                        output.extend(chunk)
                        total += len(chunk)
                    if channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(32768)
                        stderr_present = stderr_present or bool(chunk)
                        total += len(chunk)
                    if total > MAX_OUTPUT_BYTES:
                        raise AppError(
                            "SSH_OUTPUT_LIMIT", "수집 출력이 2 MiB 제한을 초과했습니다.", 502
                        )
                    if (
                        channel.exit_status_ready()
                        and not channel.recv_ready()
                        and not channel.recv_stderr_ready()
                    ):
                        break
                    if channel.closed and not channel.exit_status_ready():
                        raise AppError(
                            "SSH_CONNECTION_LOST", "수집 중 SSH 연결이 종료되었습니다.", 502
                        )
                    time.sleep(0.01)
                exit_code = channel.recv_exit_status()
                if exit_code < 0:
                    raise AppError(
                        "SSH_CONNECTION_LOST", "명령 종료 상태를 확인하지 못했습니다.", 502
                    )
                try:
                    stdout = output.decode("utf-8")
                except UnicodeDecodeError:
                    raise AppError(
                        "SSH_OUTPUT_INVALID", "서버 출력이 UTF-8 형식이 아닙니다.", 502
                    ) from None
                results.append(
                    CommandResult(
                        name=name, exit_code=exit_code, stdout=stdout, stderr_present=stderr_present
                    )
                )
                if name == "os_release":
                    if exit_code != 0:
                        raise AppError(
                            "SSH_OS_READ_FAILED",
                            "OS 정보를 읽지 못했습니다. 계정 권한을 확인하세요.",
                            502,
                        )
                    parse_os(stdout)
            finally:
                channel.close()
        return results
    except paramiko.AuthenticationException:
        raise AppError(
            "SSH_AUTH_FAILED", "SSH 사용자와 인증키의 접속 권한을 확인하세요.", 502
        ) from None
    except TimeoutError:
        raise AppError(
            "SSH_TIMEOUT", "SSH 연결 또는 조회 제한 시간이 초과되었습니다.", 502
        ) from None
    except (OSError, paramiko.SSHException, EOFError):
        if timed_out.is_set():
            raise AppError("SSH_TIMEOUT", "SSH 수집 제한 시간이 초과되었습니다.", 502) from None
        raise AppError(
            "SSH_CONNECTION_FAILED", "SSH 서버에 연결하거나 조회하지 못했습니다.", 502
        ) from None
    finally:
        timer.cancel()
        client.close()
        sock.close()
