"""Self-contained, frozen report data shared by preview and Markdown output."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.api.schemas.sources import DocumentInfo, SnapshotResponse
from backend.assessment.contracts import AssessmentFinding
from backend.llm.contracts import ExplanationResult
from backend.models.contracts import OperatingSystem
from backend.models.enums import CollectionStatus, OriginStatus
from backend.verification.contracts import VerificationEvidence

TEMPLATE_VERSION = "assessment-report/1.2"
MAX_REPORT_BYTES = 16 * 1024 * 1024

VERDICT_LABELS = {
    "AFFECTED": "영향 있음",
    "FIXED": "해당 CVE의 수정 기준 충족",
    "NOT_AFFECTED": "공식 조건상 영향 없음",
    "NEEDS_REVIEW": "추가 확인 필요",
}
PROCESSING_LABELS = {
    "EVALUATED": "평가됨",
    "OUT_OF_SCOPE": "지원 범위 밖",
    "NOT_INSTALLED": "입력 목록에 없음",
    "NO_MATCHING_RECORD": "대조 자료 없음",
    "COLLECTION_FAILED": "수집 실패",
    "PARTIAL_COLLECTION": "설치 여부 미확인",
}
COMPARISON_LABELS = {
    "BELOW_FIX": "수정 기준보다 낮음",
    "MEETS_FIX": "수정 기준 이상",
    "UNAVAILABLE": "비교 불가",
}
KEV_LABELS = {
    "LISTED": "악용 목록 등재",
    "NOT_LISTED": "저장 목록에 미등재",
    "NOT_FETCHED": "악용 자료 미수집",
}
ORIGIN_LABELS = {
    "OFFICIAL_MATCH": "공식 배포본 파일 일치",
    "USER_DECLARED": "사용자 입력 · 미검증",
    "UNKNOWN": "미확인",
    "UNSUPPORTED": "지원하지 않는 출처",
    "SUPPORTED_ORIGIN": "출처 확인됨",
    "VERIFIED_LAB": "시험 환경에서 확인됨",
}


class ReportPackage(BaseModel):
    package_id: UUID
    binary_name: str
    binary_version: str | None
    source_name: str | None
    source_version: str | None
    architecture: str | None
    origin_status: OriginStatus
    install_status: str


class ReportSummary(BaseModel):
    package_count: int
    finding_count: int
    cve_count: int
    kev_listed_cve_count: int
    verdict_counts: dict[str, int]
    processing_counts: dict[str, int]
    comparison_counts: dict[str, int]


class ReportExplanation(BaseModel):
    id: UUID
    finding_id: UUID
    model: str
    reported_model: str | None
    prompt_version: str
    context_sha256: str
    completed_at: AwareDatetime
    result: ExplanationResult


class ReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    report_id: UUID
    template_version: str
    frozen_at: AwareDatetime
    generated_at: AwareDatetime | None = None
    analysis_id: UUID
    inventory_id: UUID
    asset_id: UUID
    asset_name: str
    expected_release: str | None
    os: OperatingSystem
    collected_at: AwareDatetime
    ingested_at: AwareDatetime
    analysis_created_at: AwareDatetime
    analysis_completed_at: AwareDatetime
    ruleset_version: str
    feed_snapshot_id: UUID
    is_synthetic: bool
    collection_status: CollectionStatus
    package_list_complete: bool
    include_ai_explanations: bool
    summary: ReportSummary
    warnings: list[str]
    packages: list[ReportPackage]
    findings: list[AssessmentFinding]
    sources: list[SnapshotResponse]
    documents: list[DocumentInfo]
    explanations: list[ReportExplanation]
    verification: VerificationEvidence | None = None
