import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts.database_backup import backup, inspect_database, restore, verify


def test_backup_restore_preserves_data_and_rejects_overwrite_or_tamper(engine, tmp_path):
    with engine.begin() as db:
        db.execute(text("CREATE TABLE backup_example (value TEXT)"))
        db.execute(text("INSERT INTO backup_example VALUES ('preserved')"))
    target = tmp_path / "saved.db"
    restored = tmp_path / "restored.db"
    metadata = backup(Path(engine.url.database), target)
    assert verify(target) == metadata
    restore(target, restored)
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT value FROM backup_example").fetchone()[0] == "preserved"
    with pytest.raises(ValueError):
        restore(target, restored)
    with pytest.raises(ValueError):
        backup(target, target)
    manifest = target.with_suffix(".db.json")
    bad = json.loads(manifest.read_text())
    bad["sha256"] = "0" * 64
    manifest.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        verify(target)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions; Windows requires directory ACLs")
def test_backup_and_restore_are_private_with_permissive_umask(engine, tmp_path):
    target = tmp_path / "private.db"
    restored = tmp_path / "restored.db"
    previous = os.umask(0)
    try:
        backup(Path(engine.url.database), target)
        restore(target, restored)
    finally:
        os.umask(previous)
    for path in (target, restored):
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.with_suffix(".db.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("metadata", [None, [], "private-input", 42, {}, {"bytes": True}])
def test_invalid_manifest_shape_is_a_controlled_error(tmp_path, metadata):
    target = tmp_path / "invalid.db"
    target.with_suffix(".db.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest fields"):
        verify(target)


def test_manifest_failure_removes_partial_files_and_allows_retry(engine, tmp_path, monkeypatch):
    target = tmp_path / "retry.db"
    original_dump = json.dump

    def fail_write(value, stream, **kwargs):
        stream.write('{"format":')
        raise OSError("simulated disk full")

    monkeypatch.setattr("scripts.database_backup.json.dump", fail_write)
    with pytest.raises(OSError):
        backup(Path(engine.url.database), target)
    assert not target.exists()
    assert not target.with_suffix(".db.json").exists()
    monkeypatch.setattr("scripts.database_backup.json.dump", original_dump)
    metadata = backup(Path(engine.url.database), target)
    assert verify(target) == metadata


def test_failed_backup_does_not_remove_concurrently_created_manifest(engine, tmp_path, monkeypatch):
    from scripts import database_backup

    target = tmp_path / "race.db"
    manifest = target.with_suffix(".db.json")
    original_inspect = database_backup.inspect_database

    def inspect_with_competing_manifest(path):
        manifest.write_text("belongs to another operation", encoding="utf-8")
        return original_inspect(path)

    monkeypatch.setattr(database_backup, "inspect_database", inspect_with_competing_manifest)
    with pytest.raises(FileExistsError):
        backup(Path(engine.url.database), target)
    assert not target.exists()
    assert manifest.read_text() == "belongs to another operation"


def test_missing_migration_revision_rejects_backup_without_leaving_files(engine, tmp_path):
    with engine.begin() as db:
        db.execute(text("DELETE FROM alembic_version"))
    target = tmp_path / "unversioned.db"
    with pytest.raises(ValueError, match="migration revision"):
        backup(Path(engine.url.database), target)
    assert not target.exists()
    assert not target.with_suffix(".db.json").exists()


def test_inspection_closes_database_connection(engine, monkeypatch):
    from scripts import database_backup

    real_connect = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(database_backup.sqlite3, "connect", connect)
    inspect_database(Path(engine.url.database))
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def test_verify_cli_does_not_leak_invalid_manifest_or_traceback(tmp_path):
    target = tmp_path / "invalid.db"
    target.with_suffix(".db.json").write_text('["PRIVATE-SENTINEL"]', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.database_backup", "verify", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Backup operation failed" in result.stderr
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
