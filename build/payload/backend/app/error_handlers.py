import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.storage.object_storage import ObjectStorageError

logger = logging.getLogger(__name__)


def validation_message(item: dict) -> str:
    kind = item.get("type", "")
    messages = {
        "missing": "필수 항목입니다.", "string_pattern_mismatch": "허용된 문자 형식에 맞게 입력해주세요.",
        "string_type": "문자열이어야 합니다.", "int_parsing": "정수를 입력해주세요.",
        "int_type": "정수여야 합니다.", "uuid_parsing": "유효한 식별자 형식이 아닙니다.",
        "uuid_type": "유효한 식별자가 필요합니다.", "enum": "선택 가능한 값 중 하나를 지정해주세요.",
        "literal_error": "선택 가능한 값 중 하나를 지정해주세요.", "json_invalid": "JSON 요청 형식이 올바르지 않습니다.",
        "value_error": "입력값을 확인해주세요.", "assertion_error": "입력값을 확인해주세요.",
    }
    limits = {
        "string_too_short": ("min_length", "{value}자 이상 입력해주세요."),
        "string_too_long": ("max_length", "{value}자 이하로 입력해주세요."),
        "greater_than_equal": ("ge", "{value} 이상의 값을 입력해주세요."),
        "less_than_equal": ("le", "{value} 이하의 값을 입력해주세요."),
    }
    if kind in limits:
        key, template = limits[kind]
        value = item.get("ctx", {}).get(key)
        if isinstance(value, (int, float)):
            return template.format(value=value)
    return messages.get(kind, item.get("msg", "입력값을 확인해주세요."))


def public_validation_fields(errors) -> list[dict]:
    """Locations and constraints only: Pydantic input/ctx may contain passwords."""
    return [
        {
            "loc": list(item.get("loc", ())),
            "type": item.get("type", "validation_error"),
            "message": validation_message(item),
        }
        for item in errors[:20]
    ]


def database_error_code(exc: SQLAlchemyError) -> str:
    current = exc
    for _ in range(5):
        state = getattr(current, "sqlstate", None)
        if state == "25006":
            return "database_read_only"
        if state in {"42P01", "42703"}:
            return "database_schema_mismatch"
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
        if current is None:
            break
    return "database_unavailable"


def error_response(request: Request, status: int, error: dict, headers=None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or uuid4().hex
    logger.warning("request_id=%s method=%s path=%s status=%s code=%s",
                   request_id, request.method, request.url.path, status, error["code"])
    return JSONResponse(
        status_code=status,
        headers={**(headers or {}), "X-Request-ID": request_id},
        content={"error": {**error, "request_id": request_id}},
    )


class RequestErrorMiddleware:
    """Return a JSON error even for unhandled exceptions, inside CORS middleware."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = False
        finished = False

        async def send_with_id(message):
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode())]}
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            logger.error("Unhandled request error request_id=%s type=%s", request_id, type(exc).__name__)
            if started:
                if not finished:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            response = error_response(Request(scope), 500, {
                "code": "internal_server_error",
                "message": "서버 내부 오류로 요청을 처리하지 못했습니다. 요청 ID로 서버 로그를 확인해주세요.",
                "error_type": type(exc).__name__,
            })
            await response(scope, receive, send_with_id)


def register_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestErrorMiddleware)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        code = database_error_code(exc)
        messages = {
            "database_read_only": "DB가 읽기 전용 상태여서 데이터를 저장할 수 없습니다.",
            "database_schema_mismatch": "현재 코드에 필요한 DB 테이블 또는 컬럼이 없습니다.",
            "database_unavailable": "데이터베이스를 일시적으로 사용할 수 없습니다.",
        }
        return error_response(request, 503, {"code": code, "message": messages[code]})

    @app.exception_handler(ObjectStorageError)
    async def object_storage_error_handler(request: Request, exc: ObjectStorageError) -> JSONResponse:
        return error_response(request, 503, {
            "code": "object_storage_unavailable", "message": "파일 저장소를 일시적으로 사용할 수 없습니다.",
        })

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        error = (
            {**detail, "code": detail.get("code", f"http_{exc.status_code}"),
             "message": detail.get("message", "요청을 처리하지 못했습니다.")}
            if isinstance(detail, dict)
            else {"code": f"http_{exc.status_code}", "message": str(detail)}
        )
        return error_response(request, exc.status_code, error, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, {
            "code": "validation_error", "message": "입력값이 올바르지 않습니다. 표시된 항목을 확인해주세요.",
            "fields": public_validation_fields(exc.errors()),
        })

    @app.exception_handler(ResponseValidationError)
    async def response_validation_error_handler(request: Request, exc: ResponseValidationError) -> JSONResponse:
        return error_response(request, 500, {
            "code": "response_validation_error", "message": "서버 응답 구조가 API 정의와 일치하지 않습니다.",
            "fields": public_validation_fields(exc.errors()),
        })
