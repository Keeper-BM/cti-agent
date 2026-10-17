"""공식 보안 자료 상태·갱신 경로. 실제 자료 처리는 미구현."""

from fastapi import APIRouter

from backend.core.errors import AppError

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/status", status_code=501)
def get_source_status():
    raise AppError("FEATURE_NOT_IMPLEMENTED", "공식 자료 수집이 아직 연결되지 않았습니다.", 501)


@router.post("/{source_id}/sync", status_code=501)
def sync_source(source_id: str):
    raise AppError("FEATURE_NOT_IMPLEMENTED", "공식 자료 갱신이 아직 연결되지 않았습니다.", 501)
