import copy
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from backend.core.errors import AppError
from backend.sources.adapters import (
    normalize_apache,
    normalize_kev,
    normalize_nvd,
    normalize_oracle,
    normalize_ubuntu,
)
from backend.sources.contracts import Download
from backend.sources.http import APACHE_URL, NVD_URL, SourceHTTP, oracle_url
from tests.fixtures.security_sources import APACHE, CVE, KEV, NVD, ORACLE, UBUNTU


def download(value):
    text = value if isinstance(value, str) else json.dumps(value)
    return Download(
        url=APACHE_URL,
        captured_at=datetime.now(UTC),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        content_type="application/json",
        text=text,
    )


def test_ubuntu_release_source_package_ranges_and_provenance():
    record = normalize_ubuntu(download(UBUNTU), "22.04", "apache2")[0]
    assert record.cve_id == CVE
    assert record.fixed_version == "2.4.52-1ubuntu4.4"
    assert record.status == "FIX_AVAILABLE"
    assert record.metrics[0].score is None
    assert record.affected_versions == ["2.4.52-1ubuntu4.3"]
    assert normalize_ubuntu(download(UBUNTU), "24.04", "apache2") == []
    assert normalize_ubuntu(download(UBUNTU), "22.04", "mysql-8.0") == []


@pytest.mark.parametrize(
    "events",
    [
        [{"introduced": "0"}],
        [{"introduced": "1.0"}, {"fixed": "2.0"}],
        [{"introduced": "0"}, {"fixed": "2.0"}, {"introduced": "3.0"}, {"fixed": "4.0"}],
    ],
)
def test_ambiguous_ranges_do_not_invent_fixed_version(events):
    value = copy.deepcopy(UBUNTU)
    value["vulns"][0]["affected"][0]["ranges"][0]["events"] = events
    record = normalize_ubuntu(download(value), "22.04", "apache2")[0]
    assert record.fixed_version is None
    assert record.status == "UNKNOWN"
    assert record.ranges[0]["events"] == events


def test_withdrawn_record_cannot_become_a_fix_rule():
    value = copy.deepcopy(UBUNTU)
    value["vulns"][0]["withdrawn"] = "2026-11-09T00:00:00Z"
    result = normalize_ubuntu(download(value), "22.04", "apache2")[0]
    assert result.status == "WITHDRAWN" and result.fixed_version is None


def test_nvd_metrics_weaknesses_and_rejected_record():
    value = copy.deepcopy(NVD)
    value["vulnerabilities"][0]["cve"]["metrics"]["other"] = [{"ssvc": {"decision": "test"}}]
    result = normalize_nvd(download(value), CVE)[0]
    assert result.metrics[0].score == 9.8
    assert len(result.metrics) == 1
    assert result.weaknesses == ["CWE-444"]
    assert result.references == ["https://example.invalid/reference"]
    assert result.fixed_version is None
    value["vulnerabilities"][0]["cve"]["vulnStatus"] = "Rejected"
    assert normalize_nvd(download(value), CVE)[0].status == "REJECTED"
    with pytest.raises(AppError):
        normalize_nvd(download(value), "CVE-2099-9999")


def test_kev_requires_complete_catalog():
    result = normalize_kev(download(KEV))[0]
    assert result.status == "KNOWN_EXPLOITED"
    broken = {**KEV, "count": 2}
    with pytest.raises(AppError):
        normalize_kev(download(broken))


def test_vendor_conditions_preserved_separately_from_ubuntu_versions():
    apache = normalize_apache(download(APACHE))[0]
    assert apache.upstream_fixed_version == "2.4.56"
    assert apache.fixed_version is None
    assert "configuration" in apache.description
    oracle = normalize_oracle(download(ORACLE))[0]
    assert "MySQL Server" in oracle.description and "MySQL Cluster" in oracle.description
    assert oracle.fixed_version is None
    for parser in [normalize_oracle, normalize_apache]:
        with pytest.raises(AppError):
            parser(download("<html>site unavailable</html>"))


@pytest.mark.parametrize(
    "url",
    [
        "http://www.oracle.com/security-alerts/cpujan2024.html",
        "https://www.oracle.com.evil.test/security-alerts/cpujan2024.html",
        "https://localhost/security-alerts/cpujan2024.html",
        "https://www.oracle.com:123/security-alerts/cpujan2024.html",
        "https://www.oracle.com/security-alerts/../file.html",
        "https://[broken",
    ],
)
def test_oracle_url_is_restricted(url):
    with pytest.raises(AppError):
        oracle_url(url)


def test_http_raw_hash_limits_redirects_and_headers(monkeypatch):
    monkeypatch.setattr("backend.sources.http._nvd_next_request", 0)
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, content=b'\xef\xbb\xbf{"example":1}')

    http = SourceHTTP("secret-test-key", transport=httpx.MockTransport(respond))
    result = http.fetch(NVD_URL, params={"cveId": CVE})
    assert result.sha256 == hashlib.sha256(result.text.encode()).hexdigest()
    assert seen[-1].headers["apikey"] == "secret-test-key"
    http.fetch(APACHE_URL)
    assert "apikey" not in seen[-1].headers
    http.close()
    monkeypatch.setattr("backend.sources.http.MAX_RESPONSE_BYTES", 4)
    http = SourceHTTP(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"12345"))
    )
    with pytest.raises(AppError, match="크기"):
        http.fetch(APACHE_URL)
    http.close()
    http = SourceHTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://localhost/"})
        )
    )
    with pytest.raises(AppError):
        http.fetch(APACHE_URL)
    http.close()
