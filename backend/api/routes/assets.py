from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.api.dependencies import Database
from backend.api.schemas.assets import AssetCreate, AssetList, AssetPatch, AssetResponse
from backend.core.errors import AppError
from backend.models.tables import Asset

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=AssetList)
def list_assets(db: Database, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    items = db.scalars(select(Asset).order_by(Asset.created_at.desc()).limit(limit).offset(offset))
    return {"items": list(items), "total": db.scalar(select(func.count()).select_from(Asset))}


@router.post("", response_model=AssetResponse, status_code=201)
def create_asset(payload: AssetCreate, db: Database):
    asset = Asset(**payload.model_dump())
    db.add(asset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_ASSET", "같은 이름의 자산이 이미 있습니다.", 409) from None
    db.refresh(asset)
    return asset


def find_asset(asset_id: UUID, db: Database) -> Asset:
    asset = db.get(Asset, str(asset_id))
    if asset is None:
        raise AppError("ASSET_NOT_FOUND", "자산을 찾을 수 없습니다.", 404)
    return asset


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: UUID, db: Database):
    return find_asset(asset_id, db)


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: UUID, payload: AssetPatch, db: Database):
    asset = find_asset(asset_id, db)
    asset.is_active = payload.is_active
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/{asset_id}/collections", status_code=501)
def collect_asset(asset_id: UUID, db: Database):
    find_asset(asset_id, db)
    raise AppError("FEATURE_NOT_IMPLEMENTED", "SSH 수집기는 아직 연결되지 않았습니다.", 501)
