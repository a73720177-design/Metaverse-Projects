from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.storage.object_storage import ObjectStorageError
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "데이터베이스를 일시적으로 사용할 수 없습니다.",
                }
            },
        )

    @app.exception_handler(ObjectStorageError)
    async def object_storage_error_handler(
        request: Request, exc: ObjectStorageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "object_storage_unavailable",
                    "message": "파일 저장소를 일시적으로 사용할 수 없습니다.",
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": str(exc.detail),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                }
            },
        )
