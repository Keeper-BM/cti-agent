from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.collectors.ssh_protocol import COLLECTOR_VERSION, make_inventory
from backend.collectors.ssh_transport import collect_ssh
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import Asset, CollectionRun, InventoryRecord, Job, SSHProfile, utcnow


def collect_job(engine: Engine, job_id: str) -> dict:
    with Session(engine) as db:
        run = db.scalar(select(CollectionRun).where(CollectionRun.job_id == job_id))
        if run is None:
            raise AppError("COLLECTION_NOT_FOUND", "수집 작업 입력을 찾을 수 없습니다.", 500)
        if run.completed_at:
            return db.get(Job, job_id).result
        if run.collector_version != COLLECTOR_VERSION:
            raise AppError(
                "COLLECTOR_CHANGED", "수집기 버전이 변경되었습니다. 새로 요청하세요.", 409
            )
        if not db.get(Asset, run.asset_id).is_active:
            raise AppError("ASSET_INACTIVE", "비활성 자산의 수집은 실행하지 않습니다.", 409)
        profile = db.get(SSHProfile, run.profile_id)
        run_id, asset_id = run.id, run.asset_id
        db.expunge(profile)
    results = collect_ssh(profile, get_settings())
    inventory, evidence = make_inventory(UUID(asset_id), run_id, results, profile.host_fingerprint)
    partial = (
        inventory.collection_status == "PARTIAL"
        or any(r.exit_code != 0 for r in results)
        or any(service.status == "UNKNOWN" for service in evidence.services)
    )
    with Session(engine) as db, db.begin():
        job = db.get(Job, job_id)
        if job.status != "RUNNING":
            raise AppError(
                "COLLECTION_INTERRUPTED", "수집 작업이 중단되어 저장하지 않았습니다.", 409
            )
        db.add(
            InventoryRecord(
                inventory_id=str(inventory.inventory_id),
                asset_id=asset_id,
                collected_at=inventory.collected_at,
                ingested_at=inventory.ingested_at,
                os_release=inventory.os.version_id,
                package_count=len(inventory.packages),
                collection_status=inventory.collection_status,
                is_synthetic=False,
                payload=inventory.model_dump(mode="json"),
            )
        )
        db.flush()
        run = db.get(CollectionRun, run_id)
        run.inventory_id = str(inventory.inventory_id)
        run.evidence = evidence.model_dump(mode="json")
        run.active_slot = None
        run.completed_at = utcnow()
        result = {
            "message": f"SSH로 패키지 {len(inventory.packages)}개를 저장했습니다."
            + (
                " 일부 정보는 확인하지 못했습니다."
                if partial
                else " 설치 출처는 미검증 상태입니다."
            ),
            "inventory_id": run.inventory_id,
            "collection_id": run_id,
        }
        job.status, job.result, job.finished_at = (
            "PARTIAL" if partial else "SUCCEEDED",
            result,
            run.completed_at,
        )
    return result
