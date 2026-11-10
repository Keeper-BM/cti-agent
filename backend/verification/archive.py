"""Ubuntu InRelease -> Packages SHA-256 -> .deb SHA-256 -> file manifest."""

import hashlib
import io
import lzma
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.core.errors import AppError
from backend.verification.contracts import PACKAGES, RELEASES
from backend.verification.deb import inspect_deb, parse_fields

FINGERPRINT = "F6ECB3762474EDA9D21B7022871920D1991BC93C"
ARCHIVE = "https://archive.ubuntu.com/ubuntu/"
MAX_DEB = 128 * 1024 * 1024
MAX_INDEX = 16 * 1024 * 1024


def gpg_executable(settings):
    binary = settings.gpg_binary or shutil.which("gpg")
    if not binary and os.name == "nt":
        candidate = Path("C:/Program Files/Git/usr/bin/gpg.exe")
        binary = str(candidate) if candidate.is_file() else None
    if not binary or not Path(binary).is_file():
        raise AppError("VERIFIER_NOT_CONFIGURED", "백엔드에 GnuPG 실행 파일을 준비하세요.", 409)
    return binary


def verify_signature(data, settings, cache_root):
    binary = gpg_executable(settings)
    msys = os.name == "nt" and "/git/usr/bin/" in binary.replace("\\", "/").lower()

    def arg(path):
        value = Path(path).resolve()
        return "/" + value.drive[0].lower() + value.as_posix()[2:] if msys else str(value)

    # Every temporary path and automatic cleanup stays inside the configured cache.
    with tempfile.TemporaryDirectory(prefix="gpg-", dir=cache_root) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(Path(cache_root).resolve())
        signed, plain = root / "InRelease", root / "Release"
        signed.write_bytes(data)
        base = [binary, "--batch", "--no-tty", "--no-options", "--homedir", arg(root)]
        public = Path(__file__).with_name("ubuntu-archive-2018.asc")
        try:
            imported = subprocess.run(
                [*base, "--import", arg(public)], capture_output=True, timeout=15
            )
            if imported.returncode:
                raise ValueError()
            result = subprocess.run(
                [
                    *base,
                    "--no-auto-key-retrieve",
                    "--auto-key-locate",
                    "clear",
                    "--status-fd",
                    "1",
                    "--output",
                    arg(plain),
                    "--decrypt",
                    arg(signed),
                ],
                capture_output=True,
                timeout=20,
            )
            status = result.stdout.decode("utf-8", "replace")
            valid = re.findall(r"\[GNUPG:\] VALIDSIG ([A-F0-9]{40}) ", status)
            if (
                result.returncode
                or valid != [FINGERPRINT]
                or any(
                    code in status
                    for code in ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG")
                )
            ):
                raise ValueError()
            return plain.read_text(encoding="utf-8")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise AppError(
                "ARCHIVE_SIGNATURE_INVALID", "Ubuntu 저장소 서명을 확인하지 못했습니다.", 502
            ) from None


class ArchiveClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.root = Path(settings.package_cache_directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.deadline = time.monotonic() + 300
        self.http = httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "CTI-Agent/0.1 package verification"},
        )

    def close(self):
        self.http.close()

    def fetch(self, url, limit, expected=None, size=None):
        if time.monotonic() >= self.deadline:
            raise AppError("ARCHIVE_LIMIT", "공식 패키지 조회의 전체 제한 시간이 지났습니다.", 502)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "archive.ubuntu.com"
            or not parsed.path.startswith("/ubuntu/")
            or parsed.query
            or parsed.fragment
            or ".." in parsed.path.split("/")
        ):
            raise AppError("ARCHIVE_URL_INVALID", "허용하지 않은 패키지 저장소 주소입니다.", 502)
        if expected and not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise AppError("ARCHIVE_HASH_INVALID", "공식 해시 형식을 확인할 수 없습니다.", 502)
        suffix = ".deb" if parsed.path.endswith(".deb") else ".index"
        cached = self.root / (expected + suffix) if expected else None
        if cached and cached.is_file() and not cached.is_symlink():
            if cached.stat().st_size <= limit:
                value = cached.read_bytes()
                if hashlib.sha256(value).hexdigest() == expected and (
                    size is None or len(value) == size
                ):
                    return value
        budget = self.settings.package_cache_mib * 1024 * 1024
        entries = [
            p
            for p in self.root.iterdir()
            if re.fullmatch(r"[a-f0-9]{64}\.(deb|index)", p.name)
            and p.is_file()
            and not p.is_symlink()
        ]
        used = sum(p.stat().st_size for p in entries)
        needed = size if size is not None else limit
        # Retain content-addressed evidence instead of silently evicting historical inputs.
        if used + needed > budget or shutil.disk_usage(self.root).free < needed + 64 * 1024 * 1024:
            raise AppError(
                "PACKAGE_CACHE_FULL", "검증 캐시 드라이브에 여유 공간이 부족합니다.", 409
            )
        started = time.monotonic()
        output = self._download(url, limit, started)
        value = bytes(output)
        if (expected and hashlib.sha256(value).hexdigest() != expected) or (
            size is not None and len(value) != size
        ):
            raise AppError(
                "ARCHIVE_HASH_MISMATCH", "공식 자료의 크기 또는 해시가 일치하지 않습니다.", 502
            )
        if cached:
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix="download-", delete=False
            ) as stream:
                temp = Path(stream.name)
                stream.write(value)
            try:
                os.replace(temp, cached)
            finally:
                if temp.exists():
                    temp.unlink()
        return value

    def _download(self, url, limit, started):
        for attempt in range(3):
            if time.monotonic() >= self.deadline:
                break
            try:
                with self.http.stream("GET", url) as response:
                    if response.status_code in {429, 502, 503, 504} and attempt < 2:
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    if response.status_code != 200:
                        raise AppError(
                            "ARCHIVE_DOWNLOAD_FAILED",
                            "공식 패키지 자료를 가져오지 못했습니다.",
                            503,
                        )
                    output = bytearray()
                    for chunk in response.iter_bytes():
                        if (
                            len(output) + len(chunk) > limit
                            or time.monotonic() - started > 120
                            or time.monotonic() >= self.deadline
                        ):
                            raise AppError(
                                "ARCHIVE_LIMIT",
                                "공식 자료의 크기·조회 시간 제한을 초과합니다.",
                                502,
                            )
                        output.extend(chunk)
                    return output
            except (httpx.HTTPError, OSError):
                if attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
        raise AppError("ARCHIVE_DOWNLOAD_FAILED", "공식 패키지 자료 연결을 확인하세요.", 503)

    def index(self, codename, pocket):
        url = ARCHIVE + "dists/" + pocket + "/InRelease"
        signed = self.fetch(url, 2 * 1024 * 1024)
        fields = parse_fields(verify_signature(signed, self.settings, self.root))
        try:
            if (
                fields["Origin"] != "Ubuntu"
                or fields["Codename"] != codename
                or fields["Suite"] != pocket
            ):
                raise ValueError()
            issued = parsedate_to_datetime(fields["Date"])
            now = datetime.now(UTC)
            if issued.tzinfo is None or issued > now + timedelta(hours=24):
                raise ValueError()
            if "Valid-Until" in fields and parsedate_to_datetime(fields["Valid-Until"]) < now:
                raise ValueError()
            hashes = {
                line.split()[2]: (line.split()[0], int(line.split()[1]))
                for line in fields["SHA256"].splitlines()
                if line.strip()
            }
            name = "main/binary-amd64/Packages.xz"
            digest, size = hashes[name]
            if not 0 < size <= MAX_INDEX:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise AppError(
                "ARCHIVE_METADATA_INVALID",
                "저장소 릴리스·시각·해시 정보를 확인할 수 없습니다.",
                502,
            ) from None
        index_url = ARCHIVE + "dists/" + pocket + "/" + name
        blob = self.fetch(index_url, MAX_INDEX, digest, size)
        proof = {
            "pocket": pocket,
            "inrelease_url": url,
            "inrelease_sha256": hashlib.sha256(signed).hexdigest(),
            "signed_inrelease": signed.decode("utf-8"),
            "signer": FINGERPRINT,
            "index_url": index_url,
            "index_sha256": digest,
            "published_at": issued.isoformat(),
        }
        return blob, proof

    def resolve(self, inventory):
        if inventory.os.version_id not in RELEASES or inventory.os.architecture != "amd64":
            raise AppError(
                "VERIFICATION_OUT_OF_SCOPE",
                "현재 공식 파일 검증은 Ubuntu 22.04·24.04 amd64를 지원합니다.",
                422,
            )
        targets = {
            (p.binary_name, p.binary_version, p.architecture): p
            for p in inventory.packages
            if p.binary_name in PACKAGES and p.install_status == "installed"
        }
        if len(targets) > 20:
            raise AppError("VERIFICATION_LIMIT", "검증 대상 패키지 수가 제한을 초과합니다.", 422)
        found = {}
        codename = RELEASES[inventory.os.version_id]
        for pocket in (codename + "-security", codename + "-updates", codename):
            compressed, proof = self.index(codename, pocket)
            try:
                with lzma.LZMAFile(io.BytesIO(compressed)) as stream:
                    buffer, total = [], 0
                    for line in io.TextIOWrapper(stream, encoding="utf-8"):
                        total += len(line)
                        if total > 96 * 1024 * 1024 or len(line) > 1024 * 1024:
                            raise ValueError()
                        if line.strip():
                            buffer.append(line.rstrip("\n"))
                            continue
                        if buffer:
                            record = parse_fields("\n".join(buffer))
                            identity = (
                                record.get("Package"),
                                record.get("Version"),
                                record.get("Architecture"),
                            )
                            if identity in targets:
                                self._record(found, identity, record, proof)
                            buffer = []
                    if buffer:
                        record = parse_fields("\n".join(buffer))
                        identity = (
                            record.get("Package"),
                            record.get("Version"),
                            record.get("Architecture"),
                        )
                        if identity in targets:
                            self._record(found, identity, record, proof)
            except (OSError, lzma.LZMAError, UnicodeError, ValueError):
                raise AppError(
                    "ARCHIVE_METADATA_INVALID", "공식 패키지 목록 형식을 확인하지 못했습니다.", 502
                ) from None
        resolved = {}
        for identity, (record, proof) in found.items():
            filename = record.get("Filename", "")
            if not re.fullmatch(
                r"pool/main/[A-Za-z0-9+._~/-]+\.deb", filename
            ) or ".." in filename.split("/"):
                raise AppError(
                    "ARCHIVE_URL_INVALID", "공식 패키지 파일 경로가 올바르지 않습니다.", 502
                )
            try:
                size = int(record["Size"])
                if not 0 < size <= MAX_DEB:
                    raise ValueError()
            except (KeyError, ValueError):
                raise AppError(
                    "ARCHIVE_LIMIT", "공식 패키지 크기가 허용 범위를 벗어납니다.", 502
                ) from None
            blob = self.fetch(ARCHIVE + filename, MAX_DEB, record.get("SHA256"), size)
            fields, files = inspect_deb(blob, *identity)
            source = fields.get("Source", fields["Package"])
            match = re.fullmatch(r"([a-z0-9+.-]+)(?: \(([^()]+)\))?", source)
            if not match:
                raise AppError(
                    "PACKAGE_IDENTITY_MISMATCH", "공식 소스 패키지 대응을 확인할 수 없습니다.", 502
                )
            installed = targets[identity]
            source_version = match.group(2) or fields["Version"]
            if (
                installed.source_name != match.group(1)
                or installed.source_version != source_version
            ):
                raise AppError(
                    "PACKAGE_IDENTITY_MISMATCH",
                    "서버의 소스 패키지 정보가 공식 자료와 다릅니다.",
                    502,
                )
            resolved[str(installed.package_id)] = {
                "files": files,
                "proof": {
                    **proof,
                    "package_url": ARCHIVE + filename,
                    "package_sha256": record["SHA256"],
                    "source_name": match.group(1),
                    "source_version": source_version,
                    "package_size": size,
                },
            }
        return resolved

    @staticmethod
    def _record(found, identity, record, proof):
        if not re.fullmatch(r"[a-f0-9]{64}", record.get("SHA256", "")):
            raise AppError("ARCHIVE_HASH_INVALID", "공식 패키지 해시가 누락됐습니다.", 502)
        if identity in found and found[identity][0]["SHA256"] != record["SHA256"]:
            raise AppError("ARCHIVE_CONFLICT", "같은 패키지 버전의 공식 해시가 상충합니다.", 502)
        found[identity] = (record, proof)
