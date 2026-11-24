"""Advance each workflow stage and enqueue its children in the same transaction."""

import logging
from datetime import UTC
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from backend.assessment.contracts import PACKAGES, RELEASES
from backend.assessment.engine import source_for
from backend.assessment.service import pin_inputs
from backend.auth.access import authorize_actor
from backend.core.audit import audit
from backend.core.diagnostics import safe_exception_details
from backend.core.errors import AppError
from backend.models.contracts import InventorySnapshot
from backend.models.tables import (
    AnalysisRun,
    Asset,
    AssetWorkflow,
    CollectionRun,
    InventoryRecord,
    Job,
    ReportRun,
    SecuritySnapshot,
    SourceRecord,
    SourceRun,
    VerificationRun,
    WorkflowBatchAsset,
    utcnow,
)
from backend.sources.http import oracle_url
from backend.verification.queue import queue_verification
from backend.workflows.queue import queue_report

logger = logging.getLogger(__name__)
ACTIVE = {"QUEUED", "RUNNING"}
NVD_LIMIT = 3
ORACLE_LIMIT = 2


def iso(value):
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def step(run, name):
    run.stage = name
    run.timeline = {**run.timeline, name: iso(utcnow())}


def warn(run, message):
    if message not in run.warnings:
        run.warnings = [*run.warnings, message]


def finish(db, run, message=None):
    if message:
        for child in db.scalars(
            select(Job).where(
                Job.asset_id == run.asset_id,
                Job.idempotency_key.startswith(f"wf-{run.id}-"),
                Job.status == "QUEUED",
            )
        ):
            child.status, child.error_code, child.finished_at = (
                "FAILED",
                "WORKFLOW_STOPPED",
                utcnow(),
            )
            child.result = {"message": message}
            if child.kind == "SSH_COLLECTION":
                collection = db.scalar(
                    select(CollectionRun).where(CollectionRun.job_id == child.id)
                )
                if collection:
                    collection.active_slot = None
            if child.kind == "VERIFICATION":
                proof = db.scalar(select(VerificationRun).where(VerificationRun.job_id == child.id))
                if proof:
                    proof.active_slot = None
    run.error = message
    run.status = "FAILED" if message else "COMPLETED"
    run.finished_at = utcnow()
    run.active_slot = None
    audit(
        db,
        "workflow.finished",
        asset_id=run.asset_id,
        target_id=run.id,
        actor_id=run.requested_by,
        outcome=run.status,
        details={"stage": run.stage},
    )


def queue_source(db, run, source, scope, parameters):
    batch_id = db.scalar(
        select(WorkflowBatchAsset.batch_id).where(
            WorkflowBatchAsset.workflow_id == run.id, WorkflowBatchAsset.carried.is_(False)
        )
    )
    key = f"wf-{run.id}-source-{len(run.sources)}"
    job = None
    if batch_id:
        # Keep shared jobs independent of a single workflow's cancellation.
        scope_hash = sha256(f"{source}\0{scope}".encode()).hexdigest()[:40]
        key = f"batch-{batch_id}-source-{scope_hash}"
        job = db.scalar(select(Job).where(Job.idempotency_key == key))
    if job is None:
        job = Job(
            kind="SOURCE_SYNC",
            asset_id=run.asset_id,
            requested_by=run.requested_by,
            idempotency_key=key,
        )
        db.add(job)
        db.flush()
        db.add(SourceRun(job_id=job.id, source_id=source, scope_key=scope, parameters=parameters))
    run.sources = [
        *run.sources,
        {"source": source, "scope": scope, "job_id": job.id, "status": "QUEUED"},
    ]


def use_verified_inventory(db, run):
    key = f"wf-{run.id}-verify"
    job = db.scalar(select(Job).where(Job.idempotency_key == key))
    if not job:
        try:
            queue_verification(db, db.get(InventoryRecord, run.inventory_id), key, run.requested_by)
        except AppError as exc:
            warn(run, f"공식 패키지 파일 미검증 · {exc.message}")
            return True
        run.timeline = {**run.timeline, "verification": iso(utcnow())}
        return False
    proof = db.scalar(select(VerificationRun).where(VerificationRun.job_id == job.id))
    if not proof or proof.inventory_id != run.inventory_id or proof.asset_id != run.asset_id:
        raise AppError("VERIFICATION_INPUT_CHANGED", "검증 기록의 입력이 일치하지 않습니다.", 409)
    if job.status in ACTIVE:
        return False
    if job.error_code == "VERIFICATION_STALE":
        finish(db, run, "수집 이후 패키지 상태가 바뀌었습니다. 다시 분석하세요.")
        return False
    if proof.verified_inventory_id and job.status in {"SUCCEEDED", "PARTIAL"}:
        run.inventory_id = proof.verified_inventory_id
        if job.status == "PARTIAL":
            warn(run, (job.result or {}).get("message") or "일부 패키지 파일만 대조했습니다.")
    else:
        message = (job.result or {}).get("message") or "파일 검사를 완료하지 못했습니다."
        warn(run, f"공식 패키지 파일 미검증 · {message}")
    return True


