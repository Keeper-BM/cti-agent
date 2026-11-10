"""Server-side target and credential restrictions; never discover arbitrary hosts."""

import ipaddress
import os
import re
from pathlib import Path

from backend.core.errors import AppError

KEY_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}"


def allowed_targets(settings) -> set[tuple[str, int]]:
    result = set()
    for value in settings.ssh_allowed_targets.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            host, port = value.rsplit(":", 1)
            host = host.removeprefix("[").removesuffix("]")
            address = ipaddress.ip_address(host)
            if (
                address.is_unspecified
                or address.is_multicast
                or address.is_link_local
                or "%" in host
            ):
                raise ValueError()
            port = int(port)
            if not 1 <= port <= 65535:
                raise ValueError()
            result.add((str(address), port))
        except ValueError:
            raise AppError(
                "SSH_CONFIGURATION_INVALID", "서버의 SSH_ALLOWED_TARGETS 설정을 확인하세요.", 409
            ) from None
    return result


def check_target(settings, host: str, port: int):
    if (host, port) not in allowed_targets(settings):
        raise AppError("SSH_TARGET_NOT_ALLOWED", "서버 설정에서 허용한 IP·포트가 아닙니다.", 409)


def key_path(settings, alias: str) -> Path:
    if not re.fullmatch(KEY_PATTERN, alias):
        raise AppError("SSH_KEY_UNAVAILABLE", "등록된 인증키 이름을 선택하세요.", 409)
    root = Path(settings.ssh_key_directory).resolve()
    path = root / alias
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError()
        if not 0 < path.stat().st_size <= 65536:
            raise ValueError()
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ValueError()
    except (OSError, ValueError):
        raise AppError(
            "SSH_KEY_UNAVAILABLE", "서버에서 인증키 파일을 읽을 수 없습니다.", 409
        ) from None
    return path


def key_aliases(settings) -> list[str]:
    try:
        root = Path(settings.ssh_key_directory).resolve()
        candidates = sorted(
            p.name
            for p in root.iterdir()
            if re.fullmatch(KEY_PATTERN, p.name) and not p.name.endswith((".pub", ".json", ".txt"))
        )
    except OSError:
        return []
    valid = []
    for name in candidates:
        try:
            key_path(settings, name)
            valid.append(name)
        except AppError:
            pass
    return valid[:50]
