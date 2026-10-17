"""분석 요청과 판정 조회 경로. 실제 판정 기능은 미구현."""

from uuid import UUID

from fastapi import APIRouter, Query

from backend.api.schemas.findings import AnalysisRequest, FindingList
from backend.core.errors import AppError
from backend.models.contracts import Finding
from backend.models.enums import Verdict

router = APIRouter(tags=["assessment"])


@router.post("/analyses", status_code=501)
def create_analysis(payload: AnalysisRequest):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "영향 판정 모듈이 아직 연결되지 않았습니다.", 501)


@router.get("/findings", response_model=FindingList)
def list_findings(
    asset_id: UUID | None = None,
    verdict: Verdict | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "판정 결과 조회가 아직 연결되지 않았습니다.", 501)


@router.get("/findings/{finding_id}", response_model=Finding)
def get_finding(finding_id: UUID):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "판정 근거 조회가 아직 연결되지 않았습니다.", 501)
