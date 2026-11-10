"""Server-side access restrictions shared by all scoped ORM reads and writes."""

from dataclasses import dataclass

from sqlalchemy import and_, event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from backend.core.errors import AppError
from backend.models.tables import (
    AnalysisRun,
    Asset,
    AssetGrant,
    AuditEvent,
    CollectionRun,
    ComparisonRun,
    ExplanationRun,
    FindingRecord,
    InventoryRecord,
    Job,
    QuestionAsset,
    QuestionRun,
    ReportRun,
    SSHProfile,
    User,
    VerificationRun,
)


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    username: str
    display_name: str
    role: str
    asset_ids: tuple[str, ...] = ()

    @property
    def admin(self):
        return self.role == "ADMIN"


def principal_for(db, user):
    grants = tuple(db.scalars(select(AssetGrant.asset_id).where(AssetGrant.user_id == user.id)))
    return Principal(user.id, user.username, user.display_name, user.role, grants)


def check_admin(db):
    principal = db.info.get("principal")
    if principal and not principal.admin:
        raise AppError("FORBIDDEN", "관리자 권한이 필요합니다.", 403)


@event.listens_for(Session, "do_orm_execute")
def scope_queries(execute):
    principal = execute.session.info.get("principal")
    if not principal or principal.admin or not execute.is_select:
        return
    assets, actor = principal.asset_ids, principal.user_id
    # Core table expressions keep the deny set independent of ORM visibility filters.
    denied_questions = select(QuestionAsset.__table__.c.question_id).where(
        QuestionAsset.__table__.c.asset_id.not_in(assets)
    )
    allowed_question_jobs = select(QuestionRun.__table__.c.job_id).where(
        QuestionRun.__table__.c.asset_id.in_(assets),
        QuestionRun.__table__.c.id.not_in(denied_questions),
    )
    statement = execute.statement.options(
        with_loader_criteria(Asset, Asset.id.in_(assets), include_aliases=True)
    )
    for model in (
        InventoryRecord,
        AnalysisRun,
        FindingRecord,
        ReportRun,
        SSHProfile,
        CollectionRun,
        ComparisonRun,
        VerificationRun,
    ):
        statement = statement.options(
            with_loader_criteria(model, model.asset_id.in_(assets), include_aliases=True)
        )
    statement = statement.options(
        with_loader_criteria(
            ExplanationRun,
            ExplanationRun.analysis_id.in_(
                select(AnalysisRun.id).where(AnalysisRun.asset_id.in_(assets))
            ),
            include_aliases=True,
        )
    )
    statement = statement.options(
        with_loader_criteria(
            QuestionRun,
            and_(QuestionRun.asset_id.in_(assets), QuestionRun.id.not_in(denied_questions)),
            include_aliases=True,
        ),
        with_loader_criteria(
            Job,
            and_(
                or_(
                    Job.asset_id.in_(assets),
                    and_(Job.asset_id.is_(None), Job.requested_by == actor),
                ),
                or_(Job.kind != "QUESTION", Job.id.in_(allowed_question_jobs)),
            ),
            include_aliases=True,
        ),
    )
    statement = statement.options(
        with_loader_criteria(AuditEvent, AuditEvent.asset_id.in_(assets), include_aliases=True)
    )
    execute.statement = statement


@event.listens_for(Session, "before_flush")
def scope_writes(db, _context, _instances):
    principal = db.info.get("principal")
    if not principal:
        return
    for item in db.new:
        if isinstance(item, Job):
            item.requested_by = principal.user_id
    if principal.admin:
        return
    for item in set(db.new) | set(db.dirty) | set(db.deleted):
        if isinstance(item, AuditEvent):
            continue
        if principal.role == "VIEWER":
            raise AppError("FORBIDDEN", "조회 권한으로 데이터를 변경할 수 없습니다.", 403)
        if isinstance(item, (User, AssetGrant)):
            raise AppError("FORBIDDEN", "관리자 권한이 필요합니다.", 403)
        asset_id = item.id if isinstance(item, Asset) else getattr(item, "asset_id", None)
        if asset_id and asset_id not in principal.asset_ids:
            raise AppError("FORBIDDEN", "허용된 자산만 변경할 수 있습니다.", 403)


@event.listens_for(Session, "after_flush")
def audit_new_jobs(db, _context):
    principal = db.info.get("principal")
    if not principal:
        return
    for job in list(db.new):
        if isinstance(job, Job):
            db.add(
                AuditEvent(
                    actor_id=principal.user_id,
                    asset_id=job.asset_id,
                    action="job.queued",
                    target_id=job.id,
                    request_id=db.info.get("request_id"),
                    details={"kind": job.kind},
                )
            )


def authorize_job(db, job):
    if not job.requested_by:
        return
    user = db.get(User, job.requested_by)
    if not user or not user.is_active or user.role == "VIEWER":
        raise AppError(
            "JOB_ACCESS_REVOKED", "요청자의 실행 권한이 변경되어 작업을 중단했습니다.", 403
        )
    if user.role != "ADMIN":
        if job.asset_id is None and job.kind != "SYSTEM_CHECK":
            raise AppError("JOB_ACCESS_REVOKED", "관리자 권한이 필요한 작업입니다.", 403)
        if job.asset_id and not db.get(AssetGrant, (user.id, job.asset_id)):
            raise AppError("JOB_ACCESS_REVOKED", "자산 권한이 변경되어 작업을 중단했습니다.", 403)
