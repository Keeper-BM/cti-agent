"""Asset-scoped file ingestion and immutable package inventory history."""

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from backend.api.dependencies import Database
from backend.api.routes.assets import find_asset
from backend.api.schemas.inventories import CsvInventoryImport, InventoryImport, InventoryList
from backend.collectors.csv_import import parse_csv
from backend.collectors.json_import import import_inventory
from backend.core.audit import audit
from backend.core.errors import AppError
from backend.models.contracts import InventorySnapshot
from backend.models.tables import InventoryRecord

router = APIRouter(prefix="/assets/{asset_id}/inventories", tags=["inventories"])


@router.post("", response_model=InventorySnapshot, status_code=201)
def create_inventory(asset_id: UUID, payload: InventoryImport, db: Database):
    asset = find_asset(asset_id, db)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산입니다. 활성화한 뒤 입력하세요.", 409)
    snapshot = import_inventory(asset_id, payload)
    return save_snapshot(snapshot, db)


def save_snapshot(snapshot, db):
    db.add(
        InventoryRecord(
            inventory_id=str(snapshot.inventory_id),
            asset_id=str(snapshot.asset_id),
            collected_at=snapshot.collected_at,
            ingested_at=snapshot.ingested_at,
            os_release=snapshot.os.version_id,
            package_count=len(snapshot.packages),
            collection_status=snapshot.collection_status,
            is_synthetic=snapshot.is_synthetic,
            payload=snapshot.model_dump(mode="json"),
        )
    )
    audit(
        db,
        "inventory.imported",
        asset_id=snapshot.asset_id,
        target_id=snapshot.inventory_id,
        details={"method": snapshot.collection_method, "package_count": len(snapshot.packages)},
    )
    db.commit()
    return snapshot


@router.post("/csv", response_model=InventorySnapshot, status_code=201)
def create_csv(asset_id: UUID, payload: CsvInventoryImport, db: Database):
    asset = find_asset(asset_id, db)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산입니다. 활성화한 뒤 입력하세요.", 409)
    return save_snapshot(parse_csv(asset_id, payload.csv_text), db)


@router.get("", response_model=InventoryList)
def list_inventories(
    asset_id: UUID,
    db: Database,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    find_asset(asset_id, db)
    scope = InventoryRecord.asset_id == str(asset_id)
    items = db.execute(
        select(
            InventoryRecord.inventory_id,
            InventoryRecord.asset_id,
            InventoryRecord.collected_at,
            InventoryRecord.ingested_at,
            InventoryRecord.os_release,
            InventoryRecord.package_count,
            InventoryRecord.collection_status,
            InventoryRecord.is_synthetic,
        )
        .where(scope)
        .order_by(InventoryRecord.ingested_at.desc(), InventoryRecord.inventory_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": list(items.mappings()),
        "total": db.scalar(select(func.count()).select_from(InventoryRecord).where(scope)),
    }


@router.get("/{inventory_id}", response_model=InventorySnapshot)
def get_inventory(asset_id: UUID, inventory_id: UUID, db: Database):
    find_asset(asset_id, db)
    record = db.get(InventoryRecord, str(inventory_id))
    if record is None or record.asset_id != str(asset_id):
        raise AppError("INVENTORY_NOT_FOUND", "이 자산의 입력 기록을 찾을 수 없습니다.", 404)
    return InventorySnapshot.model_validate(record.payload)
