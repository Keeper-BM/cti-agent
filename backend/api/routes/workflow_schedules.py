"""Manage recurring analyses and read their scheduled execution history."""

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import delete, func, or_, select, update

from backend.api.dependencies import Database
from backend.api.schemas.workflow_schedules import (
    ChangeKind,
    ScheduleChanges,
    ScheduleEnabled,
    ScheduleInput,
    ScheduleList,
    ScheduleResponse,
    ScheduleRunList,
)
from backend.core.audit import audit
from backend.core.errors import AppError
from backend.models.tables import (
    Asset,
    SSHProfile,
    WorkflowBatch,
    WorkflowSchedule,
    WorkflowScheduleAsset,
    WorkflowScheduleRun,
    utcnow,
)
from backend.workflows.schedule_changes import compare_schedule_run
from backend.workflows.schedules import REVOKED, next_occurrence, schedule_principal

router = APIRouter(prefix="/workflow-schedules", tags=["workflow schedules"])


def visible_schedules(db):
    principal = db.info["principal"]
    statement = select(WorkflowSchedule)
    if not principal.admin:
        statement = statement.where(WorkflowSchedule.requested_by == principal.user_id)
    return statement


def find_schedule(db, schedule_id, *, lock=False):
    statement = visible_schedules(db).where(WorkflowSchedule.id == str(schedule_id))
    schedule = db.scalar(statement.with_for_update() if lock else statement)
    if schedule is None:
        raise AppError("SCHEDULE_NOT_FOUND", "분석 예약을 찾을 수 없습니다.", 404)
    return schedule


def target_ids(db, schedule_id):
    return set(
        db.scalars(
            select(WorkflowScheduleAsset.asset_id).where(
                WorkflowScheduleAsset.schedule_id == schedule_id
            )
        )
    )


def output(db, schedule):
    ids = target_ids(db, schedule.id)
    assets = db.execute(
        select(Asset.id, Asset.asset_name)
        .where(Asset.id.in_(ids))
        .order_by(Asset.asset_name, Asset.id)
    ).all()
    return {
        "id": schedule.id,
        "name": schedule.name,
        "frequency": "DAILY" if schedule.weekday is None else "WEEKLY",
        "weekday": schedule.weekday,
        "local_time": schedule.local_time,
        "next_run_at": schedule.next_run_at,
        "assets": [{"id": asset.id, "asset_name": asset.asset_name} for asset in assets],
        "inaccessible_asset_count": len(ids) - len(assets),
    }


def validate_targets(db, ids, requested_by):
    principal = schedule_principal(db, requested_by)
    ssh_ready = select(SSHProfile.id).where(SSHProfile.asset_id == Asset.id).exists()
    rows = db.execute(select(Asset.id, Asset.is_active, ssh_ready).where(Asset.id.in_(ids))).all()
    if len(rows) != len(ids):
        raise AppError("ASSET_NOT_FOUND", "선택한 자산을 모두 찾을 수 없습니다.", 404)
    if not principal.admin and not ids.issubset(principal.asset_ids):
        raise AppError("SCHEDULE_ACCESS_REVOKED", REVOKED, 403)
    if not all(active and configured for _, active, configured in rows):
        raise AppError("SCHEDULE_TARGET_NOT_READY", "SSH가 설정된 활성 자산을 선택하세요.", 409)


def replace_targets(db, schedule, new, old):
    if removed := old - new:
        db.execute(
            delete(WorkflowScheduleAsset).where(
                WorkflowScheduleAsset.schedule_id == schedule.id,
                WorkflowScheduleAsset.asset_id.in_(removed),
            )
        )
    for asset_id in sorted(new - old):
        db.add(WorkflowScheduleAsset(schedule_id=schedule.id, asset_id=asset_id))


