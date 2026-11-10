"""Freeze report facts at submission. No model, collection or external request."""

import hashlib
import json
from collections import Counter
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import defer

from backend.api.schemas.sources import DocumentInfo, SnapshotResponse
from backend.assessment.contracts import AssessmentFinding
from backend.core.errors import AppError
from backend.llm.contracts import ExplanationResult
from backend.models.contracts import InventorySnapshot
from backend.models.tables import (
    ExplanationRun,
    FindingRecord,
    InventoryRecord,
    Job,
    SecuritySnapshot,
    SourceDocument,
    VerificationRun,
)
from backend.reports.contracts import (
    COMPARISON_LABELS,
    MAX_REPORT_BYTES,
    PROCESSING_LABELS,
    TEMPLATE_VERSION,
    VERDICT_LABELS,
    ReportContent,
    ReportExplanation,
    ReportPackage,
    ReportSummary,
)
from backend.verification.contracts import VerificationEvidence


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def digest(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(data.encode("utf-8")) > MAX_REPORT_BYTES:
        raise AppError("REPORT_SIZE_LIMIT", "보고서 내용이 16 MiB 제한을 초과합니다.", 422)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def freeze_report(db, analysis, report_id, frozen_at, include_ai: bool) -> ReportContent:
    inventory = InventorySnapshot.model_validate(
        db.get(InventoryRecord, analysis.inventory_id).payload
    )
    verification = None
    if inventory.verification_id:
        run = db.get(VerificationRun, str(inventory.verification_id))
        if not run or run.verified_inventory_id != analysis.inventory_id or not run.evidence:
            raise AppError("REPORT_VERIFICATION_MISSING", "패키지 검증 근거가 누락됐습니다.", 409)
        verification = VerificationEvidence.model_validate(run.evidence)
    findings = [
        AssessmentFinding.model_validate(row.payload)
        for row in db.scalars(
            select(FindingRecord)
            .where(FindingRecord.analysis_id == analysis.id)
            .order_by(FindingRecord.cve_id, FindingRecord.package_name, FindingRecord.id)
        )
    ]
    if not findings or len(findings) != (analysis.summary or {}).get("TOTAL"):
        raise AppError("REPORT_INPUT_INVALID", "분석 결과의 완전성을 확인할 수 없습니다.", 409)
    if any(
        str(f.inventory_id) != analysis.inventory_id
        or str(f.asset_id) != analysis.asset_id
        or str(f.analysis_id) != analysis.id
        for f in findings
    ):
        raise AppError("REPORT_INPUT_INVALID", "분석 결과의 입력 범위가 일치하지 않습니다.", 409)
    sources = list(
        db.scalars(
            select(SecuritySnapshot)
            .where(SecuritySnapshot.id.in_(analysis.source_snapshot_ids))
            .order_by(SecuritySnapshot.source_id, SecuritySnapshot.scope_key)
        )
    )
    if {s.id for s in sources} != set(analysis.source_snapshot_ids):
        raise AppError("REPORT_SOURCE_MISSING", "분석 당시의 자료 기준본이 누락되었습니다.", 409)
    documents = list(
        db.scalars(
            select(SourceDocument)
            .options(defer(SourceDocument.raw_text))
            .where(SourceDocument.snapshot_id.in_(analysis.source_snapshot_ids))
            .order_by(SourceDocument.snapshot_id, SourceDocument.id)
        )
    )
    doc_ids = {d.id for d in documents}
    if any(str(e.document_version_id) not in doc_ids for f in findings for e in f.evidence_refs):
        raise AppError("REPORT_SOURCE_MISSING", "판정의 원문 참조가 누락되었습니다.", 409)
    explanations = []
    if include_ai:
        candidates = db.scalars(
            select(ExplanationRun)
            .options(defer(ExplanationRun.input_payload))
            .join(Job, Job.id == ExplanationRun.job_id)
            .where(
                ExplanationRun.analysis_id == analysis.id,
                ExplanationRun.completed_at.is_not(None),
                Job.status == "SUCCEEDED",
            )
            .order_by(ExplanationRun.completed_at.desc(), ExplanationRun.id.desc())
        )
        seen, by_id = set(), {str(f.finding_id): f for f in findings}
        for run in candidates:
            if run.finding_id in seen:
                continue
            seen.add(run.finding_id)
            result = ExplanationResult.model_validate(run.result)
            finding = by_id.get(run.finding_id)
            if (
                not finding
                or result.facts.cve_id != finding.cve_id
                or result.facts.verdict != finding.verdict
            ):
                raise AppError(
                    "REPORT_EXPLANATION_MISMATCH", "저장 설명과 분석 결과가 일치하지 않습니다.", 409
                )
            comparisons = {
                "installed_version": finding.installed_version,
                "binary_version": finding.binary_version,
                "fixed_version": finding.fixed_version,
                "package_name": finding.package_name,
                "source_package": finding.source_package,
                "os_release": inventory.os.version_id,
                "version_comparison": finding.version_comparison,
                "origin_status": finding.origin_status,
                "kev_status": finding.kev_status,
                "is_synthetic": analysis.is_synthetic,
            }
            if any(getattr(result.facts, k) != v for k, v in comparisons.items()):
                raise AppError(
                    "REPORT_EXPLANATION_MISMATCH", "설명의 기준값이 분석과 일치하지 않습니다.", 409
                )
            evidence_ids = {c.id for c in result.citations}
            if any(
                not set(s.evidence_ids) <= evidence_ids
                for s in [result.meaning, *result.next_steps]
            ):
                raise AppError(
                    "REPORT_EXPLANATION_MISMATCH", "설명에 필요한 인용이 누락되었습니다.", 409
                )
            if any(c.document_id and str(c.document_id) not in doc_ids for c in result.citations):
                raise AppError(
                    "REPORT_EXPLANATION_MISMATCH", "설명의 출처가 분석 범위를 벗어납니다.", 409
                )
            explanations.append(
                ReportExplanation(
                    id=run.id,
                    finding_id=run.finding_id,
                    model=run.model,
                    reported_model=run.reported_model,
                    prompt_version=run.prompt_version,
                    context_sha256=run.context_sha256,
                    completed_at=aware(run.completed_at),
                    result=result,
                )
            )
        explanations.sort(key=lambda e: (e.result.facts.cve_id, str(e.finding_id)))
    verdicts = Counter(str(f.verdict) for f in findings if f.verdict)
    processing = Counter(str(f.processing_status) for f in findings)
    comparisons = Counter(f.version_comparison for f in findings)
    summary = ReportSummary(
        package_count=len(inventory.packages),
        finding_count=len(findings),
        cve_count=len({f.cve_id for f in findings if f.cve_id}),
        kev_listed_cve_count=len(
            {f.cve_id for f in findings if f.cve_id and f.kev_status == "LISTED"}
        ),
        verdict_counts={k: verdicts[k] for k in VERDICT_LABELS},
        processing_counts={k: processing[k] for k in PROCESSING_LABELS},
        comparison_counts={k: comparisons[k] for k in COMPARISON_LABELS},
    )
    warnings = [
        *analysis.warnings,
        "버전 비교와 영향 판정은 별도 항목입니다. "
        "최종 판단에는 적용 조건과 추가 확인 사유가 반영됩니다.",
        "수정 기준 충족은 해당 CVE의 패키지 기준입니다. "
        "실행 중인 서비스나 자산 전체의 안전을 보장하지 않습니다.",
        "KEV 미등재·미수집은 악용이 없다는 뜻이 아닙니다. CVSS 미제공은 점수 0과 다릅니다.",
        "자동 패치나 설정 변경은 수행하지 않았습니다. "
        "공식 공지와 실제 설치 출처·조건을 확인하세요.",
    ]
    if analysis.is_synthetic:
        warnings.insert(0, "가상 입력 보고서입니다. 실제 서버의 보안 상태가 아닙니다.")
    if include_ai:
        warnings.append(
            f"자료 고정 시점의 결과별 최신 AI Summary {len(explanations)}건을 포함했습니다. "
            "나머지 결과에는 생성 완료된 요약이 없습니다."
        )
        if explanations:
            warnings.append(
                "AI Summary의 검증 범위는 인용·기준값입니다. "
                "생성 문장의 사실성은 별도 검토 대상입니다."
            )
    else:
        warnings.append("AI Summary 미포함. 보고서 생성 시 추가 요약은 생성하지 않습니다.")
    return ReportContent(
        report_id=report_id,
        template_version=TEMPLATE_VERSION,
        frozen_at=frozen_at,
        analysis_id=analysis.id,
        inventory_id=analysis.inventory_id,
        asset_id=analysis.asset_id,
        asset_name=analysis.asset_name,
        expected_release=analysis.expected_release,
        os=inventory.os,
        collected_at=inventory.collected_at,
        ingested_at=inventory.ingested_at,
        analysis_created_at=aware(analysis.created_at),
        analysis_completed_at=aware(analysis.completed_at),
        ruleset_version=analysis.ruleset_version,
        feed_snapshot_id=analysis.feed_snapshot_id,
        is_synthetic=analysis.is_synthetic,
        collection_status=inventory.collection_status,
        package_list_complete=inventory.coverage.package_list_complete,
        include_ai_explanations=include_ai,
        summary=summary,
        warnings=list(dict.fromkeys(warnings)),
        packages=[ReportPackage.model_validate(p.model_dump()) for p in inventory.packages],
        findings=findings,
        sources=[SnapshotResponse.model_validate(s) for s in sources],
        documents=[DocumentInfo.model_validate(d) for d in documents],
        explanations=explanations,
        verification=verification,
    )
