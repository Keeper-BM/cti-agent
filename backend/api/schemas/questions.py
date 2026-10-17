"""자산 범위를 제한하는 질의 요청 규격."""

from uuid import UUID

from pydantic import Field, field_validator

from backend.models.contracts import Contract


class QuestionRequest(Contract):
    requested_asset_ids: list[UUID] = Field(min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
