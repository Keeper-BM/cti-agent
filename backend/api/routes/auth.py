import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from backend.api.dependencies import Database, require_token
from backend.api.routes.assets import find_asset
from backend.api.schemas.auth import (
    AuditList,
    GrantInput,
    GrantList,
    LoginInput,
    PasswordChange,
    SessionResponse,
    UserCreate,
    UserList,
    UserPatch,
    UserResponse,
)
from backend.auth.access import check_admin
from backend.auth.passwords import hash_password, verify_password
from backend.auth.session import COOKIE, csrf_token, same_origin, token_hash
from backend.core.audit import audit
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import AssetGrant, AuditEvent, LoginSession, LoginThrottle, User, utcnow

public = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
router = APIRouter(tags=["accounts"])
DUMMY_HASH = hash_password("not-a-real-account-password")


def account_mode():
    if get_settings().auth_mode != "accounts":
        raise AppError("ACCOUNTS_DISABLED", "현재 개발용 토큰 연결 모드입니다.", 409)


def throttle(db, key, maximum):
    now = utcnow()
    identity = token_hash(key)
    db.execute(delete(LoginThrottle).where(LoginThrottle.window_start < now - timedelta(hours=24)))
    row = db.get(LoginThrottle, identity)
    if row is None:
        try:
            db.add(LoginThrottle(id=identity, count=0, window_start=now))
            db.commit()
        except IntegrityError:
            db.rollback()
    db.execute(
        update(LoginThrottle)
        .where(
            LoginThrottle.id == identity, LoginThrottle.window_start < now - timedelta(minutes=5)
        )
        .values(count=0, window_start=now)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(LoginThrottle)
        .where(LoginThrottle.id == identity)
        .values(count=LoginThrottle.count + 1)
    )
    db.commit()
    db.expire_all()
    if db.get(LoginThrottle, identity).count > maximum:
        audit(db, "login.rate_limited", outcome="DENIED")
        db.commit()
        raise AppError("LOGIN_RATE_LIMIT", "로그인 시도가 많습니다. 5분 후 다시 시도하세요.", 429)


@public.get("/status")
def status():
    return {"mode": get_settings().auth_mode}


@public.post("/login", response_model=SessionResponse)
def login(payload: LoginInput, request: Request, response: Response, db: Database):
    account_mode()
    same_origin(request)
    db.info["request_id"] = getattr(request.state, "request_id", None)
    throttle(db, "ip:" + (request.client.host if request.client else "unknown"), 30)
    throttle(db, "user:" + payload.username, 10)
    user = db.scalar(select(User).where(User.username == payload.username))
    valid = verify_password(
        payload.password.get_secret_value(), user.password_hash if user else DUMMY_HASH
    )
    if not user or not user.is_active or not valid:
        audit(db, "login.failed", outcome="DENIED")
        db.commit()
        raise AppError("LOGIN_FAILED", "계정 또는 비밀번호를 확인하세요.", 401)
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    expires = now + timedelta(hours=get_settings().session_hours)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    # Cap concurrent sessions per account without keeping old session credentials.
    sessions = list(
        db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.created_at.desc())
        )
    )
    for old in sessions[4:]:
        db.delete(old)
    db.add(LoginSession(id=token_hash(raw), user_id=user.id, created_at=now, expires_at=expires))
    audit(db, "login.succeeded", actor_id=user.id)
    db.commit()
    response.set_cookie(
        COOKIE,
        raw,
        max_age=get_settings().session_hours * 3600,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="strict",
        path="/api",
    )
    return {"user": user, "csrf_token": csrf_token(raw)}


@public.get("/me", response_model=SessionResponse, dependencies=[Depends(require_token)])
def me(request: Request, db: Database):
    account_mode()
    user = db.get(User, db.info["principal"].user_id)
    return {"user": user, "csrf_token": csrf_token(request.cookies[COOKIE])}


@public.post("/logout", dependencies=[Depends(require_token)])
def logout(request: Request, response: Response, db: Database):
    account_mode()
    actor = db.info["principal"].user_id
    db.execute(
        delete(LoginSession).where(LoginSession.id == token_hash(request.cookies.get(COOKIE, "")))
    )
    audit(db, "logout", actor_id=actor)
    db.commit()
    response.delete_cookie(
        COOKIE,
        path="/api",
        httponly=True,
        samesite="strict",
        secure=get_settings().session_cookie_secure,
    )
    return {"logged_out": True}


