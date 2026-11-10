import hashlib
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.collectors.ssh_protocol import ENV, make_inventory
from backend.collectors.ssh_transport import collect_ssh, run_ssh_commands
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.contracts import InventorySnapshot
from backend.models.enums import OriginStatus
from backend.models.tables import Asset, InventoryRecord, Job, SSHProfile, VerificationRun, utcnow
from backend.verification.archive import ArchiveClient
from backend.verification.compare import compare_package
from backend.verification.contracts import PACKAGES, VERSION, VerificationEvidence
from backend.verification.runtime import confirm_apache_http2

HASHER = (
    ENV
    + "/usr/bin/python3 -c "
    + shlex.quote(Path(__file__).with_name("_remote_hasher.py").read_text(encoding="utf-8"))
)


def identities(inventory):
    return sorted(
        (
            p.binary_name,
            p.architecture or "",
            p.binary_version or "",
            p.source_name or "",
            p.source_version or "",
            p.install_status,
        )
        for p in inventory.packages
        if p.binary_name in PACKAGES
    )


def verify_job(engine, job_id):
    with Session(engine) as db:
        run = db.scalar(select(VerificationRun).where(VerificationRun.job_id == job_id))
        if not run:
            raise AppError("VERIFICATION_NOT_FOUND", "검증 입력을 찾을 수 없습니다.", 500)
        if run.completed_at:
            return db.get(Job, job_id).result
        if run.verifier_version != VERSION:
            raise AppError("VERIFIER_CHANGED", "검증기 버전이 변경됐습니다. 새로 요청하세요.", 409)
        if not db.get(Asset, run.asset_id).is_active:
            raise AppError("ASSET_INACTIVE", "비활성 자산의 검증은 실행하지 않습니다.", 409)
        original = InventorySnapshot.model_validate(
            db.get(InventoryRecord, run.inventory_id).payload
        )
        profile = db.get(SSHProfile, run.profile_id)
        run_id, asset_id = run.id, run.asset_id
        db.expunge(profile)
    config = get_settings()
    outputs = collect_ssh(profile, config)
    inventory, _ = make_inventory(UUID(asset_id), run_id, outputs, profile.host_fingerprint)
    if original.os != inventory.os or identities(original) != identities(inventory):
        raise AppError(
            "VERIFICATION_STALE",
            "패키지나 OS가 입력 기록과 달라졌습니다. 먼저 다시 수집하세요.",
            409,
        )
    archive = ArchiveClient(config)
    try:
        artifacts = archive.resolve(inventory)
    finally:
        archive.close()
    paths = sorted({p for a in artifacts.values() for p in a["files"]})
    observed = {}
    runtime = None
    if paths:
        observer = Path(__file__).with_name("apache_observer.py").read_bytes()
        packet = json.dumps(
            {"paths": paths, "observer_sha256": hashlib.sha256(observer).hexdigest()},
            ensure_ascii=True,
        ).encode("utf-8")
        checks = run_ssh_commands(profile, config, {"files": HASHER}, {"files": packet})
        if checks[0].exit_code:
            raise AppError("FILE_CHECK_FAILED", "서버에서 파일 검사를 완료하지 못했습니다.", 502)
        try:
            result = json.loads(checks[0].stdout)
            packages = next(r.stdout for r in outputs if r.name == "packages")
            if result["before"] != packages or result["after"] != packages:
                raise AppError(
                    "VERIFICATION_STALE",
                    "검증 중 패키지 상태가 바뀌었습니다. 다시 수집하세요.",
                    409,
                )
            observed = result["files"]
            runtime = result.get("apache_runtime")
            if not isinstance(observed, dict) or set(observed) != set(paths):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise AppError(
                "FILE_CHECK_INVALID", "파일 검사 응답 형식을 확인할 수 없습니다.", 502
            ) from None
    results = []
    for package in inventory.packages:
        if package.binary_name not in PACKAGES or package.install_status != "installed":
            continue
        result = compare_package(package, artifacts.get(str(package.package_id)), observed)
        results.append(result)
        package.origin_evidence_ref = run_id
        package.origin_description = result.message
        if result.status == "MATCH":
            package.origin_status = OriginStatus.OFFICIAL_MATCH
    runtime_evidence, runtime_note = confirm_apache_http2(runtime, inventory, artifacts, run_id)
    inventory.apache_http2 = runtime_evidence
    evidence = VerificationEvidence(
        apache_http2=runtime_evidence,
        apache_runtime_note=runtime_note,
        checked_at=datetime.now(UTC),
        original_inventory_id=str(original.inventory_id),
        host_fingerprint=profile.host_fingerprint,
        packages=results,
        warnings=[
            "파일 일치를 검사했습니다. "
            "기록된 실행 조건 외의 상태·과거 설치 경로·침해 여부는 미검증입니다.",
            "설정 파일은 관리자가 바꿀 수 있어 일치 판단에서 제외하고 별도로 표시합니다.",
        ],
    )
    inventory.verification_id = UUID(run_id)
    inventory.collector_version += "+" + VERSION
    matched = sum(p.status == "MATCH" for p in results)
    with Session(engine) as db, db.begin():
        job = db.get(Job, job_id)
        if job.status != "RUNNING" or not db.get(Asset, asset_id).is_active:
            raise AppError(
                "VERIFICATION_INTERRUPTED", "검증 작업이 중단되어 저장하지 않았습니다.", 409
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
        run = db.get(VerificationRun, run_id)
        run.verified_inventory_id = str(inventory.inventory_id)
        run.evidence = evidence.model_dump(mode="json")
        run.completed_at = utcnow()
        run.active_slot = None
        job.status = "SUCCEEDED" if results and matched == len(results) else "PARTIAL"
        job.finished_at = run.completed_at
        job.result = {
            "message": f"패키지 {len(results)}개 중 {matched}개의 공식 파일 일치를 확인했습니다.",
            "verification_id": run_id,
            "inventory_id": run.verified_inventory_id,
        }
        result = job.result
    return result
