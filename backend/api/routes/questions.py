"""자산 범위를 지정하는 질의응답 경로. 실제 설명 생성은 미구현."""

from fastapi import APIRouter

from backend.api.schemas.questions import QuestionRequest
from backend.core.errors import AppError

router = APIRouter(prefix="/questions", tags=["questions"])


@router.post("", status_code=501)
def create_question(payload: QuestionRequest):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "근거 기반 질의응답이 아직 연결되지 않았습니다.", 501)
