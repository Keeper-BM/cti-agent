"""Create verified SQLite backups and restore to a new, separate database file."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.core.config import get_settings


def inspect_database(path: Path) -> str:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Database foreign key check failed")
        return db.execute("SELECT version_num FROM alembic_version").fetchone()[0]


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
    with target.open("xb"):
        pass
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(target) as dst:
                src.backup(dst, pages=256, sleep=0.05)
        version = inspect_database(target)
        meta = {
            "format": "cti-sqlite-backup/1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "schema": version,
            "sha256": digest(target),
            "bytes": target.stat().st_size,
        }
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump(meta, stream, indent=2)
            stream.write("\n")
        return meta
    except Exception:
        target.unlink(missing_ok=True)
        raise


def verify(source: Path) -> dict:
    manifest = source.with_suffix(source.suffix + ".json")
    meta = json.loads(manifest.read_text(encoding="utf-8"))
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
