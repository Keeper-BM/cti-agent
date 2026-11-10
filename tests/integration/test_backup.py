import json
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts.database_backup import backup, restore, verify


def test_backup_restore_preserves_data_and_rejects_overwrite_or_tamper(engine, tmp_path):
    with engine.begin() as db:
        db.execute(text("CREATE TABLE backup_example (value TEXT)"))
        db.execute(text("INSERT INTO backup_example VALUES ('preserved')"))
    target = tmp_path / "saved.db"
    restored = tmp_path / "restored.db"
    metadata = backup(Path(engine.url.database), target)
    assert verify(target) == metadata
    restore(target, restored)
    import sqlite3

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
