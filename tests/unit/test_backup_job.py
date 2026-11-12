import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from scripts import backup_job as job
from scripts import operations_backup as files
from scripts.postgres_backup import verify
from tests.unit.test_postgres_backup_tool import FakePostgres


@pytest.fixture
def config(tmp_path, monkeypatch):
    for name in ("work", "destination", "ssh", "evidence"):
        (tmp_path / name).mkdir(mode=0o700)
    files.generate_key(tmp_path / "recovery.key")
    files.write_new(tmp_path / "stack.env", b"POSTGRES_PASSWORD=PRIVATE-ENV-SENTINEL\n")
    files.write_new(tmp_path / "ssh/collector", b"PRIVATE-SSH-SENTINEL")
    files.write_new(tmp_path / "evidence/proof.json", b'{"test":"evidence"}')
    files.write_new(tmp_path / "destination/.cti-backup-destination", b"test-destination\n")
    monkeypatch.setattr(job, "ComposePostgres", lambda *a, **kw: FakePostgres())
    return job.Config(
        project_name="cti-backup-test",
        env_file=tmp_path / "stack.env",
        key_file=tmp_path / "recovery.key",
        ssh_directory=tmp_path / "ssh",
        evidence_directory=tmp_path / "evidence",
        work_directory=tmp_path / "work",
        destination_directory=tmp_path / "destination",
        destination_id="test-destination",
    )


def config_file(config, path):
    data = {k: str(v) if isinstance(v, Path) else v for k, v in asdict(config).items()}
    if data["evidence_directory"] is None:
        data.pop("evidence_directory")
    files.write_new(path, json.dumps(data).encode())
    return path


def assert_no_new_backup(config):
    assert not list(config.destination_directory.glob("*/completed.json"))
    assert not list(config.destination_directory.glob("*/backup.ctiops"))
    assert not list(config.work_directory.glob("cti-backup-*"))


