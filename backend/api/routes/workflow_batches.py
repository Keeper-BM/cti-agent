"""Request, recover and download analyses for an explicitly selected asset set."""

from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import case, distinct, func, select, update
from sqlalchemy.exc import IntegrityError

from backend.api.dependencies import Database
from backend.api.schemas.workflow_batches import (
    BatchComparison,
    WorkflowBatchList,
    WorkflowBatchRequest,
    WorkflowBatchResponse,
)
from backend.assessment.contracts import AssessmentFinding
from backend.core.audit import audit
from backend.core.errors import AppError
from backend.models.tables import (
    Asset,
    FindingRecord,
    InventoryRecord,
    SecuritySnapshot,
    SourceRecord,
    WorkflowBatch,
)
from backend.sources.contracts import CVE_PATTERN
from backend.workflows.batch import (
    asset_error,
    asset_status,
    batch_assets,
    enqueue_batch,
    report_status,
)
from backend.workflows.evidence import batch_sources, coverage, evaluated_pairs

router = APIRouter(prefix="/workflow-batches", tags=["workflow batches"])
RequestKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{1,100}$")]


def find_batch(db, batch_id):
    batch = db.get(WorkflowBatch, str(batch_id))
    if batch is None:
        raise AppError("BATCH_NOT_FOUND", "일괄 분석 기록을 찾을 수 없습니다.", 404)
    return batch


def selected_assets(db, ids):
    assets = {asset.id: asset for asset in db.scalars(select(Asset).where(Asset.id.in_(ids)))}
    if set(assets) != set(ids):
        raise AppError("ASSET_NOT_FOUND", "선택한 자산을 모두 찾을 수 없습니다.", 404)
    return assets


def cve_counts(db, batch, analysis_ids):
    if batch.status == "RUNNING":
        return None, None
    if batch.report_summary is not None:
        return batch.report_summary["cve_count"], batch.report_summary["affected_cve_count"]
    cve = FindingRecord.cve_id
    return db.execute(
        select(
            func.count(distinct(cve)),
            func.count(distinct(case((FindingRecord.verdict == "AFFECTED", cve)))),
        ).where(FindingRecord.analysis_id.in_(analysis_ids), FindingRecord.verdict.is_not(None))
    ).one()


def output(db, batch):
    rows = batch_assets(db, batch.id)
    inventories = {
        row.inventory_id: row
        for row in db.execute(
            select(
                InventoryRecord.inventory_id,
                InventoryRecord.package_count,
                InventoryRecord.collection_status,
                InventoryRecord.collected_at,
            ).where(
                InventoryRecord.inventory_id.in_(
                    [analysis.inventory_id for _, _, analysis in rows if analysis]
                )
            )
        )
    }
    evaluated, affected = cve_counts(
        db, batch, [analysis.id for _, _, analysis in rows if analysis]
    )
    members = []
    for member, run, analysis in rows:
        status = asset_status(run, analysis)
        summary = (analysis.summary or {}) if analysis else {}
        inventory = inventories.get(analysis.inventory_id) if analysis else None
        members.append(
            {
                "asset_id": member.asset_id,
                "asset_name": member.asset_name,
                "status": status,
                "stage": run.stage if run else "inventory",
                "analysis_id": analysis.id if analysis else None,
                "report_id": run.report_id if run and run.status == "COMPLETED" else None,
                "os_release": analysis.os_release if analysis else None,
                "is_synthetic": bool(analysis and analysis.is_synthetic),
                "carried": member.carried,
                "verdict_counts": summary,
                "coverage": coverage(summary) if analysis else None,
                "evaluated_pairs": evaluated_pairs(summary),
                "package_count": inventory.package_count if inventory else None,
                "collection_status": inventory.collection_status if inventory else None,
                "collected_at": inventory.collected_at if inventory else None,
                "error": asset_error(member, run) if status == "FAILED" else None,
                "report_note": run.error if status == "COMPLETED" else None,
            }
        )
    return {
        "id": batch.id,
        "parent_id": batch.parent_id,
        "retry_id": db.scalar(select(WorkflowBatch.id).where(WorkflowBatch.parent_id == batch.id)),
        "status": batch.status,
        "created_at": batch.created_at,
        "finished_at": batch.finished_at,
        "assets": members,
        "evaluated_cve_count": evaluated,
        "affected_cve_count": affected,
        "sources": batch_sources(rows),
        "report_status": report_status(batch),
        "report_summary": batch.report_summary,
        "report_error": batch.report_error,
    }


