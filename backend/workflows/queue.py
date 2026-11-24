"""Create child jobs and their inputs in the caller's transaction."""

from uuid import uuid4

from sqlalchemy import select

from backend.collectors.ssh_config import check_target, key_path
from backend.collectors.ssh_protocol import COLLECTOR_VERSION
from backend.core.audit import audit
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import (
    AssetWorkflow,
    CollectionRun,
    InventoryRecord,
    Job,
    ReportRun,
    SSHProfile,
    new_id,
    utcnow,
)
from backend.reports.contracts import TEMPLATE_VERSION
from backend.reports.snapshot import digest, freeze_report
from backend.reports.summary import pin_report_input


def latest_profile(db, asset_id):
    return db.scalar(
        select(SSHProfile)
        .where(SSHProfile.asset_id == asset_id)
        .order_by(SSHProfile.created_at.desc(), SSHProfile.id.desc())
        .limit(1)
    )


def queue_workflow(db, asset, key, inventory_id=None):
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산입니다.", 409)
    if db.scalar(select(AssetWorkflow.id).where(AssetWorkflow.active_slot == asset.id)):
        raise AppError("WORKFLOW_BUSY", "이 자산의 자동 분석이 진행 중입니다.", 409)
    run = AssetWorkflow(
        id=new_id(),
        asset_id=asset.id,
        requested_by=db.info["principal"].user_id,
        active_slot=asset.id,
        request_key=key,
        mode="saved" if inventory_id else "ssh",
        timeline={"inventory": utcnow().isoformat()},
    )
    if inventory_id:
        inventory = db.get(InventoryRecord, str(inventory_id))
        if not inventory or inventory.asset_id != asset.id:
            raise AppError("INVENTORY_NOT_FOUND", "이 자산의 패키지 기록을 찾을 수 없습니다.", 404)
        run.inventory_id = inventory.inventory_id
    else:
        profile = latest_profile(db, asset.id)
        if not profile:
            raise AppError("SSH_PROFILE_REQUIRED", "먼저 자산의 SSH 연결을 설정하세요.", 409)
        run.collection_id = queue_collection(db, asset, profile, f"wf-{run.id}-inventory").id
    db.add(run)
    db.flush()
    audit(db, "workflow.started", asset_id=asset.id, target_id=run.id, details={"mode": run.mode})
    return run


def queue_collection(db, asset, profile, key, actor=None):
    config = get_settings()
    check_target(config, profile.host, profile.port)
    key_path(config, profile.key_alias)
    if db.scalar(select(CollectionRun.id).where(CollectionRun.active_slot == asset.id)):
        raise AppError("COLLECTION_BUSY", "이 자산에서 이미 패키지를 수집하고 있습니다.", 409)
    job = Job(kind="SSH_COLLECTION", asset_id=asset.id, idempotency_key=key, requested_by=actor)
    db.add(job)
    db.flush()
    run = CollectionRun(
        job_id=job.id,
        asset_id=asset.id,
        profile_id=profile.id,
        active_slot=asset.id,
        collector_version=COLLECTOR_VERSION,
    )
    db.add(run)
    db.flush()
    return run


def queue_report(db, analysis, include_ai, key, actor=None, *, generate_ai_summary=False):
    report_id, frozen_at = uuid4(), utcnow()
    content = freeze_report(db, analysis, report_id, frozen_at, include_ai)
    pinned = pin_report_input(db, content, generate_ai_summary).model_dump(mode="json")
    job = Job(kind="REPORT", asset_id=analysis.asset_id, idempotency_key=key, requested_by=actor)
    db.add(job)
    db.flush()
    report = ReportRun(
        id=str(report_id),
        job_id=job.id,
        analysis_id=analysis.id,
        asset_id=analysis.asset_id,
        asset_name=content.asset_name,
        is_synthetic=content.is_synthetic,
        include_ai_explanations=include_ai,
        explanation_count=len(content.explanations),
        finding_count=len(content.findings),
        template_version=TEMPLATE_VERSION,
        input_sha256=digest(pinned),
        input_payload=pinned,
        created_at=frozen_at,
    )
    db.add(report)
    db.flush()
    return report
