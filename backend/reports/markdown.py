"""Deterministic Markdown rendering. All stored prose is data, never markup."""

import html
import re
import unicodedata
from datetime import timedelta, timezone
from urllib.parse import quote

from backend.reports.contracts import (
    COMPARISON_LABELS,
    KEV_LABELS,
    ORIGIN_LABELS,
    PROCESSING_LABELS,
    VERDICT_LABELS,
    ReportContent,
)
from backend.sources.http import safe_reference

KST = timezone(timedelta(hours=9), "KST")


def text(value) -> str:
    if value is None:
        return "미제공"
    value = " ".join(str(value).split())
    value = "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"})
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#!|~+-])", r"\\\1", value)


def link(label: str, url: str | None) -> str:
    if not safe_reference(url):
        return text(label) + " (주소 미제공)"
    return f"[{text(label)}](<{quote(url, safe='/:?=&%._~#@+-')}>)"


def time(value) -> str:
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST") if value else "미제공"


def render_markdown(report: ReportContent) -> str:
    lines = ["# CTI Agent 대응 보고서", ""]

    def paragraph(value):
        lines.extend([text(value), ""])

    def table(headers, rows):
        lines.append("| " + " | ".join(text(h) for h in headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in rows:
            lines.append("| " + " | ".join(text(cell) for cell in row) + " |")
        lines.append("")

    if report.is_synthetic:
        lines.extend(["> **가상 입력 보고서 — 실제 서버의 보안 상태가 아닙니다.**", ""])
    table(
        ["항목", "내용"],
        [
            ("대상 자산", report.asset_name),
            ("운영체제", f"{report.os.id} {report.os.version_id}"),
            ("예상 OS 릴리스", report.expected_release),
            ("아키텍처", report.os.architecture),
            ("패키지 확인 시각", time(report.collected_at)),
            ("패키지 입력 시각", time(report.ingested_at)),
            ("분석 완료 시각", time(report.analysis_completed_at)),
            ("보고서 자료 고정 시각", time(report.frozen_at)),
            ("보고서 생성 시각", time(report.generated_at)),
            (
                "입력 목록 상태",
                "전체 목록으로 선언" if report.package_list_complete else "부분 입력",
            ),
            (
                "AI Summary",
                f"{len(report.explanations)}건 포함"
                if report.include_ai_explanations
                else "미포함",
            ),
        ],
    )
    lines.extend(["## 분석 범위 및 제한 사항", ""])
    for warning in report.warnings:
        lines.append("- " + text(warning))
    lines.extend(["", "## 분석 요약", ""])
    table(
        ["집계", "건수"],
        [
            ("입력 패키지 수", report.summary.package_count),
            ("패키지별 전체 결과 수", report.summary.finding_count),
            ("중복을 제외한 CVE 수", report.summary.cve_count),
            ("KEV 등재 CVE 수 (중복 제외)", report.summary.kev_listed_cve_count),
        ],
    )
    paragraph(
        "동일 CVE가 여러 패키지에 연결되면 패키지별 결과 수는 CVE 수보다 큽니다. "
        "아래 집계는 패키지별 결과 기준입니다."
    )
    for heading, counts, labels in [
        ("버전 비교", report.summary.comparison_counts, COMPARISON_LABELS),
        ("최종 판단", report.summary.verdict_counts, VERDICT_LABELS),
        ("처리 상태", report.summary.processing_counts, PROCESSING_LABELS),
    ]:
        lines.extend([f"### {heading}", ""])
        table([heading, "건수"], [(labels[k], counts[k]) for k in labels])
    paragraph(
        "대조 자료 없음·지원 범위 밖·설치 여부 미확인 등의 처리 상태에는 "
        "취약 여부 판정값을 부여하지 않습니다."
    )
    lines.extend(["## 입력 패키지", ""])
    table(
        ["바이너리", "설치 버전", "소스 패키지", "소스 버전", "아키텍처", "출처 확인 수준"],
        [
            (
                p.binary_name,
                p.binary_version,
                p.source_name,
                p.source_version,
                p.architecture,
                ORIGIN_LABELS.get(p.origin_status, p.origin_status),
            )
            for p in report.packages
        ],
    )
    if report.verification:
        proof = report.verification
        lines.extend(["## 공식 패키지 파일 검증", ""])
        paragraph(f"검사 시각 {time(proof.checked_at)} · 검증기 {proof.verifier_version}")
        for warning in proof.warnings:
            paragraph(warning)
        if proof.apache_runtime_note:
            paragraph(proof.apache_runtime_note)
        if proof.apache_http2:
            runtime = proof.apache_http2
            paragraph(
                f"Apache HTTP/2 관측 시각 {time(runtime.observed_at)} · PID {runtime.main_pid}"
            )
            paragraph(
                f"로컬 관측 대상 {runtime.endpoint} · "
                f"HTTP/{runtime.http_version} · {runtime.http_status}"
            )
            paragraph(f"실행 파일 SHA-256 {runtime.executable_sha256}")
            paragraph(f"HTTP/2 모듈 SHA-256 {runtime.module_sha256}")
        table(
            ["패키지", "버전", "결과", "설명"],
            [(p.name, p.version, p.status, p.message) for p in proof.packages],
        )
        for package in proof.packages:
            if package.archive:
                paragraph(
                    f"{package.name} 공식 패키지 SHA-256: {package.archive.get('package_sha256')}"
                )
                lines.extend([link("공식 패키지", package.archive.get("package_url")), ""])
            table(
                ["파일", "검사", "공식 값", "조회 값"],
                [(f.path, f.status, f.expected, f.observed) for f in package.files],
            )
    lines.extend(["## CVE별 결과와 근거", ""])
    for index, finding in enumerate(report.findings, 1):
        lines.extend(
            [
                f"### {index}. {text(finding.package_name or '전체 입력')} / "
                f"{text(finding.cve_id or '패키지 처리 상태')}",
                "",
            ]
        )
        if finding.remediation:
            paragraph("대응 검토: " + finding.remediation.priority_reason)
            for step in finding.remediation.steps:
                paragraph(step.title + ": " + step.description)
                for url in step.evidence_urls:
                    lines.extend([link("대응 근거", url), ""])
        table(
            ["항목", "저장된 값"],
            [
                ("최종 판단", VERDICT_LABELS.get(finding.verdict, "판정 없음")),
                ("처리 상태", PROCESSING_LABELS[finding.processing_status]),
                ("버전 비교", COMPARISON_LABELS[finding.version_comparison]),
                ("바이너리 설치 버전", finding.binary_version),
                ("대조 기준", finding.comparison_basis),
                ("대조한 버전", finding.installed_version),
                ("소스 패키지", finding.source_package),
                ("Ubuntu 공식 수정 기준", finding.fixed_version),
                ("설치 출처", ORIGIN_LABELS.get(finding.origin_status, "미확인")),
                ("KEV", KEV_LABELS[finding.kev_status] if finding.cve_id else "해당 없음"),
                ("결과 ID", finding.finding_id),
                ("규칙 ID", finding.matched_rule_id),
            ],
        )
        for reason in finding.reasons:
            lines.append("- 판단 이유: " + text(reason))
        for limitation in finding.limitations:
            lines.append("- 제한 사항: " + text(limitation))
        lines.append("")
        if finding.nvd_metrics:
            table(
                ["CVSS 버전", "점수", "공급자", "벡터"],
                [(m.version, m.score, m.provider, m.vector) for m in finding.nvd_metrics],
            )
        else:
            paragraph("CVSS: 점수 미제공")
        if not finding.evidence_refs:
            paragraph("대조할 공식 근거가 없습니다. 안전을 의미하지 않습니다.")
        for evidence in finding.evidence_refs:
            lines.extend(
                [
                    "- 공식 근거: " + link(f"{evidence.source} · {evidence.title}", evidence.url),
                    "  - 원문 ID: " + text(evidence.document_version_id),
                    "  - 발췌: " + text(evidence.excerpt),
                    "",
                ]
            )
    lines.extend(["## AI Summary", ""])
    if not report.explanations:
        paragraph(
            "AI Summary 미포함"
            if not report.include_ai_explanations
            else "자료 고정 시점에 생성 완료된 AI Summary가 없습니다."
        )
    for index, explanation in enumerate(report.explanations, 1):
        result = explanation.result
        lines.extend(
            [f"### {index}. {text(result.facts.package_name)} / {text(result.facts.cve_id)}", ""]
        )
        table(
            ["항목", "값"],
            [
                ("요약 ID", explanation.id),
                ("결과 ID", explanation.finding_id),
                ("생성 시각", time(explanation.completed_at)),
                ("모델", explanation.model),
                ("서버 응답 모델", explanation.reported_model),
                ("생성 규칙", explanation.prompt_version),
                ("요약 입력 SHA-256", explanation.context_sha256),
            ],
        )
        lines.extend(["#### 취약점 개요 (AI 생성)", ""])
        paragraph(result.meaning.text)
        paragraph("인용: " + ", ".join(result.meaning.evidence_ids))
        lines.extend(["#### 패키지 분석 결과 (분석 원본)", ""])
        paragraph(result.assessment_text)
        for reason in result.assessment_reasons:
            lines.append("- " + text(reason))
        lines.extend(["", "#### 권고 조치 (AI 생성)", ""])
        for step in result.next_steps:
            lines.append(
                "- " + text(step.text) + " (인용: " + text(", ".join(step.evidence_ids)) + ")"
            )
        lines.extend(["", "#### 참조 근거", ""])
        for citation in result.citations:
            lines.extend(
                [
                    f"- {text(citation.id)}: " + link(citation.title, citation.url)
                    if citation.url
                    else f"- {text(citation.id)}: {text(citation.title)}",
                    "  - 기준 시각: " + time(citation.captured_at),
                    "  - 발췌: " + text(citation.excerpt),
                    "  - 원문 ID: " + text(citation.document_id),
                    "  - SHA-256: " + text(citation.sha256),
                ]
            )
        lines.append("")
        for warning in result.warnings:
            lines.append("- 제한 사항: " + text(warning))
        lines.append("")
    lines.extend(["## 분석에 사용한 공식 자료", ""])
    for source in report.sources:
        paragraph(
            f"{source.source_id} / {source.scope_key} · 수집 {time(source.captured_at)} · "
            f"기준본 {source.id} · 해석 버전 {source.adapter_version}"
        )
        for document in report.documents:
            if document.snapshot_id == source.id:
                lines.extend(
                    [
                        "- " + link("공식 수집 출처", document.url),
                        "  - 원문 ID: " + text(document.id),
                        "  - 수집 시각: " + time(document.captured_at),
                        "  - SHA-256: " + text(document.sha256),
                        "",
                    ]
                )
    if not report.sources:
        paragraph("분석에 사용한 공식 자료 기준본이 없습니다.")
    lines.extend(["## 재현 정보", ""])
    table(
        ["항목", "ID·버전"],
        [
            ("보고서 ID", report.report_id),
            ("분석 ID", report.analysis_id),
            ("패키지 입력 ID", report.inventory_id),
            ("판정용 자료 ID", report.feed_snapshot_id),
            ("판정 규칙", report.ruleset_version),
            ("보고서 양식", report.template_version),
        ],
    )
    paragraph(
        "이 보고서는 자료 고정 시점의 저장값으로 작성했습니다. "
        "이후 자료 갱신·재분석·AI 재생성은 이 보고서를 변경하지 않습니다."
    )
    return "\n".join(lines)
