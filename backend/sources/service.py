from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import (
    Job,
    SecuritySnapshot,
    SourceDocument,
    SourceRecord,
    SourceRun,
    utcnow,
)
from backend.sources.adapters import collect
from backend.sources.contracts import ADAPTER_VERSION
from backend.sources.http import SourceHTTP


def current_snapshot_ids():
    revisions = select(
        SecuritySnapshot.id,
        func.row_number()
        .over(
            partition_by=(SecuritySnapshot.source_id, SecuritySnapshot.scope_key),
            order_by=(SecuritySnapshot.captured_at.desc(), SecuritySnapshot.id.desc()),
        )
        .label("position"),
    ).subquery()
    return select(revisions.c.id).where(revisions.c.position == 1)


def sync_source_job(engine: Engine, job_id: str) -> dict:
    with Session(engine) as db:
        run = db.get(SourceRun, job_id)
        if run is None:
            raise AppError("SOURCE_RUN_MISSING", "수집 작업의 입력을 찾을 수 없습니다.", 500)
        source_id, scope, parameters = run.source_id, run.scope_key, run.parameters
    http = SourceHTTP(get_settings().nvd_api_key.get_secret_value())
    try:
        documents = collect(source_id, parameters, http)
    finally:
        http.close()
    if not documents or sum(len(d.records) for d in documents) > 10000:
        raise AppError("SOURCE_RECORD_LIMIT", "수집 자료 개수가 허용 범위를 벗어났습니다.", 502)
    # All downloads must validate before publishing any new current snapshot.
    with Session(engine) as db, db.begin():
        snapshot = SecuritySnapshot(
            id=str(uuid4()),
            job_id=job_id,
            source_id=source_id,
            scope_key=scope,
            adapter_version=ADAPTER_VERSION,
            document_count=len(documents),
            record_count=0,
        )
        db.add(snapshot)
        db.flush()
        seen = {}
        for result in documents:
            download = result.download
            document = SourceDocument(
                id=str(uuid4()),
                snapshot_id=snapshot.id,
                url=download.url,
                captured_at=download.captured_at,
                sha256=download.sha256,
                content_type=download.content_type,
                raw_text=download.text,
            )
            db.add(document)
            db.flush()
            for record in result.records:
                identity = record.cve_id, record.package_name, record.release
                value = record.model_dump(mode="json")
                if identity in seen:
                    if seen[identity] != value:
                        raise AppError(
                            "SOURCE_CONFLICT",
                            "같은 자료 내 CVE 내용이 상충합니다. 이전 자료를 유지합니다.",
                            502,
                        )
                    continue
                seen[identity] = value
                db.add(
                    SourceRecord(
                        snapshot_id=snapshot.id,
                        document_id=document.id,
                        source_id=source_id,
                        cve_id=record.cve_id,
                        package_name=record.package_name,
                        release=record.release,
                        payload=value,
                    )
                )
        snapshot.record_count = len(seen)
        result = {
            "message": f"공식 자료 {len(seen)}건을 저장했습니다.",
            "source_id": source_id,
            "snapshot_id": snapshot.id,
            "record_count": len(seen),
            "scope_key": scope,
        }
        job = db.get(Job, job_id)
        job.status = "SUCCEEDED"
        job.result = result
        job.finished_at = utcnow()
    return result