def by_request(db, key):
    return db.scalar(
        select(WorkflowBatch).where(
            WorkflowBatch.request_key == key,
            WorkflowBatch.requested_by == db.info["principal"].user_id,
        )
    )


def existing_request(db, key, ids):
    batch = by_request(db, key)
    if batch is None:
        return None
    if batch.parent_id or {member.asset_id for member, _, _ in batch_assets(db, batch.id)} != set(
        ids
    ):
        raise AppError("IDEMPOTENCY_CONFLICT", "이 요청 키는 다른 입력에 사용되었습니다.", 409)
    return batch


@router.post("", response_model=WorkflowBatchResponse, status_code=202)
def start_batch(payload: WorkflowBatchRequest, db: Database, idempotency_key: RequestKey):
    ids = sorted(str(asset_id) for asset_id in payload.asset_ids)
    existing = existing_request(db, idempotency_key, ids)
    if existing:
        return output(db, existing)
    assets = selected_assets(db, ids)
    try:
        batch = enqueue_batch(db, [(assets[asset_id], None) for asset_id in ids], idempotency_key)
        db.commit()
    except IntegrityError:
        db.rollback()
        batch = existing_request(db, idempotency_key, ids)
        if batch is None:
            raise AppError(
                "BATCH_CONFLICT", "중복 실행 요청입니다. 다시 시도하세요.", 409
            ) from None
    return output(db, batch)


