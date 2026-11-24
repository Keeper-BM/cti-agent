"""Advance persistent batches after their asset workflows settle."""

import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, load_only

from backend.core.audit import audit
from backend.core.diagnostics import safe_exception_details
from backend.core.errors import AppError
from backend.models.tables import (
    AnalysisRun,
    AssetWorkflow,
    WorkflowBatch,
    WorkflowBatchAsset,
    utcnow,
)
from backend.reports.batch import build_batch_report
from backend.workflows.queue import queue_workflow

logger = logging.getLogger(__name__)


def batch_assets(db, batch_id):
    return db.execute(
        select(WorkflowBatchAsset, AssetWorkflow, AnalysisRun)
        .outerjoin(AssetWorkflow, AssetWorkflow.id == WorkflowBatchAsset.workflow_id)
        .outerjoin(
            AnalysisRun,
            and_(
                AnalysisRun.id == AssetWorkflow.analysis_id, AnalysisRun.completed_at.is_not(None)
            ),
        )
        .where(WorkflowBatchAsset.batch_id == batch_id)
        .options(
            load_only(
                AssetWorkflow.status,
                AssetWorkflow.stage,
                AssetWorkflow.error,
                AssetWorkflow.report_id,
                AssetWorkflow.inventory_id,
                AssetWorkflow.sources,
            ),
            load_only(
                AnalysisRun.inventory_id,
                AnalysisRun.os_release,
                AnalysisRun.is_synthetic,
                AnalysisRun.source_snapshot_ids,
                AnalysisRun.summary,
                AnalysisRun.warnings,
                AnalysisRun.completed_at,
            ),
        )
        .order_by(WorkflowBatchAsset.asset_name, WorkflowBatchAsset.asset_id)
    ).all()


def asset_status(run, analysis):
    if run and run.status == "RUNNING":
        return "RUNNING"
    return "COMPLETED" if analysis else "FAILED"


def asset_error(member, run):
    return member.start_error or (run.error if run else None)


def report_status(batch):
    if batch.status == "RUNNING":
        return "WAITING"
    if batch.report_summary is not None:
        return "READY"
    return "FAILED" if batch.report_error else "QUEUED"


def enqueue_batch(db, assets, key, parent_id=None):
    batch = WorkflowBatch(
        requested_by=db.info["principal"].user_id, request_key=key, parent_id=parent_id
    )
    db.add(batch)
    db.flush()
    for asset, previous in assets:
        member = WorkflowBatchAsset(
            batch_id=batch.id, asset_id=asset.id, asset_name=asset.asset_name
        )
        if previous:
            member.workflow_id, member.carried = previous.id, True
        else:
            try:
                with db.begin_nested():
                    member.workflow_id = queue_workflow(db, asset, f"batch-{batch.id}").id
            except AppError as exc:
                member.start_error = exc.message
            except IntegrityError:
                member.start_error = "진행 중인 분석이 있습니다. 완료 후 다시 시도하세요."
        db.add(member)
    audit(db, "workflow_batch.started", target_id=batch.id, details={"asset_count": len(assets)})
    return batch


def advance_batches(engine):
    with Session(engine) as db:
        ids = list(
            db.scalars(
                select(WorkflowBatch.id).where(
                    or_(
                        WorkflowBatch.status == "RUNNING",
                        and_(
                            WorkflowBatch.markdown.is_(None), WorkflowBatch.report_error.is_(None)
                        ),
                    )
                )
            )
        )
    for batch_id in ids:
        try:
            with Session(engine) as db, db.begin():
                batch = db.get(WorkflowBatch, batch_id)
                assets = batch_assets(db, batch_id)
                states = [asset_status(run, analysis) for _, run, analysis in assets]
                if "RUNNING" in states:
                    continue
                first_report = batch.status == "RUNNING"
                if not first_report and report_status(batch) != "QUEUED":
                    continue
                if first_report:
                    batch.finished_at = utcnow()
                    completed = states.count("COMPLETED")
                    if completed == len(states):
                        batch.status = "COMPLETED"
                    else:
                        batch.status = "PARTIAL" if completed else "FAILED"
                try:
                    batch.report_summary, batch.markdown = build_batch_report(db, batch, assets)
                except OperationalError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Batch report %s failed: %s", batch_id, safe_exception_details(exc)
                    )
                    batch.report_error = (
                        "통합 보고서를 생성하지 못했습니다. "
                        "저장된 판정으로 다시 생성할 수 있습니다."
                    )
                audit(
                    db,
                    "workflow_batch.finished" if first_report else "workflow_batch.report_rebuilt",
                    target_id=batch.id,
                    actor_id=batch.requested_by,
                    outcome=batch.status if first_report else report_status(batch),
                    details={"report_ready": batch.report_summary is not None},
                )
        except OperationalError as exc:
            # A temporary DB write conflict can be retried without repeating a child job.
            logger.warning("Could not settle batch %s: %s", batch_id, safe_exception_details(exc))
