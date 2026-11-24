"""Coverage and source results from the inputs pinned to each workflow."""

from backend.models.enums import Verdict

SOURCE_LABELS = {
    "ubuntu": "Ubuntu CVE",
    "kev": "CISA KEV",
    "apache": "Apache HTTP Server",
    "nvd": "NVD",
    "oracle": "Oracle / MySQL",
}
SOURCE_OUTCOMES = {
    "UPDATED": "이번에 갱신",
    "CACHED": "갱신 실패 · 저장본 사용",
    "FAILED": "자료 미확보",
    "REUSED": "이전 분석의 기준본",
}

COVERAGE_LABELS = {
    "EVALUATED": "평가 결과 있음",
    "NO_TARGET": "평가 대상 없음",
    "NO_EVIDENCE": "평가 근거 부족",
}


def evaluated_pairs(summary):
    return sum(summary.get(verdict, 0) for verdict in Verdict)


def coverage(summary):
    if evaluated_pairs(summary):
        return "EVALUATED"
    if any(
        summary.get(status)
        for status in ("NO_MATCHING_RECORD", "PARTIAL_COLLECTION", "COLLECTION_FAILED")
    ):
        return "NO_EVIDENCE"
    return "NO_TARGET"


def batch_sources(assets):
    entries = {}
    for member, run, _ in assets:
        if run is None:
            continue
        for source in run.sources:
            status = source["status"]
            if status not in SOURCE_OUTCOMES:
                continue
            if member.carried and status == "UPDATED":
                status = "REUSED"
            key = (source["job_id"], status, source.get("snapshot_id"))
            entry = entries.setdefault(key, {**source, "status": status, "asset_names": []})
            entry["asset_names"].append(member.asset_name)
    return sorted(
        entries.values(),
        key=lambda item: (
            item["source"],
            item["scope"],
            item.get("captured_at") or "",
            item["status"],
        ),
    )
