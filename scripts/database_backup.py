"""Create verified SQLite backups and restore to a new, separate database file."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.core.config import get_settings


def inspect_database(path: Path) -> str:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Database foreign key check failed")
        revisions = db.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(revisions) != 1 or not isinstance(revisions[0][0], str) or not revisions[0][0]:
            raise ValueError("Database must have exactly one migration revision")
        return revisions[0][0]


def create_private_file(path: Path):
    """Create exclusively with owner-only POSIX permissions, even with a permissive umask."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup(source: Path, target: Path) -> dict:
    source, target = source.resolve(strict=True), target.absolute()
    manifest = target.with_suffix(target.suffix + ".json")
    if target.exists() or target.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise ValueError("Backup destination already exists; use a new file name")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting a database or following a destination symlink.
    with create_private_file(target):
        pass
    manifest_created = False
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, sleep=0.05)
        version = inspect_database(target)
        meta = {
            "format": "cti-sqlite-backup/1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "schema": version,
            "sha256": digest(target),
            "bytes": target.stat().st_size,
        }
        with create_private_file(manifest) as stream:
            manifest_created = True
            json.dump(meta, stream, indent=2)
            stream.write("\n")
        return meta
    except Exception:
        if manifest_created:
            manifest.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


def verify(source: Path) -> dict:
    manifest = source.with_suffix(source.suffix + ".json")
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    # Validate untrusted JSON before dereferencing it or reading the database.
    if (
        not isinstance(meta, dict)
        or not isinstance(meta.get("schema"), str)
        or not meta["schema"]
        or not isinstance(meta.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]) is None
        or type(meta.get("bytes")) is not int
        or meta["bytes"] <= 0
    ):
        raise ValueError("Backup manifest fields are invalid")
    if (
        meta.get("format") != "cti-sqlite-backup/1.0"
        or meta.get("sha256") != digest(source)
        or meta.get("bytes") != source.stat().st_size
    ):
        raise ValueError("Backup manifest or digest does not match")
    if inspect_database(source) != meta.get("schema"):
        raise ValueError("Backup schema does not match the manifest")
    return meta


def restore(source: Path, target: Path) -> dict:
    verify(source)
    return backup(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("destination", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("backup", type=Path)
    clone = sub.add_parser("restore")
    clone.add_argument("backup", type=Path)
    clone.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "create":
            url = make_url(get_settings().database_url)
            if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
                raise ValueError(
                    "Use pg_dump for PostgreSQL; this command requires file-based SQLite"
                )
            meta = backup(Path(url.database), args.destination)
        elif args.action == "verify":
            meta = verify(args.backup)
        else:
            meta = restore(args.backup, args.destination)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(
            1, "Backup operation failed. Check paths, permissions, database and manifest.\n"
        )
    print(
        f"Completed {args.action}: schema={meta['schema']} bytes={meta['bytes']} "
        f"sha256={meta['sha256']}"
    )


if __name__ == "__main__":
    main()