@router.get("", response_model=WorkflowBatchList)
def list_batches(db: Database, limit: int = Query(5, ge=1, le=20), offset: int = Query(0, ge=0)):
    batches = list(
        db.scalars(
            select(WorkflowBatch)
            .order_by(WorkflowBatch.created_at.desc(), WorkflowBatch.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "items": [output(db, batch) for batch in batches],
        "total": db.scalar(select(func.count(WorkflowBatch.id))),
    }


@router.get("/{batch_id}", response_model=WorkflowBatchResponse)
def get_batch(batch_id: UUID, db: Database):
    return output(db, find_batch(db, batch_id))


@router.get("/{batch_id}/comparison", response_model=BatchComparison)
def compare_batch(
    batch_id: UUID,
    db: Database,
    cve_id: Annotated[str | None, Query(pattern=CVE_PATTERN, max_length=32)] = None,
):
    batch = find_batch(db, batch_id)
    if batch.status == "RUNNING":
        raise AppError("BATCH_RUNNING", "일괄 분석이 끝나면 CVE를 비교할 수 있습니다.", 409)
    analysis_ids = [analysis.id for _, _, analysis in batch_assets(db, batch.id) if analysis]
    scope = (
        FindingRecord.analysis_id.in_(analysis_ids),
        FindingRecord.verdict.is_not(None),
    )
    if cve_id is None:
        priorities = (batch.report_summary or {}).get("priorities", [])
        cve_id = (
            priorities[0]["cve_id"]
            if priorities
            else db.scalar(select(func.max(FindingRecord.cve_id)).where(*scope))
        )
    if cve_id is None:
        return {"cve_id": None, "items": []}

    findings = [
        AssessmentFinding.model_validate(payload)
        for payload in db.scalars(
            select(FindingRecord.payload)
            .where(*scope, FindingRecord.cve_id == cve_id)
            .order_by(FindingRecord.package_name, FindingRecord.asset_id, FindingRecord.id)
        )
    ]
    sources = {
        row.id: row
        for row in db.execute(
            select(SourceRecord.id, SourceRecord.snapshot_id, SecuritySnapshot.captured_at)
            .join(SecuritySnapshot, SecuritySnapshot.id == SourceRecord.snapshot_id)
            .where(
                SourceRecord.source_id == "ubuntu",
                SourceRecord.id.in_(
                    [str(f.matched_rule_id) for f in findings if f.matched_rule_id]
                ),
            )
        )
    }
    items = []
    for finding in findings:
        source = sources.get(str(finding.matched_rule_id))
        items.append(
            {
                "finding_id": finding.finding_id,
                "asset_id": finding.asset_id,
                "package_name": finding.package_name,
                "architecture": finding.architecture,
                "binary_version": finding.binary_version,
                "installed_version": finding.installed_version,
                "fixed_version": finding.fixed_version,
                "verdict": finding.verdict,
                "ubuntu_snapshot_id": source.snapshot_id if source else None,
                "captured_at": source.captured_at if source else None,
            }
        )
    return {"cve_id": cve_id, "items": items}


@router.post("/{batch_id}/retry", response_model=WorkflowBatchResponse, status_code=202)
def retry_batch(batch_id: UUID, db: Database, idempotency_key: RequestKey):
    batch = find_batch(db, batch_id)
    if batch.status == "RUNNING":
        raise AppError("BATCH_RUNNING", "일괄 분석이 끝난 뒤 다시 시도하세요.", 409)
    previous = db.scalar(select(WorkflowBatch).where(WorkflowBatch.parent_id == batch.id))
    if previous:
        return output(db, previous)
    rows = batch_assets(db, batch.id)
    if all(analysis for _, _, analysis in rows):
        raise AppError("BATCH_NO_FAILED_ASSETS", "재시도할 자산이 없습니다.", 409)
    assets = selected_assets(db, [member.asset_id for member, _, _ in rows])
    try:
        retry = enqueue_batch(
            db,
            [
                (assets[member.asset_id], run if analysis else None)
                for member, run, analysis in rows
            ],
            idempotency_key,
            parent_id=batch.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        retry = db.scalar(select(WorkflowBatch).where(WorkflowBatch.parent_id == str(batch_id)))
        if retry is None:
            raise AppError(
                "BATCH_CONFLICT", "중복 실행 요청입니다. 다시 시도하세요.", 409
            ) from None
    return output(db, retry)


@router.post("/{batch_id}/report/retry", response_model=WorkflowBatchResponse, status_code=202)
def retry_report(batch_id: UUID, db: Database):
    batch = find_batch(db, batch_id)
    state = report_status(batch)
    if state == "WAITING":
        raise AppError("BATCH_RUNNING", "일괄 분석이 끝난 뒤 보고서를 생성하세요.", 409)
    if state == "FAILED":
        result = db.execute(
            update(WorkflowBatch)
            .where(
                WorkflowBatch.id == batch.id,
                WorkflowBatch.markdown.is_(None),
                WorkflowBatch.report_error.is_not(None),
            )
            .values(report_error=None)
        )
        if result.rowcount:
            audit(db, "workflow_batch.report_queued", target_id=batch.id)
        db.commit()
        db.refresh(batch, ["report_error", "report_summary"])
    return output(db, batch)


@router.get(
    "/{batch_id}/markdown",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}},
)
def download_batch(batch_id: UUID, db: Database):
    batch = find_batch(db, batch_id)
    if batch.report_summary is None or batch.markdown is None:
        raise AppError("BATCH_REPORT_NOT_READY", "생성 완료된 통합 보고서를 내려받으세요.", 409)
    body = batch.markdown.encode("utf-8")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cti-batch-report-{batch.id}.md"',
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": sha256(body).hexdigest(),
        },
    )
