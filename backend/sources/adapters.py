"""Normalize source facts without deriving an installed asset's verdict."""

import json
import re
from collections import defaultdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from backend.core.errors import AppError
from backend.sources.contracts import (
    CVE_PATTERN,
    CollectedDocument,
    Download,
    Metric,
    SecurityRecord,
)
from backend.sources.http import (
    APACHE_URL,
    KEV_MIRROR,
    KEV_URL,
    NVD_URL,
    OSV_URL,
    SourceHTTP,
    safe_reference,
)


def invalid():
    return AppError(
        "SOURCE_FORMAT_CHANGED", "자료 형식이 예상과 다릅니다. 이전 자료를 유지합니다.", 502
    )


def json_document(download: Download) -> dict:
    try:
        value = json.loads(download.text.lstrip("\ufeff"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, RecursionError):
        raise invalid() from None


def references(items: list) -> list[str]:
    return list(dict.fromkeys(url for item in items if (url := safe_reference(item.get("url")))))


def normalize_ubuntu(download: Download, release: str, package: str) -> list[SecurityRecord]:
    data = json_document(download)
    if set(data) - {"vulns", "next_page_token"} or not isinstance(data.get("vulns", []), list):
        raise invalid()
    records = []
    for entry in data.get("vulns", []):
        identifier = entry["id"]
        if not identifier.startswith("UBUNTU-CVE-"):
            continue  # USNs are not CVE records and cannot be substituted for one.
        cve = identifier.removeprefix("UBUNTU-")
        if not re.fullmatch(CVE_PATTERN, cve):
            raise invalid()
        matching = [
            item
            for item in entry["affected"]
            if item["package"]["ecosystem"] == f"Ubuntu:{release}:LTS"
            and item["package"]["name"] == package
        ]
        if not matching:
            continue
        ranges = [r for item in matching for r in item.get("ranges", [])]
        fixed = list(
            dict.fromkeys(e["fixed"] for r in ranges for e in r.get("events", []) if "fixed" in e)
        )
        conventional = (
            len(ranges) == 1
            and ranges[0].get("type") == "ECOSYSTEM"
            and (
                ranges[0].get("events") == [{"introduced": "0"}, {"fixed": fixed[0]}]
                if len(fixed) == 1
                else False
            )
        )
        notes = ["Ubuntu 패키지 기준 자료입니다. 자산의 영향 판정은 아직 실행하지 않았습니다."]
        if not conventional:
            notes.append(
                "단일 수정 기준으로 정리할 수 없는 범위입니다. 원문의 버전 범위를 확인하세요."
            )
        if not fixed:
            notes.append("수정 버전 미제공은 평가 대기·미수정 등의 상태를 포함할 수 있습니다.")
        priority = next(
            (s["score"] for s in entry.get("severity", []) if s["type"] == "Ubuntu"), None
        )
        metrics = [
            Metric(version=version.removeprefix("CVSS_"), vector=vector, provider="Ubuntu OSV")
            for version, vector in dict.fromkeys(
                (s["type"], s["score"])
                for s in entry.get("severity", [])
                if s["type"].startswith("CVSS")
            )
        ]
        records.append(
            SecurityRecord(
                cve_id=cve,
                title=cve,
                description=entry.get("details", ""),
                package_name=package,
                release=release,
                status="WITHDRAWN"
                if entry.get("withdrawn")
                else "FIX_AVAILABLE"
                if conventional
                else "UNKNOWN",
                fixed_version=fixed[0] if conventional and not entry.get("withdrawn") else None,
                ranges=ranges,
                affected_versions=list(
                    dict.fromkeys(v for item in matching for v in item.get("versions", []))
                ),
                metrics=metrics,
                priority=priority,
                references=list(
                    dict.fromkeys(
                        [
                            f"https://ubuntu.com/security/{cve}",
                            *references(entry.get("references", [])),
                        ]
                    )
                ),
                published_at=entry.get("published"),
                modified_at=entry.get("modified"),
                notes=notes,
            )
        )
    return records


def normalize_nvd(download: Download, cve: str) -> list[SecurityRecord]:
    data = json_document(download)
    if data.get("totalResults") == 0 and data.get("vulnerabilities") == []:
        return []
    if data.get("totalResults") != 1 or len(data.get("vulnerabilities", [])) != 1:
        raise invalid()
    entry = data["vulnerabilities"][0]["cve"]
    if entry["id"] != cve:
        raise invalid()
    metrics = []
    for metric_type, values in entry.get("metrics", {}).items():
        if not metric_type.startswith("cvssMetric"):
            continue
        for item in values:
            value = item.get("cvssData")
            if not isinstance(value, dict) or not value.get("version"):
                raise invalid()
            score = value.get("baseScore")
            if score is not None and (not isinstance(score, (int, float)) or not 0 <= score <= 10):
                raise invalid()
            metrics.append(
                Metric(
                    version=str(value.get("version", "unknown")),
                    vector=value.get("vectorString"),
                    score=score,
                    provider=item.get("source"),
                )
            )
    descriptions = entry.get("descriptions", [])
    description = next((d["value"] for d in descriptions if d["lang"] == "en"), "")
    return [
        SecurityRecord(
            cve_id=cve,
            title=cve,
            description=description,
            status="REJECTED" if entry.get("vulnStatus") == "Rejected" else "REFERENCE",
            metrics=metrics,
            weaknesses=list(
                dict.fromkeys(
                    d["value"]
                    for w in entry.get("weaknesses", [])
                    for d in w.get("description", [])
                )
            ),
            references=references(entry.get("references", [])),
            published_at=entry.get("published"),
            modified_at=entry.get("lastModified"),
            attributes={"NVD 상태": entry.get("vulnStatus", "미제공")},
            notes=[
                "NVD 점수·제품 정보는 보완 자료이며 Ubuntu 패키지의 수정 여부를 확정하지 않습니다."
            ],
        )
    ]


def normalize_kev(download: Download) -> list[SecurityRecord]:
    data = json_document(download)
    entries = data.get("vulnerabilities")
    if not isinstance(entries, list) or not entries or data.get("count") != len(entries):
        raise invalid()
    if not data.get("catalogVersion") or not data.get("dateReleased"):
        raise invalid()
    records = []
    seen = set()
    for entry in entries:
        cve = entry["cveID"]
        if cve in seen:
            raise invalid()
        seen.add(cve)
        records.append(
            SecurityRecord(
                cve_id=cve,
                title=entry["vulnerabilityName"],
                description=entry["shortDescription"],
                status="KNOWN_EXPLOITED",
                published_at=entry["dateAdded"],
                references=["https://www.cisa.gov/known-exploited-vulnerabilities-catalog"],
                weaknesses=entry.get("cwes", []),
                attributes={
                    "공급자": entry["vendorProject"],
                    "제품": entry["product"],
                    "CISA 권고 조치": entry["requiredAction"],
                    "CISA 조치 기한": entry.get("dueDate", "미제공"),
                    "랜섬웨어 악용 확인": entry.get("knownRansomwareCampaignUse", "Unknown"),
                    "카탈로그 버전": str(data["catalogVersion"]),
                },
                notes=[
                    entry.get("notes", ""),
                    "CISA의 조치 기한은 이 프로젝트 사용자의 조치 기한으로 자동 적용하지 않습니다.",
                ],
            )
        )
    return records


def normalize_apache(download: Download) -> list[SecurityRecord]:
    soup = BeautifulSoup(download.text, "html.parser")
    records = []
    for heading in soup.find_all("h3", id=re.compile(CVE_PATTERN)):
        term = heading.find_parent("dt")
        body = term.find_next_sibling("dd") if term else None
        if body is None:
            raise invalid()
        attributes = {}
        for row in body.select("table tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) == 2:
                attributes[cells[0].get_text(" ", strip=True)] = cells[1].get_text(" ", strip=True)
        fixed = next(
            (
                m.group(1)
                for key in attributes
                if (m := re.fullmatch(r"Update (\S+) released", key))
            ),
            None,
        )
        refs = [download.url + "#" + heading["id"]]
        refs.extend(urljoin(download.url, a["href"]) for a in body.find_all("a", href=True))
        records.append(
            SecurityRecord(
                cve_id=heading["id"],
                title=heading.get_text(" ", strip=True),
                description="\n".join(
                    p.get_text(" ", strip=True)
                    for p in body.find_all("p")
                    if p.get_text(strip=True)
                ),
                package_name="apache2",
                status="REFERENCE",
                upstream_fixed_version=fixed,
                references=[value for ref in refs if (value := safe_reference(ref))],
                attributes=attributes,
                notes=[
                    "Apache 제품 버전 기준입니다. "
                    "Ubuntu의 배포판 수정 버전과 별도로 해석해야 합니다."
                ],
            )
        )
    if not records:
        raise invalid()
    return records


def table_headers(table) -> list[str]:
    rows = table.select("thead tr")
    grid: dict[tuple[int, int], str] = {}
    for row_num, row in enumerate(rows):
        col = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            while (row_num, col) in grid:
                col += 1
            width, height = int(cell.get("colspan", 1)), int(cell.get("rowspan", 1))
            if not 1 <= width <= 30 or not 1 <= height <= 5:
                raise invalid()
            for y in range(height):
                for x in range(width):
                    grid[row_num + y, col + x] = cell.get_text(" ", strip=True)
            col += width
    return [value for (row, col), value in sorted(grid.items()) if row == len(rows) - 1]


def normalize_oracle(download: Download) -> list[SecurityRecord]:
    soup = BeautifulSoup(download.text, "html.parser")
    grouped = defaultdict(list)
    for table in soup.find_all("table"):
        heading = table.find_previous(["h2", "h3", "h4"])
        if heading is None or "MySQL" not in heading.get_text():
            continue
        headers = table_headers(table)
        if not headers or headers[0] != "CVE ID":
            continue
        for row in table.select("tbody tr"):
            cells = [
                cell.get_text(" ", strip=True)
                for cell in row.find_all(["td", "th"], recursive=False)
            ]
            if not cells or not re.fullmatch(CVE_PATTERN, cells[0]):
                continue
            if len(cells) != len(headers):
                raise invalid()
            grouped[cells[0]].append(dict(zip(headers, cells, strict=True)))
    if not grouped:
        raise invalid()
    return [
        SecurityRecord(
            cve_id=cve,
            title=f"Oracle MySQL 공지 · {cve}",
            status="REFERENCE",
            description="\n\n".join(
                "\n".join(f"{key}: {value}" for key, value in row.items()) for row in rows
            ),
            references=[download.url],
            attributes={
                "자료 범위": "선택한 Oracle 공지의 MySQL Risk Matrix",
                "관련 제품 행 수": str(len(rows)),
            },
            notes=[
                "MySQL Server·Cluster·Connectors 등 제품 조건을 구분해야 합니다. "
                "이 공지만으로 Ubuntu 패키지를 판정하지 않습니다."
            ],
        )
        for cve, rows in grouped.items()
    ]


def collect(source_id: str, parameters: dict, http: SourceHTTP) -> list[CollectedDocument]:
    try:
        if source_id == "ubuntu":
            documents = []
            tokens = set()
            token = None
            for _ in range(10):
                payload = {
                    "package": {
                        "ecosystem": f"Ubuntu:{parameters['release']}:LTS",
                        "name": parameters["package"],
                    }
                }
                if token:
                    payload["page_token"] = token
                download = http.fetch(OSV_URL, payload=payload)
                documents.append(
                    CollectedDocument(
                        download=download,
                        records=normalize_ubuntu(
                            download, parameters["release"], parameters["package"]
                        ),
                    )
                )
                token = json_document(download).get("next_page_token")
                if not token:
                    return documents
                if token in tokens:
                    raise invalid()
                tokens.add(token)
            raise AppError(
                "SOURCE_PAGE_LIMIT",
                "자료 페이지가 수집 제한을 초과했습니다. 이전 자료를 유지합니다.",
                502,
            )
        if source_id == "nvd":
            download = http.fetch(NVD_URL, params={"cveId": parameters["cve_id"]})
            records = normalize_nvd(download, parameters["cve_id"])
        elif source_id == "kev":
            try:
                download = http.fetch(KEV_URL)
            except AppError as error:
                if error.code not in {
                    "SOURCE_HTTP_ERROR",
                    "SOURCE_NETWORK_ERROR",
                    "SOURCE_TIMEOUT",
                }:
                    raise
                download = http.fetch(KEV_MIRROR)
            records = normalize_kev(download)
        elif source_id == "apache":
            download = http.fetch(APACHE_URL)
            records = normalize_apache(download)
        elif source_id == "oracle":
            download = http.fetch(parameters["url"])
            records = normalize_oracle(download)
        else:
            raise invalid()
        return [CollectedDocument(download=download, records=records)]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise invalid() from None
