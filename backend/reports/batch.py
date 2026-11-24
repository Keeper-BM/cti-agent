"""Render the consolidated report from each selected workflow's exact analysis."""

from datetime import datetime
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import load_only

from backend.api.schemas.workflow_batches import BatchPriority, BatchReportSummary
from backend.assessment.contracts import AssessmentFinding
from backend.assessment.remediation import cvss_score, response_order
from backend.models.tables import FindingRecord, InventoryRecord, ReportRun, utcnow
from backend.reports.contracts import (
    COMPARISON_LABELS,
    PROCESSING_LABELS,
    VERDICT_LABELS,
    ReportExplanation,
)
from backend.reports.markdown import append_table, link, text, time
from backend.reports.snapshot import aware
from backend.workflows.evidence import (
    COVERAGE_LABELS,
    SOURCE_LABELS,
    SOURCE_OUTCOMES,
    batch_sources,
    coverage,
    evaluated_pairs,
)

PRIORITY_LIMIT = 12


def cve_sections(db, analyses):
    query = (
        select(FindingRecord.cve_id, FindingRecord.payload)
        .where(FindingRecord.analysis_id.in_(analyses), FindingRecord.cve_id.is_not(None))
        .order_by(
            FindingRecord.cve_id,
            FindingRecord.analysis_id,
            FindingRecord.package_name,
            FindingRecord.id,
        )
        .execution_options(yield_per=256)
    )
    lines = []
    cve_count = affected_cve_count = priority_total = 0
    priorities, attention = [], set()
    for cve_id, group in groupby(db.execute(query), lambda record: record.cve_id):
        lines.extend([f"### {text(cve_id)}", ""])
        rows, evidence, preferred = [], {}, {}
        evaluated = False
        for record in group:
            finding = AssessmentFinding.model_validate(record.payload)
            evaluated |= finding.verdict is not None
            asset = analyses[str(finding.analysis_id)]
            refs = []
            for item in finding.evidence_refs:
                key = item.source, item.url, item.document_version_id
                if key not in evidence:
                    evidence[key] = (len(evidence) + 1, item.title, item.excerpt)
                refs.append(str(evidence[key][0]))
            rows.append(
                (
                    asset.asset_name,
                    finding.package_name,
                    finding.binary_version,
                    finding.installed_version,
                    finding.fixed_version,
                    COMPARISON_LABELS[finding.version_comparison],
                    VERDICT_LABELS.get(
                        finding.verdict, PROCESSING_LABELS[finding.processing_status]
                    ),
                    finding.reasons[-1] if finding.reasons else None,
                    ", ".join(dict.fromkeys(refs)) or None,
                )
            )
            if finding.verdict in {"AFFECTED", "NEEDS_REVIEW"}:
                steps = finding.remediation.steps if finding.remediation else []
                item = BatchPriority(
                    asset_id=asset.asset_id,
                    cve_id=cve_id,
                    package_name=finding.package_name or "패키지 미확인",
                    verdict=finding.verdict,
                    kev_listed=finding.kev_status == "LISTED",
                    next_step=f"{steps[0].title} · {steps[0].description}" if steps else None,
                    finding_id=finding.finding_id,
                    cvss_score=cvss_score(finding),
                    priority_reason=finding.remediation.priority_reason
                    if finding.remediation
                    else None,
                )
                rank = response_order(finding)
                current = preferred.get(asset.asset_id)
                if current is None or rank < current[0]:
                    preferred[asset.asset_id] = (rank, item)
        append_table(
            lines,
            [
                "자산",
                "패키지",
                "설치 버전",
                "대조 버전",
                "수정 기준",
                "버전 비교",
                "판정",
                "판정 이유",
                "근거",
            ],
            rows,
        )
        for (source, url, doc_id), (number, title, excerpt) in evidence.items():
            lines.append(f"- 근거 {number} · " + link(f"{source} · {title}", url))
            lines.append("  - 원문 ID " + text(doc_id))
            if excerpt:
                lines.append("  - " + text(excerpt))
        lines.append("")
        cve_count += evaluated
        affected_cve_count += any(item.verdict == "AFFECTED" for _, item in preferred.values())
        priority_total += len(preferred)
        attention.update(preferred)
        priorities = sorted([*priorities, *preferred.values()], key=lambda entry: entry[0])[
            :PRIORITY_LIMIT
        ]
    return lines, BatchReportSummary(
        cve_count=cve_count,
        affected_cve_count=affected_cve_count,
        attention_asset_count=len(attention),
        priority_total=priority_total,
        priorities=[item for _, item in priorities],
    )


