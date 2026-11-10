import hashlib
import secrets
from datetime import UTC
from urllib.parse import urlsplit

from backend.auth.access import Principal, principal_for
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.models.tables import LoginSession, User, utcnow

COOKIE = "cti_session"


def token_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def csrf_token(value):
    return token_hash("csrf:" + value)


def same_origin(request):
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.netloc.lower() != request.headers.get("host", "").lower()
        ):
            raise AppError("CSRF_REJECTED", "같은 서비스 화면에서 요청하세요.", 403)


def authenticate(request, db, credentials=None):
    settings = get_settings()
    db.info["request_id"] = getattr(request.state, "request_id", None)
    if settings.auth_mode == "token":
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), settings.dev_api_token.get_secret_value().encode()
        ):
            raise AppError("UNAUTHORIZED", "개발용 API 토큰을 확인하세요.", 401)
        principal = Principal(None, "development", "개발 관리자", "ADMIN")
    else:
        raw = request.cookies.get(COOKIE, "")
        if not 40 <= len(raw) <= 100:
            raise AppError("UNAUTHORIZED", "로그인이 필요합니다.", 401)
        session = db.get(LoginSession, token_hash(raw))
        if not session:
            raise AppError("UNAUTHORIZED", "로그인이 필요합니다.", 401)
        expires = (
            session.expires_at.replace(tzinfo=UTC)
            if session.expires_at.tzinfo is None
            else session.expires_at
        )
        user = db.get(User, session.user_id)
        if expires <= utcnow() or not user or not user.is_active:
            raise AppError("UNAUTHORIZED", "세션이 만료되었거나 계정이 비활성 상태입니다.", 401)
        principal = principal_for(db, user)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            same_origin(request)
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
                raise AppError("CSRF_REJECTED", "페이지를 새로고침하고 다시 요청하세요.", 403)
    db.info["principal"] = principal
    request.state.principal = principal
    path = request.url.path
    write = request.method not in {"GET", "HEAD", "OPTIONS"}
    if (
        principal.role == "VIEWER"
        and write
        and path not in {"/api/v1/auth/logout", "/api/v1/auth/password"}
    ):
        raise AppError("FORBIDDEN", "조회 권한으로 작업을 요청할 수 없습니다.", 403)
    if not principal.admin and (
        path.startswith(("/api/v1/admin/", "/api/v1/audit"))
        or path == "/api/v1/collections/settings"
        or (path.startswith("/api/v1/sources/") and write)
        or (path == "/api/v1/assets" and write)
    ):
        raise AppError("FORBIDDEN", "관리자 권한이 필요합니다.", 403)
    return principal
