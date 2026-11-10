from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from backend.api.dependencies import Database
from backend.api.routes.assets import find_asset
from backend.api.schemas.verifications import (
    VerificationDetail,
    VerificationList,
    VerificationRequest,
    VerificationResponse,
)
from backend.collectors.ssh_config import check_target, key_path
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.contracts import InventorySnapshot
from backend.models.tables import CollectionRun, InventoryRecord, Job, SSHProfile, VerificationRun
from backend.verification.archive import gpg_executable
from backend.verification.contracts import PACKAGES, VERSION

router = APIRouter(tags=["verifications"])


def response(run, db):
    return {
        **{k: getattr(run, k) for k in VerificationResponse.model_fields if k != "job"},
        "job": db.get(Job, run.job_id),
    }


@router.post(
    "/assets/{asset_id}/verifications", response_model=VerificationResponse, status_code=202
)
def create_verification(
    asset_id: UUID,
    payload: VerificationRequest,
    db: Database,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    asset = find_asset(asset_id, db)
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        run = db.scalar(select(VerificationRun).where(VerificationRun.job_id == existing.id))
        if (
            not run
            or run.asset_id != str(asset_id)
            or run.inventory_id != str(payload.inventory_id)
        ):
            raise AppError(
                "IDEMPOTENCY_CONFLICT", "같은 요청 키가 다른 작업에 사용되었습니다.", 409
            )
        return response(run, db)
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", "비활성 자산은 검증할 수 없습니다.", 409)
    row = db.get(InventoryRecord, str(payload.inventory_id))
    if not row or row.asset_id != str(asset_id):
        raise AppError("INVENTORY_NOT_FOUND", "이 자산의 패키지 기록을 찾을 수 없습니다.", 404)
    inventory = InventorySnapshot.model_validate(row.payload)
    origin = db.scalar(select(CollectionRun).where(CollectionRun.inventory_id == row.inventory_id))
    if origin is None:
        origin = db.scalar(
            select(VerificationRun).where(VerificationRun.verified_inventory_id == row.inventory_id)
        )
    if not origin or inventory.is_synthetic or inventory.collection_method != "SSH":
        raise AppError(
            "VERIFICATION_SOURCE_REQUIRED",
            "실제 SSH 수집 기록만 공식 파일 검증을 요청할 수 있습니다.",
            422,
        )
    if not any(
        p.binary_name in PACKAGES and p.install_status == "installed" for p in inventory.packages
    ):
        raise AppError("VERIFICATION_OUT_OF_SCOPE", "검증할 Apache2·MySQL 패키지가 없습니다.", 422)
    config = get_settings()
    gpg_executable(config)
    profile = db.get(SSHProfile, origin.profile_id)
    check_target(config, profile.host, profile.port)
    key_path(config, profile.key_alias)
    job = Job(kind="VERIFICATION", asset_id=str(asset_id), idempotency_key=idempotency_key)
    try:
        db.add(job)
        db.flush()
        run = VerificationRun(
            job_id=job.id,
            asset_id=str(asset_id),
            inventory_id=row.inventory_id,
            profile_id=profile.id,
            active_slot=str(asset_id),
            verifier_version=VERSION,
        )
        db.add(run)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("VERIFICATION_BUSY", "이미 검증 중이거나 중복된 요청입니다.", 409) from None
    db.refresh(run)
    return response(run, db)


@router.get("/assets/{asset_id}/verifications", response_model=VerificationList)
def list_verifications(
    asset_id: UUID, db: Database, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)
):
    find_asset(asset_id, db)
    condition = VerificationRun.asset_id == str(asset_id)
    rows = db.scalars(
        select(VerificationRun)
        .options(defer(VerificationRun.evidence))
        .where(condition)
        .order_by(VerificationRun.created_at.desc(), VerificationRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [response(r, db) for r in rows],
        "total": db.scalar(select(func.count()).select_from(VerificationRun).where(condition)),
    }


@router.get("/assets/{asset_id}/verifications/{verification_id}", response_model=VerificationDetail)
def get_verification(asset_id: UUID, verification_id: UUID, db: Database):
    find_asset(asset_id, db)
    run = db.get(VerificationRun, str(verification_id))
    if not run or run.asset_id != str(asset_id):
        raise AppError("VERIFICATION_NOT_FOUND", "이 자산의 검증 기록을 찾을 수 없습니다.", 404)
    return {**response(run, db), "evidence": run.evidence}
