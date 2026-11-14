"""Authenticated file recovery must fail closed before writing untrusted paths."""

import io
import json
import os
import stat
import subprocess
import sys
import tarfile

import pytest
from cryptography.fernet import Fernet

from scripts import operations_backup as ops


@pytest.fixture
def inputs(tmp_path):
    key = tmp_path / "recovery.key"
    ops.generate_key(key)
    env = tmp_path / "stack.env"
    ops.write_new(env, b"POSTGRES_PASSWORD=private-db-sentinel\n")
    ssh = tmp_path / "ssh-input"
    ssh.mkdir()
    ops.write_new(ssh / "collector", b"private-ssh-sentinel")
    evidence = tmp_path / "evidence-input"
    evidence.mkdir()
    ops.write_new(evidence / "nested" / "근거.json", b'{"source":"fixture"}')
    return key, {"env_file": env, "ssh_directory": ssh, "evidence_directory": evidence}


def bundle(tmp_path, key, payload):
    path = tmp_path / "forged.ctiops"
    path.write_bytes(ops.MAGIC + Fernet(key.read_bytes().strip()).encrypt(payload))
    return path


def tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, content, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(content)
            entry.linkname = "../../outside"
            archive.addfile(entry, io.BytesIO(content))
    return output.getvalue()


def test_roundtrip_encryption_unicode_permissions_and_exclusive_output(tmp_path, inputs):
    key, args = inputs
    archive, destination = tmp_path / "archive.ctiops", tmp_path / "restored"
    old_mask = os.umask(0)
    try:
        metadata = ops.create(archive, key, **args)
        assert ops.verify(archive, key) == metadata
        assert ops.restore(archive, key, destination) == metadata
    finally:
        os.umask(old_mask)
    assert (destination / "config/app.env").read_bytes() == args["env_file"].read_bytes()
    assert (destination / "ssh/collector").read_bytes() == b"private-ssh-sentinel"
    assert (destination / "evidence/nested/근거.json").read_bytes() == b'{"source":"fixture"}'
    for value in (b"private-db-sentinel", b"private-ssh-sentinel", b"config/app.env"):
        assert value not in archive.read_bytes()
    for path in [key, archive, destination, *destination.rglob("*")]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    encrypted = archive.read_bytes()
    with pytest.raises(ops.BackupError):
        ops.create(archive, key, **args)
    assert archive.read_bytes() == encrypted
    original_key = key.read_bytes()
    with pytest.raises(FileExistsError):
        ops.generate_key(key)
    assert key.read_bytes() == original_key


def test_empty_ssh_directory_restores(tmp_path, inputs):
    key, args = inputs
    (args["ssh_directory"] / "collector").unlink()
    args.pop("evidence_directory")
    archive, destination = tmp_path / "archive.ctiops", tmp_path / "restored"
    assert len(ops.create(archive, key, **args)["files"]) == 1
    ops.restore(archive, key, destination)
    assert (destination / "ssh").is_dir()


@pytest.mark.parametrize("damage", ["wrong-key", "ciphertext", "header", "truncated"])
def test_authentication_failure_creates_nothing(tmp_path, inputs, damage):
    key, args = inputs
    archive, destination = tmp_path / "archive.ctiops", tmp_path / "restored"
    ops.create(archive, key, **args)
    if damage == "wrong-key":
        key = tmp_path / "wrong.key"
        ops.generate_key(key)
    else:
        data = bytearray(archive.read_bytes())
        if damage == "truncated":
            data = data[:-32]
        else:
            data[0 if damage == "header" else len(data) // 2] ^= 1
        archive.write_bytes(data)
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, destination)
    assert not destination.exists()


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_restore_destination_is_never_overwritten(tmp_path, inputs, kind):
    key, args = inputs
    archive, destination = tmp_path / "archive.ctiops", tmp_path / "restored"
    ops.create(archive, key, **args)
    if kind == "directory":
        destination.mkdir()
    elif kind == "file":
        destination.write_bytes(b"untouched")
    else:
        destination.symlink_to(args["env_file"])
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, destination)
    assert destination.exists()
    if kind == "file":
        assert destination.read_bytes() == b"untouched"