def test_complete_job_recovers_database_settings_keys_and_evidence(tmp_path, config):
    assert job.load_config(config_file(config, tmp_path / "job.json")) == config
    old_mask = os.umask(0)
    try:
        receipt = job.run(config)
    finally:
        os.umask(old_mask)
    output = config.destination_directory / receipt["run_id"]
    assert json.loads((output / "completed.json").read_text()) == receipt
    assert receipt["status"] == "COMPLETE" and receipt["tables"] == 1
    assert receipt["files"] == 5
    assert "PRIVATE-" not in json.dumps(receipt)
    recovered = tmp_path / "restored"
    files.restore(output / "backup.ctiops", config.key_file, recovered)
    assert verify(recovered / "evidence/database.dump").database.revision == "0011"
    assert (recovered / "config/app.env").read_bytes() == config.env_file.read_bytes()
    assert (recovered / "ssh/collector").read_bytes() == b"PRIVATE-SSH-SENTINEL"
    assert (recovered / "evidence/selected/proof.json").read_bytes() == b'{"test":"evidence"}'
    assert not list(config.work_directory.glob("cti-backup-*"))
    for path in (output, *output.iterdir(), config.work_directory / ".cti-backup.lock"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    again = job.run(config)
    assert again["run_id"] != receipt["run_id"]
    assert (output / "completed.json").exists()
    assert len(list(config.destination_directory.glob("*/completed.json"))) == 2


@pytest.mark.parametrize("stage", ["database", "encryption", "verification", "receipt", "signal"])
def test_failure_cleans_only_this_run_preserving_previous(config, monkeypatch, stage):
    previous = job.run(config)
    previous_path = config.destination_directory / previous["run_id"]
    previous_bytes = (previous_path / "backup.ctiops").read_bytes()

    def fail(*a, **kw):
        raise OSError("PRIVATE-ERROR-SENTINEL")

    if stage == "database":
        monkeypatch.setattr(job, "backup", fail)
    elif stage == "encryption":
        monkeypatch.setattr(files, "create", fail)
    elif stage == "verification":
        monkeypatch.setattr(files, "verify", fail)
    elif stage == "signal":
        monkeypatch.setattr(files, "verify", lambda *a: job.interrupted(signal.SIGTERM, None))
    else:
        original = files.write_new

        def fail_receipt(path, data):
            if path.name == "completed.json":
                fail()
            original(path, data)

        monkeypatch.setattr(files, "write_new", fail_receipt)
    with pytest.raises(OSError):
        job.run(config)
    assert list(config.destination_directory.glob("*/completed.json")) == [
        previous_path / "completed.json"
    ]
    assert (previous_path / "backup.ctiops").read_bytes() == previous_bytes
    assert not list(config.work_directory.glob("cti-backup-*"))


@pytest.mark.parametrize(
    "problem",
    [
        "missing-marker",
        "wrong-marker",
        "marker-link",
        "public-destination",
        "linked-destination",
        "overlap",
        "key-in-work",
        "key-in-evidence",
        "key-hardlink",
    ],
)
def test_invalid_storage_or_key_rejected(config, tmp_path, monkeypatch, problem):
    def no_database(*a, **kw):
        pytest.fail("Must reject before accessing Docker")

    monkeypatch.setattr(job, "ComposePostgres", no_database)
    marker = config.destination_directory / ".cti-backup-destination"
    if problem == "missing-marker":
        marker.unlink()
    elif problem == "wrong-marker":
        marker.write_bytes(b"another-destination\n")
    elif problem == "marker-link":
        marker.unlink()
        marker.symlink_to(config.env_file)
    elif problem == "public-destination":
        config.destination_directory.chmod(0o755)
    elif problem == "linked-destination":
        link = tmp_path / "linked"
        link.symlink_to(config.destination_directory)
        config = replace(config, destination_directory=link)
    elif problem == "overlap":
        config = replace(config, work_directory=config.destination_directory)
    elif problem in {"key-in-work", "key-in-evidence"}:
        root = config.work_directory if problem == "key-in-work" else config.evidence_directory
        key = root / "recovery.key"
        files.generate_key(key)
        config = replace(config, key_file=key)
    else:
        os.link(config.key_file, config.evidence_directory / "key-copy")
    with pytest.raises((ValueError, OSError)):
        job.run(config)
    assert_no_new_backup(config)


def test_unmounted_destination_after_database_backup_is_rejected(config, monkeypatch):
    original = job.backup

    def changed(*args):
        result = original(*args)
        (config.destination_directory / ".cti-backup-destination").unlink()
        return result

    monkeypatch.setattr(job, "backup", changed)
    with pytest.raises(OSError):
        job.run(config)
    assert_no_new_backup(config)


def test_lock_denies_parallel_process_and_releases_after_termination(config):
    code = (
        "import sys; from pathlib import Path; from scripts.backup_job import exclusive_job; "
        "ctx=exclusive_job(Path(sys.argv[1])); ctx.__enter__(); "
        "print('locked',flush=True); sys.stdin.read(1)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(config.work_directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="active"):
            job.run(config)
        assert_no_new_backup(config)
    finally:
        process.terminate()
        process.communicate(timeout=10)
    assert job.run(config)["status"] == "COMPLETE"


def test_cli_sigterm_cleans_staging_and_unpublished_output(config, tmp_path):
    path = config_file(config, tmp_path / "job.json")
    code = """
import signal, sys
from scripts import backup_job as job
from tests.unit.test_postgres_backup_tool import FakePostgres
job.ComposePostgres = lambda *a, **kw: FakePostgres()
def blocked(*a, **kw):
    print('archive-written', flush=True)
    signal.pause()
job.files.verify = blocked
sys.argv = ['backup_job', '--config', sys.argv[1]]
job.main()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "archive-written"
        assert list(config.destination_directory.glob("*/backup.ctiops"))
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 1
        assert "Backup job failed" in stderr and "Traceback" not in stderr
        assert "PRIVATE-" not in stdout + stderr
        assert_no_new_backup(config)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "fifo"])
def test_unsafe_lock_file_rejected(config, kind):
    lock = config.work_directory / ".cti-backup.lock"
    if kind == "symlink":
        lock.symlink_to(config.key_file)
    elif kind == "hardlink":
        os.link(config.key_file, lock)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.write_bytes(b"")
        lock.chmod(0o644)
    with pytest.raises((ValueError, OSError)):
        job.run(config)
    assert_no_new_backup(config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("env_file", "relative"),
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("database", []),
        ("project_name", "x; command"),
        ("unexpected", "PRIVATE-SENTINEL"),
    ],
)
def test_bad_config_cli_is_sanitized(config, tmp_path, field, value):
    path = config_file(config, tmp_path / "job.json")
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backup_job", "--config", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Backup job failed" in result.stderr
    assert "PRIVATE-" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr
    assert_no_new_backup(config)
