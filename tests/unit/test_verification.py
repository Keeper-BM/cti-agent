import copy
import hashlib
import io
import tarfile
from types import SimpleNamespace

import httpx
import pytest
import zstandard

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.verification.archive import ArchiveClient
from backend.verification.compare import compare_package
from backend.verification.deb import inspect_deb


def tar_blob(entries, zstd=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w" if zstd else "w:gz") as archive:
        for name, content in entries:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            item.mode = 0o755 if name.endswith("apache2") else 0o644
            archive.addfile(item, io.BytesIO(content))
    return zstandard.ZstdCompressor().compress(stream.getvalue()) if zstd else stream.getvalue()


def deb(data_name="usr/sbin/apache2", zstd=False):
    control = b"Package: apache2-bin\nVersion: 1.2-3ubuntu1\nArchitecture: amd64\nSource: apache2\n"
    blobs = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", tar_blob([("control", control)])),
        (
            "data.tar.zst" if zstd else "data.tar.gz",
            tar_blob([(data_name, b"official binary")], zstd),
        ),
    ]
    raw = bytearray(b"!<arch>\n")
    for name, blob in blobs:
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(blob):<10}`\n".encode()
        assert len(header) == 60
        raw.extend(header + blob + (b"\n" if len(blob) % 2 else b""))
    return bytes(raw)


@pytest.mark.parametrize("zstd", [False, True])
def test_deb_uses_payload_hashes_without_extracting(zstd):
    metadata, files = inspect_deb(deb(zstd=zstd), "apache2-bin", "1.2-3ubuntu1", "amd64")
    assert metadata["Source"] == "apache2"
    assert files["/usr/sbin/apache2"]["sha256"] == hashlib.sha256(b"official binary").hexdigest()


@pytest.mark.parametrize("path", ["../../secret", "/absolute", "usr/../escape"])
def test_deb_rejects_path_escape(path):
    with pytest.raises(AppError):
        inspect_deb(deb(path), "apache2-bin", "1.2-3ubuntu1", "amd64")


def test_deb_rejects_different_package_identity():
    with pytest.raises(AppError) as error:
        inspect_deb(deb(), "apache2-bin", "9.9", "amd64")
    assert error.value.code == "PACKAGE_IDENTITY_MISMATCH"


def test_metadata_and_configuration_differences_do_not_become_unconditional_match():
    package = SimpleNamespace(
        package_id="test", binary_name="apache2-bin", binary_version="1", architecture="amd64"
    )
    expected = {"kind": "file", "sha256": "a" * 64, "mode": 0o755, "uid": 0, "gid": 0}
    artifact = {
        "proof": {},
        "files": {
            "/usr/sbin/apache2": expected,
            "/etc/apache2/apache2.conf": {**expected, "configuration": True},
        },
    }
    observations = {p: {**f, "status": "OK"} for p, f in artifact["files"].items()}
    observations["/etc/apache2/apache2.conf"]["sha256"] = "b" * 64
    assert compare_package(package, artifact, observations).status == "MATCH"
    modified = copy.deepcopy(observations)
    modified["/usr/sbin/apache2"]["mode"] = 0o777
    assert compare_package(package, artifact, modified).status == "DIFFERENT"
    modified["/usr/sbin/apache2"] = {"status": "UNREADABLE"}
    assert compare_package(package, artifact, modified).status == "UNAVAILABLE"
    assert compare_package(package, None, {}).status == "UNAVAILABLE"


def test_download_cannot_escape_allowlist_and_hash_mismatch_is_rejected(tmp_path):
    settings = Settings(
        _env_file=None, dev_api_token="x" * 32, package_cache_directory=str(tmp_path)
    )
    client = ArchiveClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"unexpected")),
    )
    try:
        for url in [
            "http://archive.ubuntu.com/ubuntu/file",
            "https://evil.invalid/file",
            "https://archive.ubuntu.com/ubuntu/../private",
        ]:
            with pytest.raises(AppError):
                client.fetch(url, 100)
        with pytest.raises(AppError) as failure:
            client.fetch("https://archive.ubuntu.com/ubuntu/a.deb", 100, "a" * 64)
        assert failure.value.code == "ARCHIVE_HASH_MISMATCH" and not list(tmp_path.glob("*.deb"))
    finally:
        client.close()
