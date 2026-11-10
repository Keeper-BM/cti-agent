"""Pin inputs at request time and publish findings atomically with job completion."""

from collections import Counter, defaultdict
from datetime import UTC
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, defer

from backend.assessment.contracts import PACKAGES, RULESET_VERSION
from backend.assessment.engine import UbuntuAssessmentEngine
from backend.assessment.remediation import guidance
from backend.assessment.runtime import reviewed_http2_record
from backend.core.errors import AppError
from backend.models.contracts import (
    AdvisoryPackageRule,
    Evidence,
    FeedSnapshot,
    InventorySnapshot,
    NormalizedAdvisory,
)
from backend.models.runtime import HTTP2_CONDITION
from backend.models.tables import (
    AnalysisRun,
    Asset,
    FindingRecord,
    InventoryRecord,
    Job,
    SecuritySnapshot,
    SourceDocument,
    SourceRecord,
    SourceRun,
    utcnow,
)
from backend.sources.contracts import SecurityRecord
from backend.sources.service import current_snapshot_ids


def pin_inputs(db: Session, record: InventoryRecord, job: Job) -> AnalysisRun:
    inventory = InventorySnapshot.model_validate(record.payload)
    asset = db.get(Asset, record.asset_id)
    current = list(
        db.scalars(
            select(SecuritySnapshot)
            .where(SecuritySnapshot.id.in_(current_snapshot_ids()))
            .order_by(SecuritySnapshot.source_id, SecuritySnapshot.scope_key)
        )
    )
    ubuntu = [
        s
        for s in current
        if s.source_id == "ubuntu"
        and s.scope_key in {f"{inventory.os.version_id}:{p}" for p in PACKAGES}
    ]
    cves = set(
        db.scalars(
            select(SourceRecord.cve_id).where(SourceRecord.snapshot_id.in_([s.id for s in ubuntu]))
        )
    )
    oracle_ids = set(
        db.scalars(
            select(SourceRecord.snapshot_id)
            .where(SourceRecord.source_id == "oracle", SourceRecord.cve_id.in_(cves))
            .distinct()
        )
    )
    selected = [
        s
        for s in current
        if s in ubuntu
        or s.source_id in {"kev", "apache"}
        or (s.source_id == "nvd" and s.scope_key in cves)
        or (s.source_id == "oracle" and s.id in oracle_ids)
    ]
    if len(selected) > 2000:
        raise AppError("ANALYSIS_SOURCE_LIMIT", "분석에 사용할 자료 기준본이 너무 많습니다.", 422)
    warnings = [
        "분석은 요청 시점에 저장된 자료를 사용합니다. 실시간 조회나 악용 가능성 검증은 아닙니다."
    ]
    if inventory.is_synthetic:
        warnings.append("가상 패키지 입력을 분석한 시험 결과입니다. 실제 서버 상태가 아닙니다.")
    if inventory.collection_method in {"JSON", "CSV"}:
        warnings.append(
            "파일로 입력한 설치 출처는 미검증 상태입니다. 버전 비교와 최종 판단을 구분합니다."
        )
    if not inventory.coverage.package_list_complete:
        warnings.append(
            "패키지 목록이 부분 입력 상태입니다. 누락된 대상은 미설치로 판단하지 않습니다."
        )
    if asset.expected_release and asset.expected_release != inventory.os.version_id:
        warnings.append("자산의 예상 OS와 입력 OS가 다릅니다. 확정 판정을 제한합니다.")
    for package in sorted(PACKAGES):
        if not any(s.scope_key == f"{inventory.os.version_id}:{package}" for s in ubuntu):
            warnings.append(
                f"Ubuntu {inventory.os.version_id} / {package} 자료가 저장되어 있지 않습니다."
            )
    selected_sources = {s.source_id for s in selected}
    if "nvd" not in selected_sources:
        warnings.append("관련 NVD 자료가 없어 CVSS 보충 정보가 없습니다.")
    if "kev" not in selected_sources:
        warnings.append("CISA KEV 자료를 가져오지 않아 악용 목록 등재 여부를 확인하지 못했습니다.")
    latest_jobs = {}
    for run, source_job in db.execute(
        select(SourceRun, Job)
        .join(Job, Job.id == SourceRun.job_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    ):
        latest_jobs.setdefault((run.source_id, run.scope_key), source_job.status)
    for snapshot in selected:
        status = latest_jobs.get((snapshot.source_id, snapshot.scope_key))
        if status in {"FAILED", "QUEUED", "RUNNING"}:
            warnings.append(
                f"{snapshot.source_id} / {snapshot.scope_key}: 최근 갱신 상태 {status}. "
                "마지막 성공 저장본을 사용합니다."
            )
    return AnalysisRun(
        id=str(uuid4()),
        job_id=job.id,
        asset_id=record.asset_id,
        inventory_id=record.inventory_id,
        asset_name=asset.asset_name,
        expected_release=asset.expected_release,
        os_release=inventory.os.version_id,
        is_synthetic=inventory.is_synthetic,
        ruleset_version=RULESET_VERSION,
        feed_snapshot_id=str(uuid4()),
        source_snapshot_ids=[s.id for s in selected],
        warnings=warnings,
    )


def frozen_records(db, analysis):
    return list(
        db.execute(
            select(SourceRecord, SourceDocument, SecuritySnapshot)
            .join(SourceDocument, SourceDocument.id == SourceRecord.document_id)
            .join(SecuritySnapshot, SecuritySnapshot.id == SourceRecord.snapshot_id)
            .options(defer(SourceDocument.raw_text))
            .where(SourceRecord.snapshot_id.in_(analysis.source_snapshot_ids))
            .order_by(SourceRecord.source_id, SourceRecord.cve_id, SourceRecord.id)
        )
    )


def build_feed(analysis, rows) -> FeedSnapshot:
    advisories = []
    for record, document, _snapshot in rows:
        if record.source_id != "ubuntu":
            continue
        data = SecurityRecord.model_validate(record.payload)
        # Only the adapter's exact introduced:0 -> fixed rule is supported in v1.
        conventional = data.ranges == [
            {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": data.fixed_version}]}
        ]
        supported = data.status == "FIX_AVAILABLE" and conventional and data.fixed_version
        http2_reviewed = reviewed_http2_record(data, supported)
        advisories.append(
            NormalizedAdvisory(
                advisory_id=f"UBUNTU-{data.cve_id}:{record.id}",
                cve_id=data.cve_id,
                rules=[
                    AdvisoryPackageRule(
                        rule_id=UUID(record.id),
                        package_name=data.package_name,
                        package_kind="SOURCE",
                        os_id="ubuntu",
                        release=data.release,
                        status="FIX_RELEASED" if supported else "UNKNOWN",
                        fixed_version=data.fixed_version if supported else None,
                        runtime_condition=HTTP2_CONDITION if http2_reviewed else None,
                        limitations=[]
                        if http2_reviewed
                        else [
                            "수정 기준 이전 버전의 설정·컴포넌트 조건은 자동 검증하지 않았습니다."
                        ],
                    )
                ],
                evidence_refs=[
                    Evidence(
                        document_version_id=UUID(document.id),
                        source="Ubuntu CVE / OSV",
                        title=data.cve_id,
                        url=f"https://ubuntu.com/security/{data.cve_id}",
                        excerpt=(
                            f"Ubuntu {data.release}, source {data.package_name}; "
                            f"status={data.status}; fixed={data.fixed_version or '미제공'}. "
                            + data.description[:2500]
                        ),
                    )
                ],
            )
        )
    return FeedSnapshot(
        feed_snapshot_id=analysis.feed_snapshot_id,
        captured_at=analysis.created_at.replace(tzinfo=UTC)
        if analysis.created_at.tzinfo is None
        else analysis.created_at,
        normalizer_version=RULESET_VERSION,
        advisories=advisories,
    )


def assess_job(engine: Engine, job_id: str) -> dict:
    with Session(engine) as db, db.begin():
        analysis = db.scalar(select(AnalysisRun).where(AnalysisRun.job_id == job_id))
        if analysis is None:
            raise AppError("ANALYSIS_NOT_FOUND", "분석 입력을 찾을 수 없습니다.", 500)
        job = db.get(Job, job_id)
        if analysis.completed_at:
            return job.result
        if analysis.ruleset_version != RULESET_VERSION:
            raise AppError(
                "RULESET_CHANGED", "규칙 버전이 변경되었습니다. 새 분석을 요청하세요.", 409
            )
        inventory = InventorySnapshot.model_validate(
            db.get(InventoryRecord, analysis.inventory_id).payload
        )
        rows = frozen_records(db, analysis)
        feed = build_feed(analysis, rows)
        rejected = {
            r.cve_id
            for r, _, _ in rows
            if r.source_id == "nvd" and r.payload["status"] == "REJECTED"
        }
        finished = utcnow()
        findings = UbuntuAssessmentEngine().assess(
            inventory,
            feed,
            analysis_id=UUID(analysis.id),
            evaluated_at=finished,
            expected_release=analysis.expected_release,
            rejected_cves=rejected,
        )
        kev = db.scalar(
            select(SecuritySnapshot).where(
                SecuritySnapshot.id.in_(analysis.source_snapshot_ids),
                SecuritySnapshot.source_id == "kev",
            )
        )
        listed = {r.cve_id for r, _, _ in rows if r.source_id == "kev"}
        metrics = defaultdict(list)
        for record, _, _ in rows:
            if record.source_id == "nvd":
                metrics[record.cve_id].extend(SecurityRecord.model_validate(record.payload).metrics)
        summary = Counter()
        for finding in findings:
            finding.nvd_metrics = metrics[finding.cve_id]
            if finding.cve_id:
                finding.kev_status = (
                    "LISTED" if finding.cve_id in listed else "NOT_LISTED" if kev else "NOT_FETCHED"
                )
            finding.remediation = guidance(finding)
            summary[str(finding.verdict or finding.processing_status)] += 1
            if finding.version_comparison != "UNAVAILABLE":
                summary[finding.version_comparison] += 1
            db.add(
                FindingRecord(
                    id=str(finding.finding_id),
                    analysis_id=analysis.id,
                    asset_id=analysis.asset_id,
                    package_name=finding.package_name,
                    cve_id=finding.cve_id,
                    processing_status=finding.processing_status,
                    verdict=finding.verdict,
                    payload=finding.model_dump(mode="json"),
                )
            )
        summary["TOTAL"] = len(findings)
        analysis.summary = dict(summary)
        analysis.feed_payload = feed.model_dump(mode="json")
        analysis.completed_at = finished
        result = {
            "message": f"패키지 분석 {len(findings)}건을 저장했습니다.",
            "analysis_id": analysis.id,
        }
        job.status, job.result, job.finished_at = "SUCCEEDED", result, finished
    return result
