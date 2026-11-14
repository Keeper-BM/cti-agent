"""Encrypt explicitly selected deployment files; restore only into a new directory.

Uses Fernet from the existing Paramiko/cryptography dependency. Plaintext archives
stay in bounded process memory. Keep the generated recovery key separate from backups.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b"CTI-OPS-BACKUP/1\n"
MAX_BYTES = 64 * 1024 * 1024
MAX_ENCRYPTED_BYTES = ((MAX_BYTES + 128) // 3 + 1) * 4 + len(MAGIC)
MAX_FILES = 2000
FORMAT = "cti-operations-backup/1"


class BackupError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BackupError(message)


def safe_name(name):
    require(isinstance(name, str) and 0 < len(name) <= 512, "Invalid archive path")
    parts = name.split("/")
    require(
        not PurePosixPath(name).is_absolute()
        and len(parts) <= 20
        and all(part not in {"", ".", ".."} for part in parts)
        and not any(c in name for c in "\\:\x00")
        and not any(ord(c) < 32 for c in name)
        and all(not part.endswith((".", " ")) for part in parts),
        "Unsafe archive path",
    )
    # Keep the restore layout portable; Windows drive/device names are not payload files.
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    require(all(p.split(".")[0].casefold() not in reserved for p in parts), "Reserved archive path")
    return name


def regular_bytes(path, *, maximum=MAX_BYTES, private=False):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Only regular files may be read")
    if private and os.name == "posix":
        require(before.st_mode & 0o077 == 0, "Recovery key must be owner-only")
    require(before.st_size <= maximum, "Input file exceeds the size limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(opened.st_mode)
            and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
            "Input file changed while opening",
        )
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())

    def signature(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    require(
        len(data) <= maximum and signature(before) == signature(after),
        "Input file changed while reading",
    )
    require(signature(path.lstat()) == signature(after), "Input file was replaced while reading")
    return data


def private_parents(path):
    """Create each missing parent with mode 0700; never chmod existing directories."""
    if path.is_dir():
        return
    private_parents(path.parent)
    path.mkdir(mode=0o700)


def write_new(path, data):
    path = Path(path)
    private_parents(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def generate_key(path):
    write_new(path, Fernet.generate_key() + b"\n")


def cipher(key_file):
    return Fernet(regular_bytes(key_file, maximum=1024, private=True).strip())


def tree_files(root, prefix):
    root = Path(root)
    require(stat.S_ISDIR(root.lstat().st_mode), "Input directory must not be a symbolic link")
    pending = [(root, prefix)]
    count = 0
    while pending:
        directory, relative = pending.pop()
        require(not directory.is_symlink(), "Symbolic links are not backed up")
        for path in sorted(directory.iterdir()):
            count += 1
            require(count <= MAX_FILES, "Too many input directory entries")
            name = safe_name(relative + "/" + path.name)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append((path, name))
            else:
                require(stat.S_ISREG(mode), "Links and special files are not backed up")
                yield name, path


def encode_archive(files):
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "files": [
            {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        ],
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in [
            ("manifest.json", json.dumps(manifest, ensure_ascii=False).encode()),
            *sorted(files.items()),
        ]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o600
            archive.addfile(entry, io.BytesIO(data))
            require(output.tell() <= MAX_BYTES, "Archive exceeds the size limit")
    require(output.tell() <= MAX_BYTES, "Archive exceeds the size limit")
    return output.getvalue(), manifest


def identity(name):
    return unicodedata.normalize("NFC", name).casefold()


def decode_archive(data):
    require(len(data) <= MAX_BYTES, "Archive exceeds the size limit")
    files, identities = {}, set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for entry in archive:
            name = safe_name(entry.name)
            require(entry.isfile() and not entry.issparse(), "Archive contains a non-regular file")
            require(identity(name) not in identities, "Duplicate archive path")
            require(
                len(files) <= MAX_FILES and entry.size >= 0, "Invalid archive entry count or size"
            )
            total += entry.size
            require(total <= MAX_BYTES, "Archive exceeds the size limit")
            stream = archive.extractfile(entry)
            content = stream.read(entry.size + 1)
            require(len(content) == entry.size, "Archive entry is incomplete")
            files[name] = content
            identities.add(identity(name))
    require("manifest.json" in files, "Missing archive manifest")
    manifest = json.loads(files.pop("manifest.json"))
    require(
        isinstance(manifest, dict) and set(manifest) == {"format", "created_at", "files"},
        "Invalid archive manifest",
    )
    require(
        manifest["format"] == FORMAT and isinstance(manifest["created_at"], str),
        "Unknown archive format",
    )
    records = manifest["files"]
    require(isinstance(records, list) and 1 <= len(records) <= MAX_FILES, "Invalid manifest files")
    listed = set()
    for record in records:
        require(
            isinstance(record, dict) and set(record) == {"path", "bytes", "sha256"},
            "Invalid manifest entry",
        )
        name = safe_name(record["path"])
        require(name in files and name not in listed, "Manifest file set differs")
        require(
            name == "config/app.env" or name.startswith(("ssh/", "evidence/")),
            "Unsupported restore layout",
        )
        require(
            type(record["bytes"]) is int
            and len(files[name]) == record["bytes"]
            and hashlib.sha256(files[name]).hexdigest() == record["sha256"],
            "Manifest checksum or size differs",
        )
        listed.add(name)
    require(set(files) == listed and "config/app.env" in files, "Manifest file set differs")
    # Disallow a payload file also being another payload file's parent (case-insensitive).
    folded = {identity(name) for name in files}
    require(
        all(
            identity(str(parent)) not in folded
            for name in files
            for parent in PurePosixPath(name).parents
        ),
        "Conflicting archive paths",
    )
    return files, manifest


def create(target, key_file, *, env_file, ssh_directory, evidence_directory=None):
    target, key_file = Path(target), Path(key_file)
    require(not target.exists() and not target.is_symlink(), "Backup destination already exists")
    encryption = cipher(key_file)
    for directory in (ssh_directory, evidence_directory):
        if directory is not None:
            root = Path(directory).resolve()
            require(
                not target.resolve().is_relative_to(root)
                and not key_file.resolve().is_relative_to(root),
                "Backup and recovery key must be outside input directories",
            )
    sources = [("config/app.env", Path(env_file)), *tree_files(ssh_directory, "ssh")]
    if evidence_directory is not None:
        sources.extend(tree_files(evidence_directory, "evidence"))
    require(len(sources) <= MAX_FILES, "Too many backup files")
    files, size = {}, 0
    for name, path in sources:
        require(not path.samefile(key_file), "Recovery key must not be included in the backup")
        require(path.resolve() != target.resolve(), "Destination is inside the input file set")
        content = regular_bytes(path)
        size += len(content)
        require(size <= MAX_BYTES, "Backup exceeds the size limit")
        files[name] = content
    payload, manifest = encode_archive(files)
    decode_archive(payload)  # Reject duplicate/colliding/unsupported paths before writing anything.
    write_new(target, MAGIC + encryption.encrypt(payload))
    return manifest


def read_bundle(source, key_file):
    encryption = cipher(key_file)
    raw = regular_bytes(source, maximum=MAX_ENCRYPTED_BYTES)
    require(raw.startswith(MAGIC), "Unknown backup format")
    try:
        payload = encryption.decrypt(raw[len(MAGIC) :])
    except InvalidToken:
        raise BackupError("Backup authentication failed") from None
    return decode_archive(payload)


def verify(source, key_file):
    return read_bundle(source, key_file)[1]


def restore(source, key_file, destination):
    destination = Path(destination)
    require(
        not destination.exists() and not destination.is_symlink(),
        "Restore destination already exists",
    )
    files, manifest = read_bundle(source, key_file)
    # Authenticate and validate every entry before creating the destination.
    destination.mkdir(mode=0o700, parents=False)
    try:
        for name, data in files.items():
            path = destination.joinpath(*PurePosixPath(name).parts)
            write_new(path, data)
            require(regular_bytes(path) == data, "Restored file differs")
        # An empty SSH directory is valid and must still be available for Compose binding.
        (destination / "ssh").mkdir(mode=0o700, exist_ok=True)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    keygen = sub.add_parser("keygen")
    keygen.add_argument("key_file", type=Path)
    for action in ("create", "verify", "restore"):
        item = sub.add_parser(action)
        item.add_argument("archive", type=Path)
        item.add_argument("--key-file", type=Path, required=True)
        if action == "create":
            item.add_argument("--env-file", type=Path, required=True)
            item.add_argument("--ssh-directory", type=Path, required=True)
            item.add_argument("--evidence-directory", type=Path)
        if action == "restore":
            item.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "keygen":
            generate_key(args.key_file)
            print("Created owner-only recovery key. Store separately from backups.")
            return
        if args.action == "create":
            metadata = create(
                args.archive,
                args.key_file,
                env_file=args.env_file,
                ssh_directory=args.ssh_directory,
                evidence_directory=args.evidence_directory,
            )
        elif args.action == "verify":
            metadata = verify(args.archive, args.key_file)
        else:
            metadata = restore(args.archive, args.key_file, args.destination)
    except (OSError, ValueError, tarfile.TarError):
        parser.exit(
            1, "Operations backup failed. Check key, permissions, inputs and new destination.\n"
        )
    print(f"Completed {args.action}: files={len(metadata['files'])}; contents not displayed")


if __name__ == "__main__":
    main()
