from secrets import compare_digest
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.database import get_session
from backend.core.errors import AppError

bearer = HTTPBearer(auto_error=False)
Database = Annotated[Session, Depends(get_session)]


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = get_settings().dev_api_token.get_secret_value()
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise AppError("UNAUTHORIZED", "개발용 API 토큰을 확인하세요.", 401)
