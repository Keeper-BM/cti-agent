import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.models.contracts import Contract
from backend.retrieval.contracts import QuestionResult


class QuestionRequest(Contract):
    analysis_ids: list[UUID] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=5, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        if isinstance(value, str) and re.search(
            r"dcu_llm_|-----BEGIN.*PRIVATE KEY|Bearer\s+[A-Za-z0-9]", value, re.I
        ):
            raise ValueError("질문에 API 키나 인증 정보를 입력하지 마세요.")
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.analysis_ids)) != len(self.analysis_ids):
            raise ValueError("같은 분석을 중복 선택하지 마세요.")
        return self


class QuestionResponse(TimestampResponse):
    id: UUID
    asset_id: UUID
    question: str
    analysis_ids: list[str]
    model: str
    prompt_version: str
    job: JobResponse
    created_at: datetime
    completed_at: datetime | None


class QuestionDetail(QuestionResponse):
    result: QuestionResult | None
    usage: dict[str, int] | None


class QuestionList(BaseModel):
    items: list[QuestionResponse]
    total: int
