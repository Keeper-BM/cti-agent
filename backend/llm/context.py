"""Select only one finding and that analysis's frozen source records."""

import hashlib
import json
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import defer

from backend.assessment.contracts import AssessmentFinding
from backend.core.errors import AppError
from backend.llm.contracts import Citation, ExplanationContext, Facts
from backend.models.tables import AnalysisRun, FindingRecord, SourceDocument, SourceRecord
from backend.sources.contracts import SecurityRecord
from backend.sources.http import safe_reference


def context_digest(context: ExplanationContext) -> str:
    encoded = json.dumps(context.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prepare_context(db, finding_record: FindingRecord) -> ExplanationContext:
    finding = AssessmentFinding.model_validate(finding_record.payload)
    analysis = db.get(AnalysisRun, finding_record.analysis_id)
    if not analysis or not analysis.completed_at or not finding.cve_id or not finding.verdict:
        raise AppError("EXPLANATION_NOT_ELIGIBLE", "완료된 CVE 분석 결과를 선택하세요.", 409)
    rows = db.execute(
        select(SourceRecord, SourceDocument)
        .join(SourceDocument, SourceDocument.id == SourceRecord.document_id)
        .options(defer(SourceDocument.raw_text))
        .where(
            SourceRecord.snapshot_id.in_(analysis.source_snapshot_ids),
            SourceRecord.cve_id == finding.cve_id,
        )
    ).all()
    # Do not apply another package's Ubuntu record to this finding.
    rows = [
        row
        for row in rows
        if row[0].source_id != "ubuntu"
        or (row[0].package_name == finding.source_package and row[0].release == analysis.os_release)
    ]
    order = {"ubuntu": 0, "nvd": 1, "apache": 2, "oracle": 3, "kev": 4}
    rows.sort(key=lambda row: (order[row[0].source_id], row[0].id))
    if not rows or not finding.evidence_refs:
        raise AppError("EXPLANATION_NO_EVIDENCE", "설명에 사용할 공식 근거가 없습니다.", 409)
    facts = Facts(
        cve_id=finding.cve_id,
        package_name=finding.package_name or "미확인",
        source_package=finding.source_package,
        os_release=analysis.os_release,
        installed_version=finding.installed_version,
        binary_version=finding.binary_version,
        fixed_version=finding.fixed_version,
        verdict=str(finding.verdict),
        version_comparison=finding.version_comparison,
        origin_status=str(finding.origin_status) if finding.origin_status else None,
        kev_status=finding.kev_status,
        is_synthetic=analysis.is_synthetic,
    )
    evaluated_at = finding.evaluated_at
    reasons = list(finding.reasons)
    limitations = list(finding.limitations)
    if finding.origin_status in {"UNKNOWN", "USER_DECLARED", "UNSUPPORTED"}:
        limitations.append("설치 출처가 검증되지 않았습니다. JSON의 출처 선언은 검증이 아닙니다.")
    if finding.origin_status == "OFFICIAL_MATCH":
        limitations.append(
            "공식 파일 일치를 확인했습니다. "
            "기록된 관측 조건 외의 실행 상태·서버 전체는 미검증입니다."
        )
    if finding.kev_status != "LISTED":
        limitations.append("KEV 미등재·미수집은 악용이 없다는 뜻이 아닙니다.")
    citations = [
        Citation(
            id="A1",
            source_id="assessment",
            title="저장된 패키지 분석 결과",
            document_id=None,
            record_id=None,
            snapshot_id=None,
            captured_at=evaluated_at,
            sha256=None,
            url=None,
            excerpt=json.dumps(facts.model_dump(), ensure_ascii=False)
            + "\n"
            + "\n".join(reasons + limitations),
        )
    ]
    notes = []
    # At most one representative per source, then deterministic extra records, up to eight.
    chosen, remaining, seen = [], [], set()
    for row in rows:
        if row[0].source_id in seen:
            remaining.append(row)
        else:
            chosen.append(row)
            seen.add(row[0].source_id)
    chosen = (chosen + remaining)[:8]
    if len(chosen) < len(rows):
        notes.append(f"관련 공식 기록 {len(rows)}개 중 대표 기록 {len(chosen)}개를 사용했습니다.")
    for index, (record, document) in enumerate(chosen, 1):
        data = SecurityRecord.model_validate(record.payload)
        excerpt = json.dumps(
            {
                "description": data.description,
                "package": data.package_name,
                "release": data.release,
                "status": data.status,
                "ubuntu_fixed_version": data.fixed_version,
                "upstream_fixed_version": data.upstream_fixed_version,
                "attributes": data.attributes,
            },
            ensure_ascii=False,
        )
        truncated = len(excerpt) > 5000
        if truncated:
            notes.append(f"E{index} 근거는 길이 제한으로 일부만 전달했습니다.")
        url = next((u for u in data.references if safe_reference(u)), None)
        citations.append(
            Citation(
                id=f"E{index}",
                source_id=record.source_id,
                title=f"{data.cve_id} · {record.source_id}",
                document_id=document.id,
                record_id=record.id,
                snapshot_id=record.snapshot_id,
                captured_at=document.captured_at.replace(tzinfo=UTC)
                if document.captured_at.tzinfo is None
                else document.captured_at,
                sha256=document.sha256,
                url=url or safe_reference(document.url),
                excerpt=excerpt[:5000],
                truncated=truncated,
            )
        )
    context = ExplanationContext(
        facts=facts,
        reasons=reasons,
        limitations=limitations,
        citations=citations,
        selection_notes=notes,
    )
    if len(context.model_dump_json().encode("utf-8")) > 90000:
        raise AppError("EXPLANATION_CONTEXT_LIMIT", "설명에 사용할 근거가 너무 큽니다.", 422)
    return context