def write_schedule(db, schedule, **values):
    result = db.execute(
        update(WorkflowSchedule)
        .where(
            WorkflowSchedule.id == schedule.id, WorkflowSchedule.updated_at == schedule.updated_at
        )
        .values(updated_at=utcnow(), **values)
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        raise AppError("SCHEDULE_CHANGED", "예약이 변경되었습니다. 다시 불러와 주세요.", 409)


@router.get("", response_model=ScheduleList)
def list_schedules(db: Database, limit: int = Query(10, ge=1, le=20), offset: int = Query(0, ge=0)):
    statement = visible_schedules(db)
    schedules = db.scalars(
        statement.order_by(WorkflowSchedule.created_at.desc(), WorkflowSchedule.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [output(db, schedule) for schedule in schedules],
        "total": db.scalar(statement.with_only_columns(func.count(WorkflowSchedule.id))),
    }


@router.post("", response_model=ScheduleResponse, status_code=201)
def create_schedule(payload: ScheduleInput, db: Database):
    actor = db.info["principal"].user_id
    ids = {str(item) for item in payload.asset_ids}
    validate_targets(db, ids, actor)
    schedule = WorkflowSchedule(
        requested_by=actor,
        name=payload.name,
        local_time=payload.local_time,
        weekday=payload.weekday,
        next_run_at=next_occurrence(payload.local_time, payload.weekday, utcnow()),
    )
    db.add(schedule)
    db.flush()
    replace_targets(db, schedule, ids, set())
    audit(db, "workflow_schedule.created", target_id=schedule.id, details={"asset_count": len(ids)})
    db.commit()
    return output(db, schedule)


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(schedule_id: UUID, db: Database):
    return output(db, find_schedule(db, schedule_id))


@router.put("/{schedule_id}", response_model=ScheduleResponse)
def edit_schedule(schedule_id: UUID, payload: ScheduleInput, db: Database):
    schedule = find_schedule(db, schedule_id, lock=True)
    ids = {str(item) for item in payload.asset_ids}
    validate_targets(db, ids, schedule.requested_by)
    values = {"name": payload.name, "local_time": payload.local_time, "weekday": payload.weekday}
    if schedule.next_run_at and (schedule.local_time, schedule.weekday) != (
        payload.local_time,
        payload.weekday,
    ):
        values["next_run_at"] = next_occurrence(payload.local_time, payload.weekday, utcnow())
    write_schedule(db, schedule, **values)
    replace_targets(db, schedule, ids, target_ids(db, schedule.id))
    audit(db, "workflow_schedule.updated", target_id=schedule.id, details={"asset_count": len(ids)})
    db.commit()
    return output(db, schedule)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
def set_schedule_enabled(schedule_id: UUID, payload: ScheduleEnabled, db: Database):
    schedule = find_schedule(db, schedule_id, lock=True)
    if payload.enabled != (schedule.next_run_at is not None):
        next_at = None
        if payload.enabled:
            validate_targets(db, target_ids(db, schedule.id), schedule.requested_by)
            next_at = next_occurrence(schedule.local_time, schedule.weekday, utcnow())
        write_schedule(db, schedule, next_run_at=next_at)
        audit(
            db,
            "workflow_schedule.resumed" if payload.enabled else "workflow_schedule.paused",
            target_id=schedule.id,
        )
        db.commit()
    return output(db, schedule)


def visible_runs(schedule_id):
    return (
        select(WorkflowScheduleRun, WorkflowBatch.status, WorkflowBatch.finished_at)
        .outerjoin(WorkflowBatch, WorkflowBatch.id == WorkflowScheduleRun.batch_id)
        .where(
            WorkflowScheduleRun.schedule_id == schedule_id,
            or_(WorkflowScheduleRun.batch_id.is_(None), WorkflowBatch.id.is_not(None)),
        )
    )


@router.get("/{schedule_id}/runs", response_model=ScheduleRunList)
def list_schedule_runs(
    schedule_id: UUID,
    db: Database,
    limit: int = Query(8, ge=1, le=20),
    offset: int = Query(0, ge=0),
):
    schedule = find_schedule(db, schedule_id)
    statement = visible_runs(schedule.id)
    rows = db.execute(
        statement.order_by(WorkflowScheduleRun.scheduled_for.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "items": [
            {
                "id": run.id,
                "scheduled_for": run.scheduled_for,
                "created_at": run.created_at,
                "finished_at": finished_at if run.batch_id else run.created_at,
                "batch_id": run.batch_id,
                "status": status or "SKIPPED",
                "error": run.error,
            }
            for run, status, finished_at in rows
        ],
        "total": db.scalar(
            select(func.count()).select_from(
                statement.with_only_columns(
                    WorkflowScheduleRun.id, maintain_column_froms=True
                ).subquery()
            )
        ),
    }


@router.get("/{schedule_id}/runs/{run_id}/changes", response_model=ScheduleChanges)
def schedule_changes(
    schedule_id: UUID,
    run_id: UUID,
    db: Database,
    kind: ChangeKind | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    schedule = find_schedule(db, schedule_id)
    row = db.execute(
        visible_runs(schedule.id).where(WorkflowScheduleRun.id == str(run_id))
    ).one_or_none()
    if row is None:
        raise AppError("SCHEDULE_RUN_NOT_FOUND", "예약 실행 기록을 찾을 수 없습니다.", 404)
    run, status, _ = row
    if run.batch_id is None or status == "RUNNING":
        raise AppError("SCHEDULE_RUN_UNAVAILABLE", "비교할 완료된 예약 분석이 없습니다.", 409)
    return compare_schedule_run(db, run, kind, limit, offset)
