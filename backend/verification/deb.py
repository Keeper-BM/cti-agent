"""Inspect signed-hash-verified .deb bytes; never extract or execute package payloads."""

import hashlib
import io
import posixpath
import tarfile

import zstandard

from backend.core.errors import AppError

MAX_UNPACKED = 512 * 1024 * 1024
MAX_FILES = 6000


def invalid():
    return AppError("PACKAGE_FORMAT_INVALID", "공식 패키지의 파일 형식을 확인할 수 없습니다.", 502)


def ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise invalid()
    pos, members = 8, {}
    try:
        while pos < len(data):
            header = data[pos : pos + 60]
            if len(header) != 60 or header[58:] != b"`\n":
                raise ValueError()
            name = header[:16].decode("ascii").strip().removesuffix("/")
            size = int(header[48:58])
            pos += 60
            if size < 0 or size > len(data) - pos or name in members:
                raise ValueError()
            members[name] = data[pos : pos + size]
            pos += size + (size % 2)
    except (ValueError, UnicodeError):
        raise invalid() from None
    if members.get("debian-binary") != b"2.0\n":
        raise invalid()
    return members


def safe_name(value):
    value = value.removeprefix("./")
    if value in {"", "."}:
        return "/"
    if value.startswith("/") or "\x00" in value or ".." in value.split("/"):
        raise invalid()
    path = "/" + posixpath.normpath(value)
    if len(path) > 500 or any(ord(c) < 32 for c in path):
        raise invalid()
    return path


def tar_entries(blob, name):
    source = io.BytesIO(blob)
    total, count = 0, 0
    try:
        if name.endswith(".zst"):
            if zstandard.get_frame_parameters(blob).window_size > 128 * 1024 * 1024:
                raise invalid()
            source = zstandard.ZstdDecompressor(max_window_size=128 * 1024 * 1024).stream_reader(
                source
            )
        with source, tarfile.open(fileobj=source, mode="r|*") as archive:
            for item in archive:
                count += 1
                total += item.size
                if count > MAX_FILES or item.size < 0 or total > MAX_UNPACKED:
                    raise invalid()
                path = safe_name(item.name)
                if item.isfile():
                    with archive.extractfile(item) as stream:
                        digest = hashlib.sha256()
                        small = bytearray() if path in {"/control", "/conffiles"} else None
                        read = 0
                        while block := stream.read(65536):
                            read += len(block)
                            if read > item.size:
                                raise invalid()
                            digest.update(block)
                            if small is not None:
                                if len(small) + len(block) > 1024 * 1024:
                                    raise invalid()
                                small.extend(block)
                        if read != item.size:
                            raise invalid()
                    yield (
                        path,
                        {
                            "kind": "file",
                            "sha256": digest.hexdigest(),
                            "size": item.size,
                            "mode": item.mode & 0o7777,
                            "uid": item.uid,
                            "gid": item.gid,
                            "text": bytes(small).decode("utf-8") if small is not None else None,
                        },
                    )
                elif item.issym():
                    if "\x00" in item.linkname or len(item.linkname) > 500:
                        raise invalid()
                    yield path, {"kind": "symlink", "target": item.linkname}
                elif item.islnk():
                    yield path, {"kind": "hardlink", "target": safe_name(item.linkname)}
                elif not item.isdir():
                    raise invalid()
    except (tarfile.TarError, OSError, UnicodeError, zstandard.ZstdError, ValueError):
        raise invalid() from None


def parse_fields(text):
    result = {}
    key = None
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and key:
            result[key] += "\n" + line[1:]
        else:
            key, sep, value = line.partition(":")
            if not sep or key in result:
                raise invalid()
            result[key] = value.strip()
    return result


def inspect_deb(data, name, version, architecture):
    members = ar_members(data)
    control_names = [n for n in members if n.startswith("control.tar")]
    data_names = [n for n in members if n.startswith("data.tar")]
    if len(control_names) != 1 or len(data_names) != 1:
        raise invalid()
    control = dict(tar_entries(members[control_names[0]], control_names[0]))
    if "/control" not in control or control["/control"]["kind"] != "file":
        raise invalid()
    fields = parse_fields(control["/control"]["text"])
    if (fields.get("Package"), fields.get("Version"), fields.get("Architecture")) != (
        name,
        version,
        architecture,
    ):
        raise AppError(
            "PACKAGE_IDENTITY_MISMATCH", "공식 패키지의 이름·버전·아키텍처가 다릅니다.", 502
        )
    configs = set()
    if "/conffiles" in control:
        for line in (control["/conffiles"].get("text") or "").splitlines():
            value = line.strip().split()
            if value:
                configs.add(value[0])
    files = {}
    for path, item in tar_entries(members[data_names[0]], data_names[0]):
        if path in files:
            raise invalid()
        files[path] = {**item, "configuration": path in configs}
    for item in files.values():
        if item["kind"] == "hardlink":
            target = files.get(item["target"])
            if not target or target["kind"] != "file":
                raise invalid()
            item.update({k: v for k, v in target.items() if k != "configuration"})
    if not files:
        raise invalid()
    return fields, files
