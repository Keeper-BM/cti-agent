"""Create or repair local configuration while preserving valid existing values."""

from __future__ import annotations

import math
import os
import re
import secrets
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
SECRET_FIELDS = {"DEV_API_TOKEN": 32, "POSTGRES_PASSWORD": 24}


def read_values(content: str) -> dict[str, str]:
    values = {}
    for number, line in enumerate(content.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = ASSIGNMENT.match(line)
        if not match:
            raise ValueError(f"Invalid .env assignment on line {number}")
        key, raw = match.groups()
        if key in values:
            raise ValueError(f"Duplicate .env field: {key}")
        try:
            if raw.lstrip().startswith(("'", '"')):
                value = " ".join(shlex.split(raw, comments=True, posix=True))
            else:
                value = re.sub(r"\s+#.*$", "", raw).strip()
        except ValueError:
            raise ValueError(f"Invalid quoting for {key}") from None
        values[key] = value
    return values


def validate_values(values: dict[str, str]) -> None:
    if values.get("APP_ENV") != "development":
        raise ValueError("APP_ENV must be development")
    if len(values.get("DEV_API_TOKEN", "")) < 32:
        raise ValueError("DEV_API_TOKEN must contain at least 32 characters")
    for key in ("DATABASE_URL", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        if not values.get(key):
            raise ValueError(f"{key} must not be empty")
    try:
        port = int(values.get("WEB_PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("WEB_PORT must be an integer between 1 and 65535") from None
    try:
        poll = float(values.get("WORKER_POLL_SECONDS", "2"))
        if not math.isfinite(poll) or not 0.1 <= poll <= 60:
            raise ValueError
    except ValueError:
        raise ValueError("WORKER_POLL_SECONDS must be between 0.1 and 60") from None


def initialize(root: Path = ROOT) -> bool:
    target = root / ".env"
    template = (root / ".env.example").read_text(encoding="utf-8")
    content = target.read_text(encoding="utf-8") if target.exists() else template
    existing = read_values(content)
    defaults = read_values(template)
    additions = {key: value for key, value in defaults.items() if key not in existing}
    values = {**existing, **additions}
    replacements = {}
    for key, size in SECRET_FIELDS.items():
        if not values.get(key):
            values[key] = secrets.token_urlsafe(size)
            if key in existing:
                replacements[key] = values[key]
            else:
                additions[key] = values[key]
    validate_values(values)
    lines = []
    for line in content.splitlines():
        match = ASSIGNMENT.match(line)
        key = match.group(1) if match else None
        lines.append(f"{key}={replacements[key]}" if key in replacements else line)
    lines.extend(f"{key}={value}" for key, value in additions.items())
    updated = "\n".join(lines) + "\n"
    (root / ".data").mkdir(exist_ok=True)
    (root / ".data" / "ssh-keys").mkdir(exist_ok=True)
    if target.exists() and not replacements and not additions:
        print("Validated .env; existing values preserved.")
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as f:
            temporary = Path(f.name)
            os.chmod(temporary, 0o600)
            f.write(updated)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print("Prepared .env; valid values preserved and empty secrets generated.")
    print("Read DEV_API_TOKEN from .env locally to connect the development UI.")
    return True


def main() -> int:
    try:
        initialize()
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