def append_asset_details(lines, db, assets):
    lines.extend(["## 수집 범위와 분석 기록", ""])
    for member, run, analysis in assets:
        lines.extend([f"### {text(member.asset_name)}", ""])
        if not analysis:
            cause = member.start_error or (run.error if run else None)
            lines.extend([text(cause or "분석 결과를 확보하지 못했습니다."), ""])
            continue
        inventory = db.get(
            InventoryRecord,
            analysis.inventory_id,
            options=[
                load_only(
                    InventoryRecord.package_count,
                    InventoryRecord.collected_at,
                    InventoryRecord.collection_status,
                )
            ],
        )
        append_table(
            lines,
            ["항목", "기록"],
            [
                ("패키지 수", inventory.package_count),
                ("수집 시각", time(aware(inventory.collected_at))),
                (
                    "수집 상태",
                    {"COMPLETE": "완료", "PARTIAL": "일부 수집"}.get(
                        inventory.collection_status, "실패"
                    ),
                ),
                ("분석 시각", time(aware(analysis.completed_at))),
                ("분석 ID", analysis.id),
                ("수집 기록 ID", analysis.inventory_id),
            ],
        )
        for warning in analysis.warnings:
            lines.append("- " + text(warning))
        lines.append("")
        report_body = (
            db.scalar(select(ReportRun.content).where(ReportRun.id == run.report_id))
            if run.report_id
            else None
        ) or {}
        explanations = report_body.get("explanations", [])
        if explanations:
            lines.extend(["#### AI Summary", ""])
            for payload in explanations:
                summary = ReportExplanation.model_validate(payload)
                result = summary.result
                model = summary.reported_model or summary.model
                lines.extend(
                    [
                        text(f"{result.facts.cve_id} · {result.facts.package_name} · {model}"),
                        "",
                        text(result.meaning.text),
                        "",
                    ]
                )
                for step in result.next_steps:
                    lines.append(
                        "- " + text(step.text) + " (" + text(", ".join(step.evidence_ids)) + ")"
                    )
                for evidence in result.citations:
                    lines.append(
                        "- " + text(evidence.id) + " · " + link(evidence.title, evidence.url)
                    )
                lines.append("")
        elif run.error or report_body.get("ai_summary_note"):
            lines.extend([text(report_body.get("ai_summary_note") or run.error), ""])


