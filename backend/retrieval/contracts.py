from typing import Literal

from pydantic import BaseModel, Field

from backend.llm.contracts import Citation, CitedText, StrictModel

PROMPT_VERSION = "scoped-question/1.1"


class QuestionFact(BaseModel):
    asset_ref: str
    analysis_id: str
    finding_id: str
    package_name: str | None
    cve_id: str | None
    installed_version: str | None
    fixed_version: str | None
    verdict: str | None
    version_comparison: str
    origin_status: str | None
    reasons: list[str]


class QuestionContext(BaseModel):
    question: str
    analysis_ids: list[str]
    asset_ids: list[str]
    summaries: list[dict]
    facts: list[QuestionFact]
    citations: list[Citation]
    retrieval_version: str
    facts_digest: str
    warnings: list[str]
    insufficient_evidence: bool


class GeneratedAnswer(StrictModel):
    facts_digest: str
    insufficient_evidence: bool
    answer: list[CitedText] = Field(min_length=1, max_length=6)


class QuestionResult(BaseModel):
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE"]
    answer: list[CitedText]
    facts: list[QuestionFact]
    summaries: list[dict]
    citations: list[Citation]
    retrieval_version: str
    warnings: list[str]
