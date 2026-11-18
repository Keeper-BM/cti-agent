from sqlalchemy import select

from backend.collectors.ssh_config import check_target, key_path
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.contracts import InventorySnapshot
from backend.models.tables import CollectionRun, Job, SSHProfile, VerificationRun
from backend.verification.archive import gpg_executable
from backend.verification.contracts import PACKAGES, VERSION


def queue_verification(db, row, key, actor=None):
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
    if db.scalar(select(VerificationRun.id).where(VerificationRun.active_slot == row.asset_id)):
        raise AppError("VERIFICATION_BUSY", "이 자산의 파일을 이미 검증 중입니다.", 409)
    job = Job(kind="VERIFICATION", asset_id=row.asset_id, requested_by=actor, idempotency_key=key)
    db.add(job)
    db.flush()
    run = VerificationRun(
        job_id=job.id,
        asset_id=row.asset_id,
        inventory_id=row.inventory_id,
        profile_id=profile.id,
        active_slot=row.asset_id,
        verifier_version=VERSION,
    )
    db.add(run)
    db.flush()
    return run
