"""Run verified PostgreSQL + encrypted file backups for a host scheduler.

Run from the repository root. Only explicitly configured, pre-existing private
directories are used. Completed runs contain a receipt written after verification
and plaintext staging cleanup; previous runs are never deleted or overwritten.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts import operations_backup as files
from scripts.postgres_backup import ComposePostgres, backup, database_name


@dataclass(frozen=True)
class Config:
    project_name: str
    env_file: Path
    key_file: Path
    ssh_directory: Path
    work_directory: Path
    destination_directory: Path
    destination_id: str
    evidence_directory: Path | None = None
    database: str | None = None
    timeout_seconds: int = 300


def private_directory(path):
    info = path.lstat()
    files.require(
        stat.S_ISDIR(info.st_mode) and info.st_mode & 0o077 == 0,
        "Expected an existing owner-only directory, not a link",
    )


def load_config(path):
    data = json.loads(files.regular_bytes(path, maximum=16384, private=True))
    required = {
        "project_name",
        "env_file",
        "key_file",
        "ssh_directory",
        "work_directory",
        "destination_directory",
        "destination_id",
    }
    optional = {"evidence_directory", "database", "timeout_seconds"}
    files.require(
        isinstance(data, dict) and required <= data.keys() <= required | optional,
        "Invalid backup job configuration",
    )
    for name in required - {"project_name", "destination_id"} | {"evidence_directory"}:
        if name not in data:
            continue
        value = data[name]
        files.require(isinstance(value, str) and Path(value).is_absolute(), "Use absolute paths")
        data[name] = Path(value)
    config = Config(**data)
    validate(config)
    return config


def validate(config):
    files.require(os.name == "posix", "Backup jobs require POSIX file locks and permissions")
    files.require(
        isinstance(config.project_name, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", config.project_name),
        "Invalid Compose project name",
    )
    files.require(
        isinstance(config.destination_id, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", config.destination_id),
        "Invalid destination identity",
    )
    files.require(
        type(config.timeout_seconds) is int and 1 <= config.timeout_seconds <= 3600,
        "Invalid command timeout",
    )
    if config.database is not None:
        files.require(isinstance(config.database, str), "Invalid source database")
        database_name(config.database)
    for directory in (config.work_directory, config.destination_directory):
        private_directory(directory)
    work, destination = config.work_directory.resolve(), config.destination_directory.resolve()
    files.require(
        not work.is_relative_to(destination) and not destination.is_relative_to(work),
        "Work and destination directories must be separate",
    )
    for path in (config.env_file, config.key_file):
        files.require(
            not any(path.resolve().is_relative_to(p) for p in (work, destination)),
            "Settings and recovery key must stay outside work and destination directories",
        )
    files.cipher(config.key_file)
    files.regular_bytes(config.env_file, maximum=1024 * 1024, private=True)
    files.require(not config.env_file.samefile(config.key_file), "Recovery key is not an env file")
    for directory in (config.ssh_directory, config.evidence_directory):
        if directory is None:
            continue
        files.require(stat.S_ISDIR(directory.lstat().st_mode), "Invalid input directory")
        source = directory.resolve()
        files.require(
            not config.key_file.resolve().is_relative_to(source)
            and all(
                not source.is_relative_to(p) and not p.is_relative_to(source)
                for p in (work, destination)
            ),
            "Input directories must exclude recovery key, staging and backups",
        )
    marker = files.regular_bytes(
        config.destination_directory / ".cti-backup-destination", maximum=128, private=True
    )
    files.require(marker == (config.destination_id + "\n").encode(), "Wrong backup destination")


@contextmanager
def exclusive_job(work_directory):
    # Never unlink this file: unlinking a held flock would allow another inode/lock.
    import fcntl

    path = work_directory / ".cti-backup.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        files.require(
            stat.S_ISREG(info.st_mode) and info.st_mode & 0o077 == 0 and info.st_nlink == 1,
            "Invalid backup lock file",
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise files.BackupError("Another backup job is active") from None
        yield
    finally:
        os.close(descriptor)


def copy_evidence(config, target):
    if config.evidence_directory is None:
        return
    total = 0
    for name, source in files.tree_files(config.evidence_directory, "selected"):
        # Check before copying: copying a hard link would hide its identity from create().
        files.require(not source.samefile(config.key_file), "Recovery key is part of evidence")
        content = files.regular_bytes(source)
        total += len(content)
        files.require(total <= files.MAX_BYTES, "Evidence exceeds the size limit")
        files.write_new(target.joinpath(*name.split("/")), content)


def run(config):
    validate(config)
    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex
    output = config.destination_directory / run_id
    with exclusive_job(config.work_directory):
        created = False
        try:
            with tempfile.TemporaryDirectory(
                prefix="cti-backup-", dir=config.work_directory
            ) as temp:
                evidence = Path(temp) / "evidence"
                evidence.mkdir(mode=0o700)
                copy_evidence(config, evidence)
                db = ComposePostgres(
                    config.project_name,
                    config.env_file,
                    database=config.database,
                    timeout=config.timeout_seconds,
                )
                metadata = backup(db, evidence / "database.dump")
                # Check again after the dump in case the destination was unmounted/replaced.
                validate(config)
                output.mkdir(mode=0o700)
                created = True
                archive = output / "backup.ctiops"
                file_metadata = files.create(
                    archive,
                    config.key_file,
                    env_file=config.env_file,
                    ssh_directory=config.ssh_directory,
                    evidence_directory=evidence,
                )
                files.require(
                    files.verify(archive, config.key_file) == file_metadata,
                    "Written archive verification failed",
                )
                receipt = {
                    "format": "cti-backup-job/1",
                    "status": "COMPLETE",
                    "run_id": run_id,
                    "started_at": started.isoformat(),
                    "archive": "backup.ctiops",
                    "bytes": archive.stat().st_size,
                    "sha256": hashlib.sha256(
                        files.regular_bytes(archive, maximum=files.MAX_ENCRYPTED_BYTES)
                    ).hexdigest(),
                    "files": len(file_metadata["files"]),
                    "revision": metadata.database.revision,
                    "tables": len(metadata.database.tables),
                }
            # Plaintext staging must be removed before the completion marker is published.
            receipt["completed_at"] = datetime.now(UTC).isoformat()
            files.write_new(output / "completed.json", json.dumps(receipt, indent=2).encode())
            return receipt
        except BaseException:
            if created:
                shutil.rmtree(output)
            raise


def interrupted(_signal, _frame):
    raise InterruptedError("Backup job interrupted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        result = run(load_config(args.config))
    except (OSError, ValueError, tarfile.TarError, KeyboardInterrupt):
        # Never print exception details: inputs and subprocess failures may contain secrets.
        parser.exit(
            1,
            "Backup job failed; no new completed backup. "
            "Check private configuration and service status.\n",
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
