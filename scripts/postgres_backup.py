"""Verified logical backups for the reference Compose PostgreSQL service.

Uses the DB container's matching pg_dump/pg_restore clients. Backup creation tests
the dump in a temporary database; restoration only creates a new named database.
Credentials stay in the existing container environment, never in CLI arguments.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scripts.database_backup import create_private_file, digest


class BackupError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TableDigest(StrictModel):
    namespace: str
    name: str
    rows: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SequenceState(StrictModel):
    namespace: str
    name: str
    last_value: int
    is_called: bool


class DatabaseState(StrictModel):
    revision: str = Field(min_length=1, max_length=100)
    tables: list[TableDigest] = Field(min_length=1)
    sequences: list[SequenceState]
    extensions: dict[str, str]


class Manifest(StrictModel):
    format: Literal["cti-postgres-backup/1"]
    created_at: str
    server_major: int = Field(ge=17)
    bytes: int = Field(gt=5)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database: DatabaseState


def database_name(value):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", value):
        raise BackupError("Use a simple PostgreSQL database/user name of at most 63 characters")
    return value


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


class ComposePostgres:
    def __init__(self, project, env_file, *, database=None, timeout=300):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
            raise BackupError("Invalid Compose project name")
        self.compose = ["docker", "compose", "-p", project, "--env-file", str(env_file)]
        self.timeout = timeout
        values = self.run(["printenv", "POSTGRES_USER", "POSTGRES_DB"]).decode().splitlines()
        if len(values) != 2:
            raise BackupError("The db service must define POSTGRES_USER and POSTGRES_DB")
        self.user = database_name(values[0])
        self.database = database_name(database or values[1])

    def run(self, args, *, input=None, stdin=None, stdout=None):
        try:
            result = subprocess.run(
                [*self.compose, "exec", "-T", "db", *args],
                input=input,
                stdin=stdin,
                stdout=stdout if stdout is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise BackupError(f"{args[0]} exceeded the operation timeout") from None
        if result.returncode:
            # PostgreSQL errors may include data or connection details; do not echo stderr.
            raise BackupError(f"{args[0]} failed (exit {result.returncode})")
        return result.stdout

    def sql(self, database, query, *, stdout=None):
        return self.run(
            [
                "psql",
                "-X",
                "-w",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                self.user,
                "-d",
                database_name(database),
                "-f",
                "-",
            ],
            input=("SET timezone='UTC'; SET extra_float_digits=3;\n" + query).encode(),
            stdout=stdout,
        )

    def major(self):
        return int(self.sql(self.database, "SHOW server_version_num;").strip()) // 10000

    def create_database(self, name):
        self.run(
            [
                "createdb",
                "-w",
                "-U",
                self.user,
                "--maintenance-db=postgres",
                "--template=template0",
                "--encoding=UTF8",
                "--",
                database_name(name),
            ]
        )

    def drop_created_database(self, name):
        # Only callers that successfully created this database may invoke cleanup.
        self.run(
            [
                "dropdb",
                "-w",
                "-U",
                self.user,
                "--maintenance-db=postgres",
                "--force",
                "--",
                database_name(name),
            ]
        )

    def load_dump(self, source, name):
        with source.open("rb") as stream:
            self.run(
                [
                    "pg_restore",
                    "-w",
                    "-U",
                    self.user,
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    database_name(name),
                ],
                stdin=stream,
            )

    @contextmanager
    def scratch_database(self):
        name = "cti_backup_verify_" + uuid4().hex
        self.create_database(name)
        try:
            yield name
        finally:
            self.drop_created_database(name)

    def inspect(self, name):
        revisions = self.sql(name, "SELECT version_num FROM public.alembic_version;")
        revisions = revisions.decode().splitlines()
        if len(revisions) != 1 or not revisions[0]:
            raise BackupError("Database must contain exactly one Alembic revision")
        relations = json.loads(
            self.sql(
                name,
                """
            SELECT COALESCE(json_agg(json_build_array(n.nspname,c.relname,c.relkind)
                ORDER BY n.nspname,c.relname),'[]'::json)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE left(n.nspname,3) <> 'pg_' AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r','p','S');
        """,
            )
        )
        tables, sequences = [], []
        for namespace, table, kind in relations:
            identifier = quoted(namespace) + "." + quoted(table)
            if kind == "S":
                value = json.loads(
                    self.sql(
                        name,
                        "SELECT row_to_json(s) FROM "
                        f"(SELECT last_value,is_called FROM {identifier}) s;",
                    )
                )
                sequences.append(SequenceState(namespace=namespace, name=table, **value))
                continue
            # Sort fixed-size row hashes in PostgreSQL and stream them to a private temp file.
            # This handles duplicates and large JSON/report rows without loading them in Python.
            with tempfile.TemporaryFile() as rows:
                self.sql(
                    name,
                    f"""
                    COPY (SELECT encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex')
                          FROM {identifier} t ORDER BY 1) TO STDOUT;
                """,
                    stdout=rows,
                )
                rows.seek(0)
                checksum, count = hashlib.sha256(), 0
                for line in rows:
                    if not re.fullmatch(rb"[0-9a-f]{64}\n", line):
                        raise BackupError("Invalid row digest output")
                    checksum.update(line)
                    count += 1
            tables.append(
                TableDigest(
                    namespace=namespace, name=table, rows=count, sha256=checksum.hexdigest()
                )
            )
        extensions = json.loads(
            self.sql(
                name,
                """
            SELECT COALESCE(json_object_agg(extname,extversion),'{}'::json) FROM pg_extension;
        """,
            )
        )
        return DatabaseState(
            revision=revisions[0], tables=tables, sequences=sequences, extensions=extensions
        )


def manifest_path(path):
    return path.with_suffix(path.suffix + ".json")


def verify(source: Path) -> Manifest:
    metadata = Manifest.model_validate_json(manifest_path(source).read_text(encoding="utf-8"))
    if source.stat().st_size != metadata.bytes or digest(source) != metadata.sha256:
        raise BackupError("Backup size or SHA-256 differs from the manifest")
    with source.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise BackupError("Expected a custom-format PostgreSQL archive")
    return metadata


def backup(db: ComposePostgres, target: Path) -> Manifest:
    target = target.absolute()
    manifest = manifest_path(target)
    if any(p.exists() or p.is_symlink() for p in (target, manifest)):
        raise BackupError("Backup destination already exists; use a new file name")
    major = db.major()
    if major < 17:
        raise BackupError("This tool requires PostgreSQL 17 or newer")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    manifest_created = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            db.run(
                [
                    "pg_dump",
                    "-w",
                    "-U",
                    db.user,
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    db.database,
                ],
                stdout=stream,
            )
        # Derive the manifest from the consistent dump, not a changing live database.
        with db.scratch_database() as scratch:
            db.load_dump(target, scratch)
            state = db.inspect(scratch)
        metadata = Manifest(
            format="cti-postgres-backup/1",
            created_at=datetime.now(UTC).isoformat(),
            server_major=major,
            bytes=target.stat().st_size,
            sha256=digest(target),
            database=state,
        )
        with create_private_file(manifest) as stream:
            manifest_created = True
            stream.write(metadata.model_dump_json(indent=2) + "\n")
        return verify(target)
    except BaseException:
        if manifest_created:
            manifest.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


def restore(db: ComposePostgres, source: Path, target: str) -> Manifest:
    metadata = verify(source)
    target = database_name(target)
    if target == db.database:
        raise BackupError("Restore target must differ from the configured source database")
    if metadata.server_major != db.major():
        raise BackupError("Restore requires the same PostgreSQL major version")
    # CREATE fails for an existing DB. Do not enter cleanup until it has succeeded.
    db.create_database(target)
    try:
        db.load_dump(source, target)
        if db.inspect(target) != metadata.database:
            raise BackupError("Restored schema revision, table contents or sequences differ")
    except BaseException:
        db.drop_created_database(target)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "restore", "verify"):
        item = sub.add_parser(action)
        item.add_argument("archive", type=Path)
        if action != "verify":
            item.add_argument("--project-name", required=True)
            item.add_argument("--env-file", type=Path, required=True)
            item.add_argument("--database", help="Source database; defaults to POSTGRES_DB")
            item.add_argument("--timeout", type=int, default=300)
        if action == "restore":
            item.add_argument("--target-db", required=True)
    args = parser.parse_args()
    try:
        if args.action == "verify":
            metadata = verify(args.archive)
        else:
            if not 1 <= args.timeout <= 3600:
                raise BackupError("Timeout must be 1 to 3600 seconds")
            if args.action == "restore":
                verify(args.archive)  # Reject invalid archives before contacting Docker/DB.
            db = ComposePostgres(
                args.project_name, args.env_file, database=args.database, timeout=args.timeout
            )
            metadata = (
                backup(db, args.archive)
                if args.action == "create"
                else restore(db, args.archive, args.target_db)
            )
    except (OSError, ValueError, ValidationError, subprocess.SubprocessError):
        parser.exit(
            1,
            "PostgreSQL backup operation failed. Check service, permissions, "
            "new destination and trusted backup manifest. No existing DB is overwritten.\n",
        )
    print(
        f"Completed {args.action}: revision={metadata.database.revision} "
        f"tables={len(metadata.database.tables)} bytes={metadata.bytes} sha256={metadata.sha256}"
    )


if __name__ == "__main__":
    main()
