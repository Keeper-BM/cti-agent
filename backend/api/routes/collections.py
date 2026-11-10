from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.routes.assets import find_asset
from backend.api.schemas.collections import (
    CollectionDetail,
    CollectionList,
    CollectionRequest,
    CollectionResponse,
    SSHProfileInput,
    SSHProfileResponse,
    SSHProfileState,
    SSHSettingsResponse,
)
from backend.auth.access import check_admin
from backend.collectors.ssh_config import allowed_targets, check_target, key_aliases, key_path
from backend.collectors.ssh_protocol import COLLECTOR_VERSION
from backend.core.audit import audit
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import CollectionRun, Job, SSHProfile

router = APIRouter(tags=["collections"])


def response(run, db):
    return {
        **{
            k: getattr(run, k)
            for k in CollectionResponse.model_fields
            if k not in {"job", "profile"}
        },
        "job": db.get(Job, run.job_id),
        "profile": db.get(SSHProfile, run.profile_id),
    }


@router.get("/collections/settings", response_model=SSHSettingsResponse)
def settings():
    config = get_settings()
    targets = sorted(allowed_targets(config))
    keys = key_aliases(config)
    return {
        "enabled": bool(targets and keys),
        "allowed_targets": [
            f"[{host}]:{port}" if ":" in host else f"{host}:{port}" for host, port in targets
        ],
        "key_aliases": keys,
        "timeout_seconds": config.ssh_timeout_seconds,
        "message": "허용한 서버와 등록한 인증키만 사용할 수 있습니다."
        if targets and keys
        else "백엔드에 SSH_ALLOWED_TARGETS와 인증키 파일을 설정하세요.",
    }


@router.get("/assets/{asset_id}/ssh-profile", response_model=SSHProfileState)
def get_profile(asset_id: UUID, db: Database):
    find_asset(asset_id, db)
    profile = db.scalar(
        select(SSHProfile)
        .where(SSHProfile.asset_id == str(asset_id))
        .order_by(SSHProfile.created_at.desc(), SSHProfile.id.desc())
        .limit(1)
    )
    return {"profile": profile}


@router.put("/assets/{asset_id}/ssh-profile", response_model=SSHProfileResponse)
def save_profile(asset_id: UUID, payload: SSHProfileInput, db: Database):
    check_admin(db)
    asset = find_asset(asset_id, db)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산의 연결 설정은 변경할 수 없습니다.", 409)
    config = get_settings()
    check_target(config, payload.host, payload.port)
    key_path(config, payload.key_alias)
    profile = SSHProfile(asset_id=str(asset_id), **payload.model_dump())
    db.add(profile)
    db.flush()
    audit(db, "ssh_profile.saved", asset_id=asset_id, target_id=profile.id)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/assets/{asset_id}/collections", response_model=CollectionResponse, status_code=202)
def create_collection(
    asset_id: UUID,
    payload: CollectionRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    asset = find_asset(asset_id, db)
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        run = db.scalar(select(CollectionRun).where(CollectionRun.job_id == existing.id))
        if (
            run is None
            or run.asset_id != str(asset_id)
            or run.profile_id != str(payload.profile_id)
        ):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(run, db)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산은 수집할 수 없습니다.", 409)
    profile = db.get(SSHProfile, str(payload.profile_id))
    if profile is None or profile.asset_id != str(asset_id):
        raise AppError("SSH_PROFILE_NOT_FOUND", "이 자산의 SSH 연결 설정을 찾을 수 없습니다.", 404)
    config = get_settings()
    check_target(config, profile.host, profile.port)
    key_path(config, profile.key_alias)
    if db.scalar(select(CollectionRun.id).where(CollectionRun.active_slot == str(asset_id))):
        raise AppError("COLLECTION_BUSY", "이 자산을 수집 중입니다. 완료 후 다시 요청하세요.", 409)
    job = Job(kind="SSH_COLLECTION", asset_id=str(asset_id), idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        run = CollectionRun(
            job_id=job.id,
            asset_id=str(asset_id),
            profile_id=profile.id,
            active_slot=str(asset_id),
            collector_version=COLLECTOR_VERSION,
        )
        db.add(run)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(
            "COLLECTION_CONFLICT", "중복 수집 요청입니다. 작업 상태를 확인하세요.", 409
        ) from None
    db.refresh(run)
    return response(run, db)


@router.get("/assets/{asset_id}/collections", response_model=CollectionList)
def list_collections(
    asset_id: UUID, db: Database, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)
):
    find_asset(asset_id, db)
    condition = CollectionRun.asset_id == str(asset_id)
    runs = db.scalars(
        select(CollectionRun)
        .options(defer(CollectionRun.evidence))
        .where(condition)
        .order_by(CollectionRun.created_at.desc(), CollectionRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(r, db) for r in runs],
        "total": db.scalar(select(func.count()).select_from(CollectionRun).where(condition)),
    }


@router.get("/assets/{asset_id}/collections/{collection_id}", response_model=CollectionDetail)
def get_collection(asset_id: UUID, collection_id: UUID, db: Database):
    find_asset(asset_id, db)
    run = db.get(CollectionRun, str(collection_id))
    if run is None or run.asset_id != str(asset_id):
        raise AppError("COLLECTION_NOT_FOUND", "이 자산의 수집 기록을 찾을 수 없습니다.", 404)
    return {**response(run, db), "evidence": run.evidence}
