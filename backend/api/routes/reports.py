"""보고서 생성·조회·출력 경로. 실제 보고서 처리는 미구현."""

from uuid import UUID

from fastapi import APIRouter

from backend.api.schemas.reports import ReportRequest
from backend.core.errors import AppError

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", status_code=501)
def create_report(payload: ReportRequest):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "보고서 생성이 아직 연결되지 않았습니다.", 501)


@router.get("/{report_id}", status_code=501)
def get_report(report_id: UUID):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "보고서 조회가 아직 연결되지 않았습니다.", 501)


@router.get("/{report_id}/markdown", status_code=501)
def download_report(report_id: UUID):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "Markdown 출력이 아직 연결되지 않았습니다.", 501)