def begin_sources(db, run):
    if run.collection_id:
        collection = db.get(CollectionRun, run.collection_id)
        job = db.get(Job, collection.job_id)
        if job.status in ACTIVE:
            return
        if not collection.inventory_id or job.status not in {"PARTIAL", "SUCCEEDED"}:
            finish(db, run, (job.result or {}).get("message") or "SSH 패키지 수집에 실패했습니다.")
            return
        run.inventory_id = collection.inventory_id
        if job.status == "PARTIAL":
            warn(run, "SSH로 일부 정보만 확인했습니다. 분석에 수집 범위를 함께 표시합니다.")
        if not use_verified_inventory(db, run):
            return
    record = db.get(InventoryRecord, run.inventory_id)
    inventory = InventorySnapshot.model_validate(record.payload)
    if inventory.collection_status == "FAILED":
        finish(db, run, "실패한 패키지 기록입니다. 다시 수집하거나 다른 입력을 선택하세요.")
        return
    step(run, "sources")
    packages = {
        source_for(p) for p in inventory.packages if p.install_status == "installed"
    } & PACKAGES
    if inventory.os.id != "ubuntu" or inventory.os.version_id not in RELEASES or not packages:
        warn(
            run, "지원하는 Ubuntu 릴리스와 설치 패키지 조합이 없어 공식 자료 대조 대상이 없습니다."
        )
        run.enriched = True
        return
    for package in sorted(packages):
        release = inventory.os.version_id
        queue_source(
            db, run, "ubuntu", f"{release}:{package}", {"release": release, "package": package}
        )
    queue_source(db, run, "kev", "catalog", {})
    if "apache2" in packages:
        queue_source(db, run, "apache", "catalog", {})


def settle_sources(db, run):
    items = []
    for item in run.sources:
        if item["status"] not in ACTIVE:
            items.append(item)
            continue
        job = db.get(Job, item["job_id"])
        if job.status in ACTIVE:
            items.append({**item, "status": job.status})
            continue
        snapshot = db.scalar(select(SecuritySnapshot).where(SecuritySnapshot.job_id == job.id))
        state = "UPDATED"
        if snapshot is None:
            saved = select(SecuritySnapshot).where(
                SecuritySnapshot.source_id == item["source"],
                SecuritySnapshot.scope_key == item["scope"],
            )
            if job.idempotency_key.startswith("batch-") and job.finished_at:
                # Assets that reach this stage later use the same fallback cutoff.
                saved = saved.where(SecuritySnapshot.captured_at <= job.finished_at)
            snapshot = db.scalar(
                saved.order_by(
                    SecuritySnapshot.captured_at.desc(), SecuritySnapshot.id.desc()
                ).limit(1)
            )
            state = "CACHED" if snapshot else "FAILED"
            detail = f"{iso(snapshot.captured_at)} 저장본 사용" if snapshot else "이전 저장본 없음"
            warn(run, f"{item['source']} · {item['scope']} 갱신 실패 · {detail}")
        items.append(
            {
                **item,
                "status": state,
                "snapshot_id": snapshot.id if snapshot else None,
                "records": snapshot.record_count if snapshot else None,
                "captured_at": iso(snapshot.captured_at) if snapshot else None,
            }
        )
    if items != run.sources:
        run.sources = items
    return not any(i["status"] in ACTIVE for i in items)