@pytest.mark.parametrize(
    "path",
    ["../escape", "/escape", "ssh/../escape", "ssh\\escape", "C:/escape", "ssh/NUL", "ssh/x."],
)
def test_unsafe_archive_paths_rejected_before_writing(tmp_path, inputs, path):
    key, _ = inputs
    archive = bundle(tmp_path, key, tar([(path, b"bad", tarfile.REGTYPE)]))
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.DIRTYPE]
)
def test_nonregular_archive_entries_rejected(tmp_path, inputs, kind):
    key, _ = inputs
    archive = bundle(tmp_path, key, tar([("ssh/unsafe", b"", kind)]))
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"ssh/A": b"a", "ssh/a": b"b"},
        {"ssh/caf\u00e9": b"a", "ssh/cafe\u0301": b"b"},
        {"ssh/dir": b"a", "ssh/dir/key": b"b"},
        {"other/key": b"a"},
    ],
)
def test_collisions_and_unknown_layout_rejected(tmp_path, inputs, extra):
    key, _ = inputs
    payload, _ = ops.encode_archive({"config/app.env": b"env", **extra})
    archive = bundle(tmp_path, key, payload)
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("damage", ["checksum", "extra", "duplicate", "missing", "type", "empty"])
def test_manifest_validation(tmp_path, inputs, damage):
    key, _ = inputs
    _, manifest = ops.encode_archive({"config/app.env": b"env"})
    entries = [("config/app.env", b"env", tarfile.REGTYPE)]
    if damage == "checksum":
        manifest["files"][0]["sha256"] = "0" * 64
    elif damage == "extra":
        entries.append(("ssh/extra", b"unlisted", tarfile.REGTYPE))
    elif damage == "duplicate":
        manifest["files"] *= 2
    elif damage == "missing":
        entries.clear()
    elif damage == "type":
        manifest["files"][0]["bytes"] = True
    else:
        manifest = []
    entries.append(("manifest.json", json.dumps(manifest).encode(), tarfile.REGTYPE))
    archive = bundle(tmp_path, key, tar(entries))
    with pytest.raises(ops.BackupError):
        ops.restore(archive, key, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize(
    "kind", ["key-mode", "key-link", "file-link", "directory-link", "fifo", "key-copy"]
)
def test_unsafe_source_rejected(tmp_path, inputs, kind):
    key, args = inputs
    if kind == "key-mode":
        key.chmod(0o644)
    elif kind == "key-link":
        link = tmp_path / "link.key"
        link.symlink_to(key)
        key = link
    elif kind == "file-link":
        (args["ssh_directory"] / "link").symlink_to(args["env_file"])
    elif kind == "directory-link":
        link = tmp_path / "ssh-link"
        link.symlink_to(args["ssh_directory"], target_is_directory=True)
        args["ssh_directory"] = link
    elif kind == "fifo":
        os.mkfifo(args["ssh_directory"] / "fifo")
    else:
        os.link(key, args["ssh_directory"] / "recovery.key")
    archive = tmp_path / "archive.ctiops"
    with pytest.raises(ops.BackupError):
        ops.create(archive, key, **args)
    assert not archive.exists()


def test_key_and_output_cannot_be_inside_input_directories(tmp_path, inputs):
    key, args = inputs
    with pytest.raises(ops.BackupError):
        ops.create(args["ssh_directory"] / "backup.ctiops", key, **args)
    key = args["evidence_directory"] / "recovery.key"
    ops.generate_key(key)
    with pytest.raises(ops.BackupError):
        ops.create(tmp_path / "backup.ctiops", key, **args)


def test_bounds_reject_large_declared_size_and_file_count(tmp_path, inputs, monkeypatch):
    key, args = inputs
    with pytest.raises(ops.BackupError):
        ops.regular_bytes(args["env_file"], maximum=1)
    monkeypatch.setattr(ops, "MAX_FILES", 1)
    with pytest.raises(ops.BackupError):
        ops.create(tmp_path / "archive.ctiops", key, **args)
    entry = tarfile.TarInfo("config/app.env")
    entry.size = ops.MAX_BYTES + 1
    with pytest.raises(ops.BackupError):
        ops.decode_archive(entry.tobuf() + b"\0" * 1024)


def test_partial_restore_is_removed(tmp_path, inputs, monkeypatch):
    key, args = inputs
    archive, destination = tmp_path / "archive.ctiops", tmp_path / "restored"
    ops.create(archive, key, **args)
    original = ops.write_new

    def fail_second(path, data):
        if "ssh" in path.parts:
            raise OSError("simulated disk error")
        original(path, data)

    monkeypatch.setattr(ops, "write_new", fail_second)
    with pytest.raises(OSError):
        ops.restore(archive, key, destination)
    assert not destination.exists()


def test_failed_write_removes_only_its_new_output(tmp_path, monkeypatch):
    path = tmp_path / "out"

    def fail(_):
        raise OSError("simulated flush failure")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        ops.write_new(path, b"secret")
    assert not path.exists()
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        ops.write_new(path, b"replacement")
    assert path.read_bytes() == b"existing"


def test_cli_success_and_error_do_not_print_file_contents(tmp_path, inputs):
    key, args = inputs
    archive = tmp_path / "archive.ctiops"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.operations_backup",
            "create",
            str(archive),
            "--key-file",
            str(key),
            "--env-file",
            str(args["env_file"]),
            "--ssh-directory",
            str(args["ssh_directory"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    archive.write_bytes(b"secret-invalid-archive")
    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.operations_backup",
            "verify",
            str(archive),
            "--key-file",
            str(key),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1
    output = result.stdout + result.stderr + failed.stdout + failed.stderr
    assert "private-" not in output and "secret-invalid" not in output and "Traceback" not in output
    assert key.read_text().strip() not in output
