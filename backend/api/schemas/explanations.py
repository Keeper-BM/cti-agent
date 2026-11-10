from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.llm.contracts import ExplanationResult
from backend.models.contracts import Contract


class ExplanationRequest(Contract):
    finding_id: UUID


class ExplanationResponse(TimestampResponse):
    id: UUID
    finding_id: UUID
    analysis_id: UUID
    job: JobResponse
    provider: str
    model: str
    reported_model: str | None
    prompt_version: str
    context_sha256: str
    result: ExplanationResult | None
    usage: dict[str, int] | None
    created_at: datetime
    completed_at: datetime | None


class ExplanationList(BaseModel):
    items: list[ExplanationResponse]
    total: int


class LLMStatus(BaseModel):
    configured: bool
    provider: str = "학교 LLM API"
    model: str | None
    message: str
