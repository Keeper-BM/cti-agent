"""Versioned, source-attributed CVE library. No asset assessment is performed here."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.schemas.jobs import JobResponse
from backend.api.schemas.sources import (
    CVEDetail,
    DocumentInfo,
    RecordList,
    RecordResponse,
    SnapshotList,
    SourceStatusList,
    SourceSyncRequest,
)
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import Job, SecuritySnapshot, SourceDocument, SourceRecord, SourceRun
from backend.sources.contracts import CVE_PATTERN, SOURCE_INFO, SourceId
from backend.sources.http import oracle_url
from backend.sources.service import current_snapshot_ids

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/status", response_model=SourceStatusList)
def get_source_status(db: Database):
    items = []
    for source_id, (name, purpose, url) in SOURCE_INFO.items():
        job = db.scalar(
            select(Job)
            .join(SourceRun, Job.id == SourceRun.job_id)
            .where(SourceRun.source_id == source_id)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        snapshot = db.scalar(
            select(SecuritySnapshot)
            .where(SecuritySnapshot.source_id == source_id)
            .order_by(SecuritySnapshot.captured_at.desc(), SecuritySnapshot.id.desc())
            .limit(1)
        )
        items.append(
            {
                "source_id": source_id,
                "name": name,
                "purpose": purpose,
                "url": url,
                "latest_job": job,
                "latest_snapshot": snapshot,
            }
        )
    return {
        "items": items,
        "nvd_key_configured": bool(get_settings().nvd_api_key.get_secret_value()),
    }


def request_scope(source_id: str, payload: SourceSyncRequest) -> tuple[str, dict]:
    allowed = {
        "ubuntu": {"release", "package"},
        "nvd": {"cve_id"},
        "kev": set(),
        "apache": set(),
        "oracle": {"url"},
    }
    if payload.model_fields_set - allowed[source_id]:
        raise AppError("INVALID_SYNC_INPUT", "선택한 출처에 맞지 않는 입력입니다.", 422)
    if source_id == "ubuntu":
        return f"{payload.release}:{payload.package}", {
            "release": payload.release,
            "package": payload.package,
        }
    if source_id == "nvd":
        if not payload.cve_id:
            raise AppError("CVE_REQUIRED", "NVD에서 조회할 CVE 번호를 입력하세요.", 422)
        return payload.cve_id, {"cve_id": payload.cve_id}
    if source_id == "oracle":
        if not payload.url:
            raise AppError(
                "SOURCE_URL_REQUIRED", "Oracle 공식 공지 주소를 선택하거나 입력하세요.", 422
            )
        url = oracle_url(payload.url)
        return url, {"url": url}
    return "catalog", {}


@router.post("/{source_id}/sync", response_model=JobResponse, status_code=202)
def sync_source(
    source_id: SourceId,
    payload: SourceSyncRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    scope, parameters = request_scope(source_id, payload)
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        run = db.get(SourceRun, existing.id)
        if not run or run.source_id != source_id or run.parameters != parameters:
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return existing
    pending = db.scalar(
        select(Job)
        .join(SourceRun, Job.id == SourceRun.job_id)
        .where(
            SourceRun.source_id == source_id,
            SourceRun.scope_key == scope,
            Job.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if pending:
        return pending
    job = Job(kind="SOURCE_SYNC", idempotency_key=idempotency_key)
    db.add(job)
    try:
        db.flush()
        db.add(
            SourceRun(job_id=job.id, source_id=source_id, scope_key=scope, parameters=parameters)
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "SYNC_CONFLICT", "요청이 중복되었습니다. 작업 상태를 확인하세요.", 409
        ) from None
    db.refresh(job)
    return job


@router.get("/snapshots", response_model=SnapshotList)
def snapshots(
    db: Database,
    source_id: SourceId | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conditions = [] if source_id is None else [SecuritySnapshot.source_id == source_id]
    return {
        "items": list(
            db.scalars(
                select(SecuritySnapshot)
                .where(*conditions)
                .order_by(SecuritySnapshot.captured_at.desc(), SecuritySnapshot.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": db.scalar(select(func.count()).select_from(SecuritySnapshot).where(*conditions)),
    }


def record_response(row) -> RecordResponse:
    record, document, snapshot = row
    return RecordResponse(
        id=record.id,
        snapshot_id=record.snapshot_id,
        source_id=record.source_id,
        scope_key=snapshot.scope_key,
        data=record.payload,
        document=DocumentInfo.model_validate(document),
    )


def records_query():
    return (
        select(SourceRecord, SourceDocument, SecuritySnapshot)
        .join(SourceDocument, SourceRecord.document_id == SourceDocument.id)
        .join(SecuritySnapshot, SourceRecord.snapshot_id == SecuritySnapshot.id)
        .options(defer(SourceDocument.raw_text))
    )


@router.get("/records", response_model=RecordList)
def records(
    db: Database,
    source_id: SourceId | None = None,
    cve: str = Query("", max_length=40),
    package: str | None = Query(None, max_length=200),
    release: str | None = Query(None, max_length=16),
    snapshot_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if snapshot_id is not None and db.get(SecuritySnapshot, str(snapshot_id)) is None:
        raise AppError("SNAPSHOT_NOT_FOUND", "자료 기준본을 찾을 수 없습니다.", 404)
    conditions = (
        [SourceRecord.snapshot_id == str(snapshot_id)]
        if snapshot_id
        else [SourceRecord.snapshot_id.in_(current_snapshot_ids())]
    )
    if source_id:
        conditions.append(SourceRecord.source_id == source_id)
    if cve:
        conditions.append(SourceRecord.cve_id.contains(cve.strip().upper(), autoescape=True))
    if package:
        conditions.append(SourceRecord.package_name == package)
    if release:
        conditions.append(SourceRecord.release == release)
    rows = db.execute(
        records_query()
        .where(*conditions)
        .order_by(SourceRecord.cve_id.desc(), SourceRecord.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [record_response(row) for row in rows],
        "total": db.scalar(select(func.count()).select_from(SourceRecord).where(*conditions)),
    }


@router.get("/cves/{cve_id}", response_model=CVEDetail)
def cve_detail(cve_id: Annotated[str, Path(pattern=CVE_PATTERN)], db: Database):
    items = [
        record_response(row)
        for row in db.execute(
            records_query()
            .where(
                SourceRecord.cve_id == cve_id, SourceRecord.snapshot_id.in_(current_snapshot_ids())
            )
            .order_by(SourceRecord.source_id, SecuritySnapshot.captured_at.desc())
        )
    ]
    if not items:
        raise AppError("CVE_NOT_FOUND", "저장된 CVE 자료가 없습니다. 자료를 먼저 가져오세요.", 404)
    order = {source: index for index, source in enumerate(SOURCE_INFO)}
    items.sort(key=lambda item: order[item.source_id])
    kev = db.scalar(
        select(SecuritySnapshot)
        .where(SecuritySnapshot.source_id == "kev")
        .order_by(SecuritySnapshot.captured_at.desc(), SecuritySnapshot.id.desc())
        .limit(1)
    )
    urls = set()
    for item in items:
        for url in item.data.references:
            try:
                urls.add(oracle_url(url))
            except (AppError, ValueError):
                pass
    return CVEDetail(
        cve_id=cve_id,
        records=items,
        kev_snapshot=kev,
        kev_status="LISTED"
        if any(item.source_id == "kev" for item in items)
        else "NOT_LISTED"
        if kev
        else "NOT_FETCHED",
        oracle_urls=sorted(urls),
    )


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, db: Database):
    document = db.get(SourceDocument, str(document_id))
    if not document:
        raise AppError("DOCUMENT_NOT_FOUND", "원문을 찾을 수 없습니다.", 404)
    return {
        **DocumentInfo.model_validate(document).model_dump(mode="json"),
        "raw_text": document.raw_text,
    }
