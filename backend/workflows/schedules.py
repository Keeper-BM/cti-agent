"""Queue existing batch workflows from persistent KST schedules."""

import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.auth.access import Principal, principal_for
from backend.core.config import get_settings
from backend.core.diagnostics import safe_exception_details
from backend.core.errors import AppError
from backend.models.tables import (
    Asset,
    User,
    WorkflowBatch,
    WorkflowSchedule,
    WorkflowScheduleAsset,
    WorkflowScheduleRun,
    utcnow,
)
from backend.workflows.batch import enqueue_batch

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9), "KST")
REVOKED = "예약을 등록한 계정의 실행 권한 또는 자산 접근 권한을 확인하세요."


def next_occurrence(local_time: str, weekday: int | None, after: datetime) -> datetime:
    local = after.astimezone(KST)
    hour, minute = map(int, local_time.split(":"))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        candidate += timedelta(days=(weekday - local.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7 if weekday is not None else 1)
    return candidate.astimezone(UTC)


def schedule_principal(db, requested_by):
    if requested_by is None:
        if get_settings().auth_mode == "token":
            return Principal(None, "development", "개발 관리자", "ADMIN")
    else:
        user = db.get(User, requested_by)
        if user and user.is_active and user.role in {"ADMIN", "OPERATOR"}:
            return principal_for(db, user)
    raise AppError("SCHEDULE_ACCESS_REVOKED", REVOKED, 403)


def dispatch(db, schedule_id, now):
    schedule = db.scalar(
        select(WorkflowSchedule).where(WorkflowSchedule.id == schedule_id).with_for_update()
    )
    if not schedule or schedule.next_run_at is None:
        return
    next_at = next_occurrence(schedule.local_time, schedule.weekday, now)
    claimed = db.execute(
        update(WorkflowSchedule)
        .where(
            WorkflowSchedule.id == schedule_id,
            WorkflowSchedule.next_run_at == schedule.next_run_at,
            WorkflowSchedule.next_run_at <= now,
            WorkflowSchedule.updated_at == schedule.updated_at,
        )
        .values(next_run_at=next_at)
        .execution_options(synchronize_session=False)
    )
    if not claimed.rowcount:
        return
    # Coalesce missed slots after a restart. The next slot and this run commit together.
    due = next_at - timedelta(days=7 if schedule.weekday is not None else 1)
    if db.scalar(
        select(WorkflowScheduleRun.id).where(
            WorkflowScheduleRun.schedule_id == schedule_id,
            WorkflowScheduleRun.scheduled_for == due,
        )
    ):
        return
    run = WorkflowScheduleRun(schedule_id=schedule_id, scheduled_for=due, created_at=now)
    db.add(run)
    active = db.scalar(
        select(WorkflowScheduleRun.id)
        .join(WorkflowBatch, WorkflowBatch.id == WorkflowScheduleRun.batch_id)
        .where(WorkflowScheduleRun.schedule_id == schedule_id, WorkflowBatch.status == "RUNNING")
        .limit(1)
    )
    if active:
        run.error = "이전 예약 분석이 진행 중이어서 이번 회차는 건너뛰었습니다."
        return

    try:
        principal = schedule_principal(db, schedule.requested_by)
        assets = list(
            db.scalars(
                select(Asset)
                .join(WorkflowScheduleAsset, WorkflowScheduleAsset.asset_id == Asset.id)
                .where(WorkflowScheduleAsset.schedule_id == schedule_id)
                .order_by(Asset.id)
            )
        )
        if not principal.admin and any(asset.id not in principal.asset_ids for asset in assets):
            raise AppError("SCHEDULE_ACCESS_REVOKED", REVOKED, 403)
    except AppError as exc:
        run.error = exc.message
        return
    if not assets:
        run.error = "예약에 연결된 자산이 없습니다."
        return
    db.info["principal"] = principal
    key = f"schedule-{schedule_id}-{due:%Y%m%d%H%M}"
    run.batch_id = enqueue_batch(db, [(asset, None) for asset in assets], key).id


def advance_schedules(engine, now=None):
    now = now or utcnow()
    with Session(engine) as db:
        ids = list(
            db.scalars(
                select(WorkflowSchedule.id)
                .where(WorkflowSchedule.next_run_at <= now)
                .order_by(WorkflowSchedule.next_run_at, WorkflowSchedule.id)
                .limit(20)
            )
        )
    for schedule_id in ids:
        try:
            with Session(engine) as db, db.begin():
                dispatch(db, schedule_id, now)
        except OperationalError as exc:
            logger.warning(
                "Could not dispatch schedule %s: %s", schedule_id, safe_exception_details(exc)
            )
