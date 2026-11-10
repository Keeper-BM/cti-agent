from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.auth.session import authenticate
from backend.core.database import get_session

bearer = HTTPBearer(auto_error=False)
Database = Annotated[Session, Depends(get_session)]


def require_token(
    request: Request,
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    return authenticate(request, db, credentials)