def enrich(db, run):
    ubuntu_ids = [
        s["snapshot_id"] for s in run.sources if s["source"] == "ubuntu" and s.get("snapshot_id")
    ]
    records = list(db.scalars(select(SourceRecord).where(SourceRecord.snapshot_id.in_(ubuntu_ids))))
    cves = {r.cve_id for r in records}
    kev = next((s.get("snapshot_id") for s in run.sources if s["source"] == "kev"), None)
    known = (
        set(db.scalars(select(SourceRecord.cve_id).where(SourceRecord.snapshot_id == kev)))
        if kev
        else set()
    )

    def priority(cve):
        year, number = cve.split("-")[1:]
        return (cve in known, int(year), int(number))

    for cve in sorted(cves, key=priority, reverse=True)[:NVD_LIMIT]:
        queue_source(db, run, "nvd", cve, {"cve_id": cve})
    if len(cves) > NVD_LIMIT:
        warn(
            run,
            f"NVD 보충 조회는 KEV 등재 여부와 CVE 번호순으로 {NVD_LIMIT}건을 선택했습니다. "
            "Ubuntu 자료는 전체를 대조합니다.",
        )
    urls = []
    for row in sorted(records, key=lambda r: priority(r.cve_id), reverse=True):
        if row.package_name != "mysql-8.0":
            continue
        for ref in row.payload.get("references", []):
            try:
                url = oracle_url(ref)
            except AppError:
                continue
            if url not in urls:
                urls.append(url)
    for url in urls[:ORACLE_LIMIT]:
        queue_source(db, run, "oracle", url, {"url": url})
    if any(row.package_name == "mysql-8.0" for row in records):
        warn(
            run,
            "MySQL은 Ubuntu 자료에 연결된 Oracle 공식 공지 "
            f"{min(len(urls), ORACLE_LIMIT)}건을 보충 조회 대상으로 선택했습니다.",
        )
    run.enriched = True


def begin_analysis(db, run):
    if not settle_sources(db, run):
        return
    if any(s["source"] == "ubuntu" and s["status"] == "FAILED" for s in run.sources):
        finish(
            db,
            run,
            "Ubuntu 기준 자료를 확보하지 못했습니다. 출처 상태를 확인한 뒤 다시 실행하세요.",
        )
        return
    if not run.enriched:
        enrich(db, run)
        if any(s["status"] in ACTIVE for s in run.sources):
            return
    job = Job(
        kind="ASSESSMENT",
        asset_id=run.asset_id,
        requested_by=run.requested_by,
        idempotency_key=f"wf-{run.id}-analysis",
    )
    db.add(job)
    db.flush()
    ids = [s["snapshot_id"] for s in run.sources if s.get("snapshot_id")]
    analysis = pin_inputs(db, db.get(InventoryRecord, run.inventory_id), job, snapshot_ids=ids)
    analysis.warnings = [*analysis.warnings, *run.warnings]
    db.add(analysis)
    db.flush()
    run.analysis_id = analysis.id
    step(run, "analysis")


def advance(db, run):
    authorize_actor(db, run.requested_by, run.asset_id, "WORKFLOW")
    if not db.get(Asset, run.asset_id).is_active:
        finish(db, run, "비활성화된 자산입니다. 자동 분석을 중단했습니다.")
        return
    if run.stage == "inventory":
        begin_sources(db, run)
    elif run.stage == "sources":
        begin_analysis(db, run)
    else:
        result = (
            db.get(AnalysisRun, run.analysis_id)
            if run.stage == "analysis"
            else db.get(ReportRun, run.report_id, options=[load_only(ReportRun.job_id)])
        )
        job = db.get(Job, result.job_id)
        if job.status in ACTIVE:
            return
        if job.status != "SUCCEEDED":
            finish(
                db,
                run,
                (job.result or {}).get("message")
                or f"작업을 완료하지 못했습니다 ({job.error_code}).",
            )
            return
        if run.stage == "analysis":
            report = queue_report(
                db, result, True, f"wf-{run.id}-report", run.requested_by, generate_ai_summary=True
            )
            run.report_id = report.id
            step(run, "report")
        else:
            finish(db, run)


def advance_workflows(engine):
    with Session(engine) as db:
        ids = list(
            db.scalars(select(AssetWorkflow.id).where(AssetWorkflow.active_slot.is_not(None)))
        )
    for run_id in ids:
        try:
            with Session(engine) as db, db.begin():
                run = db.get(AssetWorkflow, run_id)
                if run.active_slot:
                    advance(db, run)
        except AppError as exc:
            message = exc.message
        except Exception as exc:
            logger.error("Workflow %s failed: %s", run_id, safe_exception_details(exc))
            message = "단계를 준비하지 못했습니다. 실행 기록을 확인한 뒤 다시 시도하세요."
        else:
            continue
        with Session(engine) as db, db.begin():
            run = db.get(AssetWorkflow, run_id)
            if run.active_slot:
                finish(db, run, message)
