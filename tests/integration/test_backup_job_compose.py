"""Scheduled job entry point against a disposable, migrated PostgreSQL database."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import operations_backup as files
from scripts.postgres_backup import restore, verify
from tests.fixtures.compose_accounts import account_stack, require


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_COMPOSE_PROJECT"), reason="Requires an explicit Compose test DB"
)
def test_backup_job_cli_restores_real_database_and_preserves_previous_runs(
    tmp_path, record_testsuite_property
):
    with account_stack(
        os.environ["TEST_POSTGRES_COMPOSE_PROJECT"],
        os.environ["TEST_POSTGRES_COMPOSE_ENV_FILE"],
    ) as stack:
        for name in ("work", "destination", "ssh", "evidence"):
            (tmp_path / name).mkdir(mode=0o700)
        key = tmp_path / "recovery.key"
        files.generate_key(key)
        files.write_new(tmp_path / "ssh/collector", b"test-key-only")
        files.write_new(tmp_path / "evidence/probe.json", b'{"evidence":"preserved"}')
        marker = tmp_path / "destination/.cti-backup-destination"
        files.write_new(marker, b"compose-acceptance\n")
        config = tmp_path / "job.json"
        files.write_new(
            config,
            json.dumps(
                {
                    "project_name": os.environ["TEST_POSTGRES_COMPOSE_PROJECT"],
                    "env_file": str(Path(os.environ["TEST_POSTGRES_COMPOSE_ENV_FILE"]).resolve()),
                    "key_file": str(key),
                    "ssh_directory": str(tmp_path / "ssh"),
                    "work_directory": str(tmp_path / "work"),
                    "destination_directory": str(tmp_path / "destination"),
                    "destination_id": "compose-acceptance",
                    "database": stack.source,
                    "evidence_directory": str(tmp_path / "evidence"),
                }
            ).encode(),
        )
        stack.db.sql(
            stack.source, "CREATE TABLE backup_job_probe (id SERIAL PRIMARY KEY, value TEXT);"
        )
        stack.db.sql(stack.source, "INSERT INTO backup_job_probe(value) VALUES ('보존할 값');")

        def run(expected):
            result = subprocess.run(
                [sys.executable, "-m", "scripts.backup_job", "--config", str(config)],
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            require(result.returncode == expected, "Unexpected backup job exit status")
            require("Traceback" not in result.stderr, "Unsanitized backup error")
            return json.loads(result.stdout) if expected == 0 else None

        first = run(0)
        archive = tmp_path / "destination" / first["run_id"] / "backup.ctiops"
        require(
            hashlib.sha256(archive.read_bytes()).hexdigest() == first["sha256"], "Archive differs"
        )
        files.restore(archive, key, tmp_path / "recovered")
        dump = tmp_path / "recovered/evidence/database.dump"
        metadata = verify(dump)
        require(metadata.database.revision == "0011", "Missing migration state")
        stack.db.sql(stack.source, "INSERT INTO backup_job_probe(value) VALUES ('newer');")
        restore(stack.db, dump, stack.target)
        stack.databases.append(stack.target)
        require(
            stack.db.sql(stack.target, "SELECT value FROM backup_job_probe;").decode().strip()
            == "보존할 값",
            "Restored backup point differs",
        )
        require(stack.db.inspect(stack.target) == metadata.database, "Full database differs")
        second = run(0)
        require(first["run_id"] != second["run_id"], "Backup run overwrote previous run")
        require(
            hashlib.sha256(archive.read_bytes()).hexdigest() == first["sha256"],
            "Old backup changed",
        )
        marker.unlink()
        run(1)
        require(
            len(list((tmp_path / "destination").glob("*/completed.json"))) == 2,
            "Failure published a receipt",
        )
        require(not list((tmp_path / "work").glob("cti-backup-*")), "Plaintext staging remains")
        require(
            stack.db.sql(
                "postgres",
                "SELECT count(*) FROM pg_database WHERE datname LIKE 'cti_backup_verify_%';",
            ).strip()
            == b"0",
            "Scratch database remains",
        )
        for name, value in {
            "tables": len(metadata.database.tables),
            "files": first["files"],
            "completed_runs": 2,
        }.items():
            record_testsuite_property("backup_job." + name, value)
