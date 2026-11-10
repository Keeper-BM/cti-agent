"""Bounded requests to an explicit set of official public endpoints."""

import hashlib
import re
import time
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlsplit

import httpx

from backend.core.errors import AppError
from backend.sources.contracts import Download

OSV_URL = "https://api.osv.dev/v1/query"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
KEV_MIRROR = (
    "https://raw.githubusercontent.com/cisagov/kev-data/develop/"
    "known_exploited_vulnerabilities.json"
)
APACHE_URL = "https://httpd.apache.org/security/vulnerabilities_24.html"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
_nvd_lock = Lock()
_nvd_next_request = 0.0


def oracle_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise AppError("INVALID_SOURCE_URL", "Oracle 공식 공지 주소를 확인하세요.", 422) from None
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"www.oracle.com", "oracle.com"}
        or not re.fullmatch(r"/security-alerts/[a-z0-9-]+\.html", parsed.path)
        or parsed.query
    ):
        raise AppError(
            "INVALID_SOURCE_URL", "Oracle 공식 보안 공지의 HTTPS 주소를 사용하세요.", 422
        )
    return "https://www.oracle.com" + parsed.path


def safe_reference(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


class SourceHTTP:
    def __init__(self, api_key: str = "", transport=None):
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=httpx.Timeout(25, connect=10),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "Keeper-CTI-Agent/0.1 (academic security metadata client)"},
        )

    def close(self):
        self.client.close()

    def fetch(
        self, url: str, *, payload: dict | None = None, params: dict | None = None
    ) -> Download:
        if url not in {OSV_URL, NVD_URL, KEV_URL, KEV_MIRROR, APACHE_URL}:
            oracle_url(url)
        headers = {}
        if url == NVD_URL:
            global _nvd_next_request
            with _nvd_lock:
                time.sleep(max(0, _nvd_next_request - time.monotonic()))
                _nvd_next_request = time.monotonic() + (0.7 if self.api_key else 6.2)
            if self.api_key:
                headers["apiKey"] = self.api_key
        try:
            with self.client.stream(
                "POST" if payload is not None else "GET",
                url,
                json=payload,
                params=params,
                headers=headers,
            ) as response:
                if response.status_code == 429:
                    raise AppError(
                        "SOURCE_RATE_LIMIT",
                        "출처의 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.",
                        503,
                        True,
                    )
                if response.status_code != 200:
                    raise AppError(
                        "SOURCE_HTTP_ERROR",
                        f"공식 자료 요청이 실패했습니다 (HTTP {response.status_code}).",
                        503,
                        True,
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AppError(
                            "SOURCE_TOO_LARGE", "자료 크기가 수집 제한을 초과했습니다.", 502
                        )
                    data.extend(chunk)
                return Download(
                    url=str(response.url),
                    captured_at=datetime.now(UTC),
                    sha256=hashlib.sha256(data).hexdigest(),
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                    text=data.decode("utf-8"),
                )
        except httpx.TimeoutException:
            raise AppError(
                "SOURCE_TIMEOUT", "공식 자료 응답 시간이 초과되었습니다.", 503, True
            ) from None
        except (httpx.HTTPError, UnicodeError):
            raise AppError(
                "SOURCE_NETWORK_ERROR", "공식 자료 연결 또는 문자 인코딩을 확인하세요.", 503, True
            ) from None
