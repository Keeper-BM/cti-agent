from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from backend.api.schemas.common import TimestampResponse


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=256)


class UserCreate(LoginInput):
    password: SecretStr = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["ADMIN", "OPERATOR", "VIEWER"] = "VIEWER"

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("표시 이름을 확인하세요.")
        return value


class UserResponse(TimestampResponse):
    id: UUID
    username: str
    display_name: str
    role: Literal["ADMIN", "OPERATOR", "VIEWER"]
    is_active: bool
    created_at: datetime


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["ADMIN", "OPERATOR", "VIEWER"] | None = None
    is_active: StrictBool | None = None


class UserList(BaseModel):
    items: list[UserResponse]
    total: int


class SessionResponse(BaseModel):
    user: UserResponse
    csrf_token: str


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class GrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID


class GrantList(BaseModel):
    users: list[UserResponse]


class AuditResponse(TimestampResponse):
    id: UUID
    actor_id: UUID | None
    asset_id: UUID | None
    action: str
    target_id: str | None
    outcome: str
    request_id: str | None
    details: dict
    created_at: datetime


class AuditList(BaseModel):
    items: list[AuditResponse]
    total: int
