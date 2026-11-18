"""Create child jobs and their inputs in the caller's transaction."""

from uuid import uuid4

from sqlalchemy import select

from backend.collectors.ssh_config import check_target, key_path
from backend.collectors.ssh_protocol import COLLECTOR_VERSION
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import CollectionRun, Job, ReportRun, utcnow
from backend.reports.contracts import TEMPLATE_VERSION
from backend.reports.snapshot import digest, freeze_report


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


def queue_report(db, analysis, include_ai, key, actor=None):
    report_id, frozen_at = uuid4(), utcnow()
    content = freeze_report(db, analysis, report_id, frozen_at, include_ai)
    pinned = content.model_dump(mode="json")
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