@public.post("/password", dependencies=[Depends(require_token)])
def password(payload: PasswordChange, request: Request, response: Response, db: Database):
    account_mode()
    principal = db.info["principal"]
    user = db.get(User, principal.user_id)
    if not verify_password(payload.current_password.get_secret_value(), user.password_hash):
        raise AppError("PASSWORD_INVALID", "현재 비밀번호를 확인하세요.", 400)
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(password_hash=hash_password(payload.new_password.get_secret_value()))
    )
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, "password.changed", actor_id=user.id)
    db.commit()
    response.delete_cookie(COOKIE, path="/api")
    return {"login_required": True}


@router.get("/admin/users", response_model=UserList)
def list_users(db: Database, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    check_admin(db)
    return {
        "items": list(
            db.scalars(select(User).order_by(User.created_at, User.id).limit(limit).offset(offset))
        ),
        "total": db.scalar(select(func.count()).select_from(User)),
    }


@router.post("/admin/users", response_model=UserResponse, status_code=201)
def create_user(payload: UserCreate, db: Database):
    check_admin(db)
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        role=payload.role,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    try:
        db.add(user)
        db.flush()
        audit(db, "user.created", target_id=user.id, details={"role": user.role})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("USER_EXISTS", "같은 로그인 이름의 계정이 있습니다.", 409) from None
    return user


@router.patch("/admin/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, payload: UserPatch, db: Database):
    check_admin(db)
    # A short write lock serializes administrator demotion/deactivation across sessions.
    db.execute(update(User).where(User.role == "ADMIN").values(role=User.role))
    admins = list(
        db.scalars(
            select(User).where(User.role == "ADMIN", User.is_active.is_(True)).with_for_update()
        )
    )
    user = db.get(User, str(user_id))
    if not user:
        raise AppError("USER_NOT_FOUND", "계정을 찾을 수 없습니다.", 404)
    if not payload.model_fields_set or any(
        getattr(payload, k) is None for k in payload.model_fields_set
    ):
        raise AppError("INVALID_USER_CHANGE", "변경할 역할 또는 활성 상태를 입력하세요.", 422)
    if (
        user.role == "ADMIN"
        and user.is_active
        and len(admins) <= 1
        and (payload.role not in {None, "ADMIN"} or payload.is_active is False)
    ):
        raise AppError(
            "LAST_ADMIN", "마지막 활성 관리자를 비활성화하거나 권한을 낮출 수 없습니다.", 409
        )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, "user.updated", target_id=user.id, details=payload.model_dump(exclude_unset=True))
    db.commit()
    return user


@router.get("/admin/assets/{asset_id}/grants", response_model=GrantList)
def grants(asset_id: UUID, db: Database):
    check_admin(db)
    find_asset(asset_id, db)
    return {
        "users": list(
            db.scalars(
                select(User)
                .join(AssetGrant, User.id == AssetGrant.user_id)
                .where(AssetGrant.asset_id == str(asset_id))
                .order_by(User.username)
            )
        )
    }


@router.post("/admin/assets/{asset_id}/grants")
def add_grant(asset_id: UUID, payload: GrantInput, db: Database):
    check_admin(db)
    find_asset(asset_id, db)
    if not db.get(User, str(payload.user_id)):
        raise AppError("USER_NOT_FOUND", "계정을 찾을 수 없습니다.", 404)
    if not db.get(AssetGrant, (str(payload.user_id), str(asset_id))):
        db.add(AssetGrant(user_id=str(payload.user_id), asset_id=str(asset_id)))
        audit(db, "asset.access_granted", asset_id=asset_id, target_id=payload.user_id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"granted": True}


@router.delete("/admin/assets/{asset_id}/grants/{user_id}")
def revoke_grant(asset_id: UUID, user_id: UUID, db: Database):
    check_admin(db)
    find_asset(asset_id, db)
    db.execute(
        delete(AssetGrant).where(
            AssetGrant.user_id == str(user_id), AssetGrant.asset_id == str(asset_id)
        )
    )
    audit(db, "asset.access_revoked", asset_id=asset_id, target_id=user_id)
    db.commit()
    return {"revoked": True}


@router.get("/audit", response_model=AuditList)
def events(
    db: Database,
    asset_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    check_admin(db)
    filters = [] if asset_id is None else [AuditEvent.asset_id == str(asset_id)]
    return {
        "items": list(
            db.scalars(
                select(AuditEvent)
                .where(*filters)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ),
        "total": db.scalar(select(func.count()).select_from(AuditEvent).where(*filters)),
    }