def build_batch_report(db, batch, assets):
    analyses = {analysis.id: member for member, _, analysis in assets if analysis}
    names = {member.asset_id: member.asset_name for member, _, _ in assets}
    details, summary = cve_sections(db, analyses)
    states = {
        member.asset_id: coverage(analysis.summary or {}) if analysis else "FAILED"
        for member, _, analysis in assets
    }
    assessed = sum(state == "EVALUATED" for state in states.values())
    unassessed = sum(state in {"NO_TARGET", "NO_EVIDENCE"} for state in states.values())
    failed = len(assets) - assessed - unassessed
    lines = [
        "# CTI Agent 통합 대응 보고서",
        "",
        f"선택 {len(assets)}대 · 평가 결과 있음 {assessed}대"
        f" · 미평가 {unassessed}대 · 분석 실패 {failed}대",
        "",
        f"평가한 CVE {summary.cve_count}개 · "
        + (
            f"영향 확인 CVE {summary.affected_cve_count}개"
            if summary.cve_count
            else "영향 확인 결과 없음"
        ),
        "",
        "분석 종료 " + time(aware(batch.finished_at)),
        "",
        "보고서 생성 " + time(utcnow()),
        "",
        "일괄 분석 ID " + text(batch.id),
        "",
    ]
    if batch.parent_id:
        lines.extend(["이전 일괄 분석 ID " + text(batch.parent_id), ""])
    append_sources(lines, assets)
    if summary.priorities:
        lines.extend(
            [
                "## 우선 대응",
                "",
                "영향 있음, KEV 등재, 확인된 CVSS 점수 내림차순, CVE 번호 순으로 정렬합니다.",
                "",
            ]
        )
        if summary.priority_total > len(summary.priorities):
            lines.extend(
                [
                    f"우선 대응 대상 {summary.priority_total}건 중 상위 "
                    f"{len(summary.priorities)}건입니다. "
                    "전체 판정은 CVE별 표에서 확인할 수 있습니다.",
                    "",
                ]
            )
        append_table(
            lines,
            ["자산", "CVE", "패키지", "판정", "KEV·CVSS", "우선 검토 근거", "권고 조치"],
            [
                (
                    names[str(item.asset_id)],
                    item.cve_id,
                    item.package_name,
                    VERDICT_LABELS[item.verdict],
                    ("KEV 등재 · " if item.kev_listed else "")
                    + (
                        f"CVSS {item.cvss_score:g}"
                        if item.cvss_score is not None
                        else "CVSS 점수 없음"
                    ),
                    item.priority_reason,
                    item.next_step,
                )
                for item in summary.priorities
            ],
        )
    lines.extend(["## 선택 자산", ""])
    append_table(
        lines,
        ["자산", "평가 상태", "Ubuntu", "평가한 조합", "영향 있음", "추가 확인 필요", "참고"],
        [
            (
                member.asset_name,
                COVERAGE_LABELS[states[member.asset_id]] if analysis else "분석 실패",
                analysis.os_release if analysis else None,
                evaluated_pairs(analysis.summary or {}) if analysis else None,
                (analysis.summary or {}).get("AFFECTED", 0)
                if states[member.asset_id] == "EVALUATED"
                else None,
                (analysis.summary or {}).get("NEEDS_REVIEW", 0)
                if states[member.asset_id] == "EVALUATED"
                else None,
                " · ".join(
                    filter(
                        None,
                        (
                            "이전 실행 결과 재사용" if member.carried else None,
                            "가상 입력" if analysis and analysis.is_synthetic else None,
                            "개별 보고서 생성 실패" if analysis and run.error else None,
                            member.start_error or (run.error if not analysis and run else None),
                        ),
                    )
                )
                or "—",
            )
            for member, run, analysis in assets
        ],
    )
    lines.extend(
        [
            "자산별 건수는 패키지·CVE 조합 수입니다. 상단 CVE 수는 자산 간 중복을 제거한 값입니다.",
            "",
            "## CVE별 자산 판정과 공식 근거",
            "",
        ]
    )
    lines.extend(
        details or ["확인된 CVE별 판정이 없습니다. 자산별 수집 범위와 실패 사유를 확인하세요.", ""]
    )
    append_asset_details(lines, db, assets)
    return summary.model_dump(mode="json"), "\n".join(lines)


def append_sources(lines, assets):
    sources = batch_sources(assets)
    lines.extend(["## 공식 자료 조회 결과", ""])
    if not sources:
        lines.extend(["이번 실행에서 완료된 공식 자료 조회가 없습니다.", ""])
        return
    append_table(
        lines,
        ["출처", "범위", "조회 결과", "기준 시각 (KST)", "기준본 ID", "자산"],
        [
            (
                SOURCE_LABELS.get(item["source"], item["source"]),
                item["scope"],
                SOURCE_OUTCOMES[item["status"]],
                time(aware(datetime.fromisoformat(item["captured_at"])))
                if item.get("captured_at")
                else None,
                item.get("snapshot_id"),
                ", ".join(item["asset_names"]),
            )
            for item in sources
        ],
    )
