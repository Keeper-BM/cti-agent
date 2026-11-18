"""Asset-bound analysis, with persistent progress independent of browser navigation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header
from sqlalchemy import and_, case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from backend.api.dependencies import Database
from backend.api.routes.assets import find_asset
from backend.api.schemas.workflows import WorkflowRequest, WorkflowResponse, WorkspaceResponse
from backend.core.audit import audit
from backend.core.errors import AppError
from backend.models.tables import (
    AnalysisRun,
    AssetWorkflow,
    AuditEvent,
    CollectionRun,
    InventoryRecord,
    Job,
    ReportRun,
    SSHProfile,
    new_id,
    utcnow,
)
from backend.workflows.queue import queue_collection
from backend.workflows.service import iso

router = APIRouter(prefix="/assets/{asset_id}", tags=["workflows"])


def latest_profile(db, asset_id):
    return db.scalar(
        select(SSHProfile)
        .where(SSHProfile.asset_id == asset_id)
        .order_by(SSHProfile.created_at.desc(), SSHProfile.id.desc())
        .limit(1)
    )


def response(db, run):
    row = (
        db.get(
            InventoryRecord,
            run.inventory_id,
            options=[
                load_only(
                    InventoryRecord.package_count,
                    InventoryRecord.collected_at,
                    InventoryRecord.is_synthetic,
                )
            ],
        )
        if run.inventory_id
        else None
    )
    sources = run.sources
    proof_result = None
    if "verification" in run.timeline:
        proof_result = db.scalar(
            select(Job.result).where(
                Job.idempotency_key == f"wf-{run.id}-verify",
                Job.asset_id == run.asset_id,
                Job.status.in_(["SUCCEEDED", "PARTIAL", "FAILED"]),
            )
        )
    if run.status == "RUNNING" and run.stage == "sources":
        live = dict(
            db.execute(
                select(Job.id, Job.status).where(
                    Job.id.in_(
                        [s["job_id"] for s in sources if s["status"] in {"RUNNING", "QUEUED"}]
                    )
                )
            ).all()
        )
        sources = [
            {**s, "status": "RUNNING"} if live.get(s["job_id"]) == "RUNNING" else s for s in sources
        ]
    return {
        **{
            k: getattr(run, k)
            for k in WorkflowResponse.model_fields
            if k
            not in {"sources", "package_count", "collected_at", "is_synthetic", "verification_note"}
        },
        "sources": sources,
        "verification_note": (proof_result or {}).get("message"),
        "package_count": row.package_count if row else None,
        "collected_at": row.collected_at if row else None,
        "is_synthetic": row.is_synthetic if row else None,
    }


@router.post("/workflows", response_model=WorkflowResponse, status_code=202)
def start_workflow(
    asset_id: UUID,
    payload: WorkflowRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    asset = find_asset(asset_id, db)
    mode = "saved" if payload.inventory_id else "ssh"
    existing = db.scalar(
        select(AssetWorkflow).where(
            AssetWorkflow.asset_id == asset.id, AssetWorkflow.request_key == idempotency_key
        )
    )
    if existing:
        if existing.mode != mode or (
            mode == "saved" and existing.inventory_id != str(payload.inventory_id)
        ):
            raise AppError("IDEMPOTENCY_CONFLICT", "이 요청 키는 다른 입력에 사용되었습니다.", 409)
        return response(db, existing)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산입니다.", 409)
    if db.scalar(select(AssetWorkflow.id).where(AssetWorkflow.active_slot == asset.id)):
        raise AppError("WORKFLOW_BUSY", "이 자산의 자동 분석이 진행 중입니다.", 409)
    principal = db.info["principal"]
    run = AssetWorkflow(
        id=new_id(),
        asset_id=asset.id,
        requested_by=principal.user_id,
        active_slot=asset.id,
        request_key=idempotency_key,
        mode=mode,
        timeline={"inventory": iso(utcnow())},
    )
    try:
        if mode == "ssh":
            profile = latest_profile(db, asset.id)
            if not profile:
                raise AppError("SSH_PROFILE_REQUIRED", "먼저 자산의 SSH 연결을 설정하세요.", 409)
            run.collection_id = queue_collection(db, asset, profile, f"wf-{run.id}-inventory").id
        else:
            inventory = db.get(InventoryRecord, str(payload.inventory_id))
            if not inventory or inventory.asset_id != asset.id:
                raise AppError(
                    "INVENTORY_NOT_FOUND", "이 자산의 패키지 기록을 찾을 수 없습니다.", 404
                )
            run.inventory_id = inventory.inventory_id
        db.add(run)
        audit(db, "workflow.started", asset_id=asset.id, target_id=run.id, details={"mode": mode})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "WORKFLOW_BUSY", "중복 실행 요청입니다. 현재 진행 상태를 확인하세요.", 409
        ) from None
    return response(db, run)


@router.get("/workflows/{run_id}", response_model=WorkflowResponse)
def get_workflow(asset_id: UUID, run_id: UUID, db: Database):
    find_asset(asset_id, db)
    run = db.get(AssetWorkflow, str(run_id))
    if not run or run.asset_id != str(asset_id):
        raise AppError("WORKFLOW_NOT_FOUND", "실행 기록을 찾을 수 없습니다.", 404)
    return response(db, run)


@router.get("/workspace", response_model=WorkspaceResponse)
def workspace(asset_id: UUID, db: Database, analysis_id: UUID | None = None):
    asset = find_asset(asset_id, db)
    profile = latest_profile(db, asset.id)
    state, checked = ("configured" if profile else "unconfigured"), None
    if profile:
        event = db.execute(
            select(AuditEvent.created_at, AuditEvent.outcome)
            .where(AuditEvent.target_id == profile.id, AuditEvent.action == "ssh_profile.checked")
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        ).first()
        collected = db.execute(
            select(Job.finished_at, Job.status)
            .join(CollectionRun, Job.id == CollectionRun.job_id)
            .where(CollectionRun.profile_id == profile.id, Job.finished_at.is_not(None))
            .order_by(Job.finished_at.desc())
            .limit(1)
        ).first()
        checks = [
            (e[0], e[1] in {"SUCCESS", "SUCCEEDED", "PARTIAL"}) for e in (event, collected) if e
        ]
        if checks:
            checked, ok = max(checks, key=lambda e: e[0])
            state = "verified" if ok else "failed"
    inventory = db.scalar(
        select(InventoryRecord)
        .options(
            load_only(
                InventoryRecord.inventory_id,
                InventoryRecord.collected_at,
                InventoryRecord.package_count,
                InventoryRecord.os_release,
                InventoryRecord.is_synthetic,
            )
        )
        .where(InventoryRecord.asset_id == asset.id)
        .order_by(InventoryRecord.ingested_at.desc(), InventoryRecord.inventory_id.desc())
        .limit(1)
    )
    run = db.scalar(
        select(AssetWorkflow)
        .where(AssetWorkflow.asset_id == asset.id)
        .order_by(AssetWorkflow.created_at.desc(), AssetWorkflow.id.desc())
        .limit(1)
    )
    manual_report = (
        select(ReportRun.id)
        .where(ReportRun.analysis_id == AnalysisRun.id, ReportRun.completed_at.is_not(None))
        .order_by(ReportRun.completed_at.desc(), ReportRun.id.desc())
        .limit(1)
        .correlate(AnalysisRun)
        .scalar_subquery()
    )
    # An automated run owns its report even if another report is generated later.
    report_id = case(
        (AssetWorkflow.id.is_(None), manual_report),
        (AssetWorkflow.status == "COMPLETED", AssetWorkflow.report_id),
        else_=None,
    )
    briefs = (
        select(
            AnalysisRun.id,
            AnalysisRun.inventory_id,
            AnalysisRun.os_release,
            AnalysisRun.completed_at,
            AnalysisRun.is_synthetic,
            AnalysisRun.summary,
            report_id.label("report_id"),
            AssetWorkflow.id.label("workflow_id"),
        )
        .outerjoin(
            AssetWorkflow,
            and_(
                AssetWorkflow.analysis_id == AnalysisRun.id,
                AssetWorkflow.asset_id == AnalysisRun.asset_id,
            ),
        )
        .where(AnalysisRun.asset_id == asset.id, AnalysisRun.completed_at.is_not(None))
        .order_by(AnalysisRun.completed_at.desc(), AnalysisRun.id.desc())
    )
    history = db.execute(briefs.limit(8)).mappings().all()
    chosen = history[0] if history else None
    viewed = None
    if analysis_id:
        chosen = (
            db.execute(briefs.where(AnalysisRun.id == str(analysis_id))).mappings().one_or_none()
        )
        if chosen is None:
            raise AppError(
                "ANALYSIS_NOT_FOUND", "이 자산의 완료된 분석 기록을 찾을 수 없습니다.", 404
            )
    elif run and (
        run.status == "RUNNING"
        or not chosen
        or (run.finished_at or run.created_at) >= chosen["completed_at"]
    ):
        viewed = run
        chosen = next((row for row in history if row["id"] == run.analysis_id), None)
        if chosen is None and run.analysis_id:
            chosen = (
                db.execute(briefs.where(AnalysisRun.id == run.analysis_id)).mappings().one_or_none()
            )
    if viewed is None and chosen and chosen["workflow_id"]:
        viewed = db.get(AssetWorkflow, chosen["workflow_id"])
    latest = response(db, run) if run else None
    selected_run = latest if viewed is run else (response(db, viewed) if viewed else None)
    return {
        "asset": asset,
        "profile_id": profile.id if profile else None,
        "connection_status": state,
        "connection_checked_at": iso(checked) if checked else None,
        "inventory": inventory,
        "latest": latest,
        "history": history,
        "selection": {"workflow": selected_run, "analysis": chosen},
    }
