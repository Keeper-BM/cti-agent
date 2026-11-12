"""Explicitly opt in against a disposable, migrated Compose stack (also run in CI)."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.postgres_backup import (
    BackupError,
    ComposePostgres,
    backup,
    manifest_path,
    quoted,
    restore,
    verify,
)


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_COMPOSE_PROJECT"), reason="Requires an explicit Compose test DB"
)
def test_real_postgres_dump_restore_and_rejection(tmp_path):
    db = ComposePostgres(
        os.environ["TEST_POSTGRES_COMPOSE_PROJECT"],
        Path(os.environ["TEST_POSTGRES_COMPOSE_ENV_FILE"]),
    )
    table = "backup_probe_" + uuid4().hex[:12] + '"quoted'
    identifier = quoted(table)
    target = "cti_restored_" + uuid4().hex
    broken = "cti_rejected_" + uuid4().hex
    archive = tmp_path / "actual.dump"
    created_target = False
    db.sql(db.database, f"CREATE TABLE {identifier} (id SERIAL PRIMARY KEY, value JSONB);")
    try:
        db.sql(
            db.database, f'INSERT INTO {identifier}(value) VALUES (\'{{"메시지":"preserved"}}\');'
        )
        expected = backup(db, archive)
        assert verify(archive) == expected
        assert any(t.name == table and t.rows == 1 for t in expected.database.tables)
        assert any(
            s.name == table + "_id_seq" and s.last_value == 1 for s in expected.database.sequences
        )
        db.sql(db.database, f"INSERT INTO {identifier}(value) VALUES ('{{}}');")
        assert restore(db, archive, target) == expected
        created_target = True
        assert db.sql(target, f"SELECT count(*) FROM {identifier};").strip() == b"1"
        assert db.sql(db.database, f"SELECT count(*) FROM {identifier};").strip() == b"2"
        with pytest.raises(BackupError):
            restore(db, archive, target)
        assert db.sql(target, f"SELECT count(*) FROM {identifier};").strip() == b"1"
        metadata = expected.model_dump()
        metadata["database"]["tables"][0]["sha256"] = "0" * 64
        manifest_path(archive).write_text(json.dumps(metadata))
        with pytest.raises(BackupError, match="differ"):
            restore(db, archive, broken)
        assert (
            db.sql(
                "postgres", f"SELECT count(*) FROM pg_database WHERE datname='{broken}';"
            ).strip()
            == b"0"
        )
        # A changed archive is rejected before CREATE, even when the target name is valid.
        archive.write_bytes(archive.read_bytes() + b"tampered")
        with pytest.raises(BackupError, match="SHA-256"):
            restore(db, archive, broken)
        assert (
            db.sql(
                "postgres",
                "SELECT count(*) FROM pg_database WHERE datname LIKE 'cti_backup_verify_%';",
            ).strip()
            == b"0"
        )
    finally:
        if created_target:
            db.drop_created_database(target)
        db.sql(db.database, f"DROP TABLE {identifier};")
