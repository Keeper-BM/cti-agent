import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from backend.api.dependencies import Database, require_token
from backend.api.routes import assets, examples, findings, jobs, questions, reports, sources
from backend.api.schemas.common import CapabilitiesResponse, ErrorResponse, FeatureFlags
from backend.core.config import get_settings
from backend.core.diagnostics import safe_exception_details
from backend.core.errors import AppError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings()  # Fail closed if the development token is missing.
    yield


def error_response(request: Request, error: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": getattr(request.state, "request_id", str(uuid4())),
                "retryable": error.retryable,
            }
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="BlendedMeshup · Threat Intelligence API",
        version="0.1.0",
        description="Ubuntu asset and vulnerability intelligence API. Development version.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "Unhandled request error; request_id=%s; %s",
                request.state.request_id,
                safe_exception_details(exc),
            )
            response = error_response(
                request, AppError("INTERNAL_ERROR", "요청 처리 중 오류가 발생했습니다.", 500)
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors())
        return error_response(
            request, AppError("VALIDATION_ERROR", f"입력값을 확인하세요: {fields}", 422)
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return error_response(
            request, AppError("HTTP_ERROR", "요청 경로를 확인하세요.", exc.status_code)
        )

    @app.get("/api/v1/health", tags=["system"])
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/readiness", tags=["system"])
    def readiness(db: Database):
        try:
            # Also verify that migrations ran; SELECT 1 alone is insufficient.
            db.execute(text("SELECT version_num FROM alembic_version"))
            db.execute(text("SELECT id FROM assets LIMIT 1"))
            db.execute(text("SELECT id FROM jobs LIMIT 1"))
        except SQLAlchemyError:
            raise AppError(
                "DATABASE_NOT_READY", "DB 연결과 마이그레이션을 확인하세요.", 503, True
            ) from None
        return {"status": "ready"}

    protected = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(require_token)],
        responses={code: {"model": ErrorResponse} for code in [401, 404, 409, 422, 500, 501]},
    )
    protected.include_router(assets.router)
    protected.include_router(jobs.router)
    protected.include_router(findings.router)
    protected.include_router(questions.router)
    protected.include_router(reports.router)
    protected.include_router(sources.router)
    protected.include_router(examples.router)

    @protected.get("/capabilities", response_model=CapabilitiesResponse, tags=["system"])
    def capabilities():
        return CapabilitiesResponse(features=FeatureFlags())

    app.include_router(protected)
    return app


app = create_app()
