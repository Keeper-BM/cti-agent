import hashlib
import json
from collections import Counter, defaultdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.assessment.contracts import RULESET_VERSION, AssessmentFinding
from backend.assessment.engine import UbuntuAssessmentEngine
from backend.assessment.remediation import guidance
from backend.assessment.service import frozen_records
from backend.comparison.contracts import VERSION, ComparisonInput, ComparisonResult, ComparisonRow
from backend.core.errors import AppError
from backend.models.contracts import FeedSnapshot, InventorySnapshot
from backend.models.tables import ComparisonRun, FindingRecord, InventoryRecord, Job, utcnow
from backend.sources.contracts import Metric


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 32 * 1024 * 1024:
        raise AppError("COMPARISON_LIMIT", "비교 입력 크기가 제한을 초과합니다.", 422)
    return hashlib.sha256(raw).hexdigest()


def pin(db, analysis, target):
    before = InventorySnapshot.model_validate(
        db.get(InventoryRecord, analysis.inventory_id).payload
    )
    after = InventorySnapshot.model_validate(target.payload)
    if before.asset_id != after.asset_id:
        raise AppError("COMPARISON_ASSET_MISMATCH", "같은 자산의 기록만 비교할 수 있습니다.", 422)
    if (
        before.os.id != after.os.id
        or before.os.version_id != after.os.version_id
        or before.os.architecture != after.os.architecture
    ):
        raise AppError(
            "COMPARISON_OS_MISMATCH", "동일한 OS 릴리스·아키텍처의 기록을 선택하세요.", 422
        )
    if before.inventory_id == after.inventory_id:
        raise AppError("COMPARISON_SAME_INPUT", "서로 다른 패키지 기록을 선택하세요.", 422)
    feed = FeedSnapshot.model_validate(analysis.feed_payload)
    risks = {}
    for row in db.scalars(select(FindingRecord).where(FindingRecord.analysis_id == analysis.id)):
        f = AssessmentFinding.model_validate(row.payload)
        if f.cve_id:
            risks[f.cve_id] = {
                "kev_status": f.kev_status,
                "nvd_metrics": [m.model_dump() for m in f.nvd_metrics],
            }
    rejected = [
        record.cve_id
        for record, _, _ in frozen_records(db, analysis)
        if record.source_id == "nvd" and record.payload["status"] == "REJECTED"
    ]
    return ComparisonInput(
        baseline_analysis_id=UUID(analysis.id),
        asset_id=UUID(analysis.asset_id),
        asset_name=analysis.asset_name,
        expected_release=analysis.expected_release,
        before=before,
        after=after,
        feed=feed,
        rejected_cves=rejected,
        risk_facts=risks,
        source_snapshot_ids=analysis.source_snapshot_ids,
    )


def compare(data: ComparisonInput):
    now = utcnow()
    engine = UbuntuAssessmentEngine()
    groups = []
    for inventory in (data.before, data.after):
        results = engine.assess(
            inventory,
            data.feed,
            analysis_id=uuid4(),
            evaluated_at=now,
            expected_release=data.expected_release,
            rejected_cves=set(data.rejected_cves),
        )
        grouped = defaultdict(list)
        for f in results:
            risk = data.risk_facts.get(f.cve_id, {})
            f.kev_status = risk.get("kev_status", "NOT_FETCHED")
            f.nvd_metrics = [Metric.model_validate(m) for m in risk.get("nvd_metrics", [])]
            f.remediation = guidance(f)
            grouped[(f.package_name or "", f.architecture or "", f.cve_id or "")].append(f)
        groups.append(grouped)

    def facts(items):
        return sorted(
            (
                str(f.verdict or ""),
                str(f.processing_status),
                f.installed_version or "",
                f.binary_version or "",
                f.fixed_version or "",
                f.version_comparison,
                str(f.origin_status or ""),
                tuple(sorted(f.reason_codes)),
            )
            for f in items
        )

    left, right = groups
    rows = []
    for name, arch, cve in sorted(set(left) | set(right)):
        key = (name, arch, cve)
        before = left.get(key, [])
        after = right.get(key, [])
        change = (
            "ADDED"
            if not before
            else "REMOVED"
            if not after
            else "UNCHANGED"
            if facts(before) == facts(after)
            else "CHANGED"
        )
        rows.append(
            ComparisonRow(
                package_name=name,
                architecture=arch or None,
                cve_id=cve or None,
                change=change,
                before=before,
                after=after,
            )
        )
    counts = Counter(r.change for r in rows)
    return ComparisonResult(
        baseline_analysis_id=data.baseline_analysis_id,
        asset_id=data.asset_id,
        asset_name=data.asset_name,
        before_inventory_id=data.before.inventory_id,
        after_inventory_id=data.after.inventory_id,
        source_snapshot_ids=data.source_snapshot_ids,
        ruleset_version=RULESET_VERSION,
        before_collected_at=data.before.collected_at,
        after_collected_at=data.after.collected_at,
        completed_at=now,
        summary={k: counts[k] for k in ["ADDED", "REMOVED", "CHANGED", "UNCHANGED"]},
        rows=rows,
        warnings=[
            "두 입력을 선택한 분석의 동일한 보안 자료와 현재 비교 규칙으로 다시 평가했습니다.",
            "추가·제거는 입력 목록의 차이입니다. 해결·안전을 자동으로 의미하지 않습니다.",
            "같은 자료 기준의 설치 상태를 비교합니다. 이전 분석·보고서는 변경하지 않습니다.",
        ]
        + (
            ["가상 입력이 포함된 비교입니다."]
            if data.before.is_synthetic or data.after.is_synthetic
            else []
        )
        + (
            ["부분 수집 입력이 포함되어 누락 패키지를 해결된 것으로 판단할 수 없습니다."]
            if not data.before.coverage.package_list_complete
            or not data.after.coverage.package_list_complete
            else []
        ),
    )


def compare_job(engine, job_id):
    with Session(engine) as db:
        run = db.scalar(select(ComparisonRun).where(ComparisonRun.job_id == job_id))
        if not run:
            raise AppError("COMPARISON_NOT_FOUND", "비교 입력을 찾지 못했습니다.", 500)
        if run.completed_at:
            return db.get(Job, job_id).result
        if run.version != VERSION or digest(run.input_payload) != run.input_sha256:
            raise AppError("COMPARISON_INPUT_CHANGED", "비교 입력 또는 버전이 바뀌었습니다.", 409)
        data = ComparisonInput.model_validate(run.input_payload)
        run_id = run.id
    result = compare(data)
    wire = result.model_dump(mode="json")
    digest(wire)
    with Session(engine) as db, db.begin():
        job = db.get(Job, job_id)
        if job.status != "RUNNING":
            raise AppError("COMPARISON_INTERRUPTED", "비교 작업이 중단됐습니다.", 409)
        run = db.get(ComparisonRun, run_id)
        run.result = wire
        run.completed_at = utcnow()
        job.status = "SUCCEEDED"
        job.finished_at = run.completed_at
        job.result = {
            "message": "같은 자료 기준의 패키지 전후 비교를 저장했습니다.",
            "comparison_id": run_id,
        }
        return job.result
