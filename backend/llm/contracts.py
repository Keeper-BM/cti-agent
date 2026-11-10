"""Small, bounded explanation contract, independent of the assessment verdict."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PROMPT_VERSION = "cve-explanation/1.0"
SCHOOL_BASE_URL = "https://code.cu.ac.kr/llm/v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Facts(StrictModel):
    cve_id: str
    package_name: str
    source_package: str | None
    os_release: str | None
    installed_version: str | None
    binary_version: str | None
    fixed_version: str | None
    verdict: str
    version_comparison: str
    origin_status: str | None
    kev_status: str
    is_synthetic: bool


class CitedText(StrictModel):
    text: str = Field(min_length=10, max_length=1400)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class GeneratedExplanation(StrictModel):
    facts: Facts
    meaning: CitedText
    next_steps: list[CitedText] = Field(min_length=1, max_length=5)


class Citation(BaseModel):
    id: str
    source_id: str
    title: str
    document_id: UUID | None
    record_id: UUID | None
    snapshot_id: UUID | None
    captured_at: datetime
    sha256: str | None
    url: str | None
    excerpt: str
    truncated: bool = False
    chunk_id: UUID | None = None
    chunk_start: int | None = None
    chunk_end: int | None = None


class ExplanationContext(BaseModel):
    facts: Facts
    reasons: list[str]
    limitations: list[str]
    citations: list[Citation]
    selection_notes: list[str]


class ExplanationResult(BaseModel):
    facts: Facts
    meaning: CitedText
    assessment_text: str
    assessment_reasons: list[str]
    next_steps: list[CitedText]
    citations: list[Citation]
    warnings: list[str]
    validation: Literal["STRUCTURE_FACTS_CITATIONS_CHECKED"] = "STRUCTURE_FACTS_CITATIONS_CHECKED"


class ProviderReply(BaseModel):
    content: str
    model: str | None
    usage: dict[str, int]
