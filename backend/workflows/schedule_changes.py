"""Compare settled scheduled analyses without treating missing findings as fixed."""

from collections import defaultdict

from sqlalchemy import select

from backend.models.tables import (
    AnalysisRun,
    AssetWorkflow,
    FindingRecord,
    InventoryRecord,
    WorkflowBatchAsset,
    WorkflowScheduleRun,
)
from backend.workflows.batch import asset_error, batch_assets
from backend.workflows.evidence import evaluated_pairs

CHANGE_ORDER = ("NEW_AFFECTED", "FIXED", "RECHECK")
VERDICT_PRIORITY = {"AFFECTED": 0, "NEEDS_REVIEW": 1, "NOT_AFFECTED": 2, "FIXED": 3}


def comparison_blocker(collection_status, sources, summary):
    if collection_status != "COMPLETE":
        return "패키지 전체를 수집한 결과가 필요합니다."
    if not evaluated_pairs(summary or {}):
        return "공식 자료와 대조한 평가 결과가 없습니다."
    ubuntu = [source for source in sources if source["source"] == "ubuntu"]
    if not ubuntu or any(source["status"] != "UPDATED" for source in ubuntu):
        return "이번 회차의 Ubuntu 공식 자료 갱신을 완료하지 못했습니다."
    return None


def previous_results(db, scheduled_run, asset_ids):
    previous = {}
    if not asset_ids:
        return previous
    result = db.execute(
        select(
            WorkflowBatchAsset.asset_id,
            AnalysisRun.id,
            AnalysisRun.completed_at,
            AnalysisRun.summary,
            AssetWorkflow.sources,
        )
        .select_from(WorkflowScheduleRun)
        .join(WorkflowBatchAsset, WorkflowBatchAsset.batch_id == WorkflowScheduleRun.batch_id)
        .join(AssetWorkflow, AssetWorkflow.id == WorkflowBatchAsset.workflow_id)
        .join(AnalysisRun, AnalysisRun.id == AssetWorkflow.analysis_id)
        .join(InventoryRecord, InventoryRecord.inventory_id == AnalysisRun.inventory_id)
        .where(
            WorkflowScheduleRun.schedule_id == scheduled_run.schedule_id,
            WorkflowScheduleRun.scheduled_for < scheduled_run.scheduled_for,
            WorkflowBatchAsset.asset_id.in_(asset_ids),
            AnalysisRun.completed_at.is_not(None),
            AnalysisRun.is_synthetic.is_(False),
            InventoryRecord.collection_status == "COMPLETE",
        )
        .order_by(WorkflowScheduleRun.scheduled_for.desc())
        .execution_options(yield_per=50)
    )
    try:
        for row in result:
            if row.asset_id not in previous and not comparison_blocker(
                "COMPLETE", row.sources, row.summary
            ):
                previous[row.asset_id] = row
                if len(previous) == len(asset_ids):
                    break
    finally:
        result.close()
    return previous


def findings_by_analysis(db, analysis_ids):
    by_analysis = defaultdict(dict)
    if not analysis_ids:
        return by_analysis
    rows = db.execute(
        select(
            FindingRecord.id,
            FindingRecord.analysis_id,
            FindingRecord.cve_id,
            FindingRecord.package_name,
            FindingRecord.payload["architecture"].as_string().label("architecture"),
            FindingRecord.verdict,
        )
        .where(
            FindingRecord.analysis_id.in_(analysis_ids),
            FindingRecord.cve_id.is_not(None),
            FindingRecord.package_name.is_not(None),
            FindingRecord.verdict.is_not(None),
        )
        .order_by(FindingRecord.id)
    )
    for row in rows:
        key = (row.cve_id, row.package_name, row.architecture)
        findings = by_analysis[row.analysis_id]
        existing = findings.get(key)
        if existing is None or VERDICT_PRIORITY[row.verdict] < VERDICT_PRIORITY[existing.verdict]:
            findings[key] = row
    return by_analysis


def asset_changes(asset_id, previous, current):
    for cve_id, package_name, architecture in previous.keys() | current.keys():
        key = (cve_id, package_name, architecture)
        before, after = previous.get(key), current.get(key)
        old_verdict, verdict = before.verdict if before else None, after.verdict if after else None
        if old_verdict != "AFFECTED" and verdict == "AFFECTED":
            kind = "NEW_AFFECTED"
        elif old_verdict == "AFFECTED" and verdict != "AFFECTED":
            kind = "FIXED" if verdict == "FIXED" else "RECHECK"
        else:
            continue
        yield {
            "kind": kind,
            "asset_id": asset_id,
            "cve_id": cve_id,
            "package_name": package_name,
            "architecture": architecture,
            "previous_verdict": old_verdict,
            "verdict": verdict,
            "previous_finding_id": before.id if before else None,
            "finding_id": after.id if after else None,
        }


def compare_schedule_run(db, scheduled_run, kind, limit, offset):
    rows = batch_assets(db, scheduled_run.batch_id)
    collection = dict(
        db.execute(
            select(InventoryRecord.inventory_id, InventoryRecord.collection_status).where(
                InventoryRecord.inventory_id.in_(
                    [analysis.inventory_id for _, _, analysis in rows if analysis]
                )
            )
        ).all()
    )
    assets = []
    for member, run, analysis in rows:
        if not analysis:
            reason = asset_error(member, run) or "완료된 분석 결과가 없습니다."
        elif analysis.is_synthetic:
            reason = "실제 SSH 수집 결과가 필요합니다."
        else:
            reason = comparison_blocker(
                collection.get(analysis.inventory_id), run.sources, analysis.summary
            )
        assets.append(
            {
                "asset_id": member.asset_id,
                "asset_name": member.asset_name,
                "analysis_id": analysis.id if analysis else None,
                "previous_analysis_id": None,
                "previous_completed_at": None,
                "status": "UNAVAILABLE" if reason else "BASELINE",
                "reason": reason,
            }
        )
    eligible = [asset for asset in assets if asset["status"] == "BASELINE"]
    previous = previous_results(db, scheduled_run, [asset["asset_id"] for asset in eligible])
    for asset in eligible:
        if baseline := previous.get(asset["asset_id"]):
            asset.update(
                status="COMPARED",
                previous_analysis_id=baseline.id,
                previous_completed_at=baseline.completed_at,
            )
    compared = [asset for asset in eligible if asset["status"] == "COMPARED"]
    findings = findings_by_analysis(
        db,
        {asset[key] for asset in compared for key in ("analysis_id", "previous_analysis_id")},
    )
    counts = dict.fromkeys(CHANGE_ORDER, 0)
    matches = []
    names = {asset["asset_id"]: asset["asset_name"] for asset in compared}
    for asset in compared:
        for change in asset_changes(
            asset["asset_id"],
            findings[asset["previous_analysis_id"]],
            findings[asset["analysis_id"]],
        ):
            counts[change["kind"]] += 1
            if kind is None or change["kind"] == kind:
                matches.append(change)
    matches.sort(
        key=lambda item: (
            CHANGE_ORDER.index(item["kind"]),
            names[item["asset_id"]],
            item["cve_id"],
            item["package_name"],
            item["architecture"] or "",
            item["asset_id"],
        )
    )
    return {
        "assets": assets,
        "counts": counts,
        "items": matches[offset : offset + limit],
        "total": len(matches),
    }
