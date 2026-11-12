import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

from scripts.postgres_backup import (
    BackupError,
    DatabaseState,
    TableDigest,
    backup,
    database_name,
    manifest_path,
    restore,
    verify,
)


class FakePostgres:
    user = database = "cti"

    def __init__(self):
        self.created, self.dropped = [], []
        self.state = DatabaseState(
            revision="0011",
            tables=[TableDigest(namespace="public", name="example", rows=1, sha256="a" * 64)],
            sequences=[],
            extensions={"plpgsql": "1.0"},
        )

    def major(self):
        return 17

    def run(self, args, *, stdout):
        stdout.write(b"PGDMP-test-content")

    @contextmanager
    def scratch_database(self):
        self.create_database("scratch")
        try:
            yield "scratch"
        finally:
            self.drop_created_database("scratch")

    def create_database(self, name):
        self.created.append(name)

    def drop_created_database(self, name):
        self.dropped.append(name)

    def load_dump(self, source, name):
        pass

    def inspect(self, name):
        return self.state


def test_private_roundtrip_and_no_overwrite(tmp_path):
    db, archive = FakePostgres(), tmp_path / "saved.dump"
    previous = os.umask(0)
    try:
        metadata = backup(db, archive)
    finally:
        os.umask(previous)
    assert verify(archive) == restore(db, archive, "restored") == metadata
    if os.name != "nt":
        assert archive.stat().st_mode & 0o777 == 0o600
        assert manifest_path(archive).stat().st_mode & 0o777 == 0o600
    assert db.dropped == ["scratch"]
    with pytest.raises(BackupError, match="already exists"):
        backup(db, archive)
    with pytest.raises(BackupError, match="differ"):
        restore(db, archive, db.database)
    assert db.created == ["scratch", "restored"]


@pytest.mark.parametrize("mode", ["bytes", "hash", "magic", "shape"])
def test_corruption_rejected_before_database_creation(tmp_path, mode):
    db, archive = FakePostgres(), tmp_path / "saved.dump"
    metadata = backup(db, archive).model_dump()
    if mode == "bytes":
        archive.write_bytes(b"PGDMP-short")
    elif mode == "hash":
        metadata["sha256"] = "0" * 64
    elif mode == "magic":
        import hashlib

        archive.write_bytes(b"other-test-content")
        metadata["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        metadata["bytes"] = archive.stat().st_size
    else:
        metadata = ["PRIVATE-SENTINEL"]
    manifest_path(archive).write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        restore(db, archive, "newdb")
    assert db.created == ["scratch"]


def test_existing_database_is_never_dropped_on_create_failure(tmp_path, monkeypatch):
    db, archive = FakePostgres(), tmp_path / "saved.dump"
    backup(db, archive)

    def already_exists(name):
        raise BackupError("existing database")

    monkeypatch.setattr(db, "create_database", already_exists)
    with pytest.raises(BackupError):
        restore(db, archive, "existing")
    assert db.dropped == ["scratch"]


@pytest.mark.parametrize("operation", ["load", "mismatch"])
def test_restore_failure_removes_only_new_database(tmp_path, monkeypatch, operation):
    db, archive = FakePostgres(), tmp_path / "saved.dump"
    backup(db, archive)
    if operation == "load":

        def fail(*args):
            raise BackupError("restore failed")

        monkeypatch.setattr(db, "load_dump", fail)
    else:
        db.state.tables[0].rows = 2
    with pytest.raises(BackupError):
        restore(db, archive, "newdb")
    assert db.dropped == ["scratch", "newdb"]


def test_failed_backup_cleans_own_files_but_preserves_competing_manifest(tmp_path, monkeypatch):
    db, archive = FakePostgres(), tmp_path / "saved.dump"

    def competing(name):
        manifest_path(archive).write_text("another operation")
        return db.state

    monkeypatch.setattr(db, "inspect", competing)
    with pytest.raises(FileExistsError):
        backup(db, archive)
    assert not archive.exists()
    assert manifest_path(archive).read_text() == "another operation"
    assert db.dropped == ["scratch"]


@pytest.mark.parametrize("value", ["postgres://host/db", "x y", "-x", "x;DROP", "x" * 64])
def test_connection_strings_and_unsafe_names_rejected(value):
    with pytest.raises(BackupError):
        database_name(value)


def test_cli_does_not_leak_invalid_manifest(tmp_path):
    archive = tmp_path / "invalid.dump"
    manifest_path(archive).write_text('["PRIVATE-SENTINEL"]')
    result = subprocess.run(
        [sys.executable, "-m", "scripts.postgres_backup", "verify", str(archive)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "PostgreSQL backup operation failed" in result.stderr
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
