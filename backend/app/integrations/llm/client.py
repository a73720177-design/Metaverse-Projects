import os
from typing import Any

import httpx


class LlmServiceConnectionError(RuntimeError):
    pass


class LlmServiceResponseError(RuntimeError):
    """LLM 서비스가 4xx/5xx를 반환했습니다.

    status_code와 body를 함께 들고 있어야 호출부가 409(document_not_indexed)
    처럼 복구 가능한 응답을 구분할 수 있습니다.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class HttpLlmClient:
    """LLM 팀의 독립 FastAPI 서비스와 통신하는 HTTP 클라이언트입니다."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        api_prefix: str | None = None,
    ) -> None:
        self.base_url = os.getenv("LLM_SERVICE_URL", "http://localhost:8001").rstrip("/")
        configured_prefix = (
            os.getenv("LLM_API_PREFIX", "/api/v1")
            if api_prefix is None
            else api_prefix
        )
        self.api_prefix = configured_prefix.rstrip("/")
        self.timeout = float(os.getenv("LLM_SERVICE_TIMEOUT", "300"))
        self.transport = transport

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, payload)

    async def get_json(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def delete(self, path: str) -> None:
        """본문 없는 204 응답을 쓰는 삭제 요청입니다."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.request(
                    "DELETE",
                    f"{self.base_url}{self.api_prefix}{path}",
                    headers={"X-Backend-Contract-Version": "1"},
                )
        except httpx.RequestError as exc:
            raise LlmServiceConnectionError(
                f"LLM 서비스를 사용할 수 없습니다: {self.base_url}"
            ) from exc

        if response.status_code >= 400:
            raise LlmServiceResponseError(
                f"LLM 서비스가 {path} 요청에 HTTP {response.status_code}를 반환했습니다.",
                status_code=response.status_code,
            )

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{self.api_prefix}{path}",
                    json=payload,
                    headers={"X-Backend-Contract-Version": "1"},
                )
        except httpx.RequestError as exc:
            raise LlmServiceConnectionError(
                f"LLM 서비스를 사용할 수 없습니다: {self.base_url}"
            ) from exc

        if response.status_code >= 400:
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            raise LlmServiceResponseError(
                f"LLM 서비스가 {path} 요청에 HTTP {response.status_code}를 반환했습니다.",
                status_code=response.status_code,
                body=error_body,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LlmServiceResponseError("LLM 서비스가 잘못된 JSON을 반환했습니다.") from exc
        if not isinstance(body, dict):
            raise LlmServiceResponseError("LLM 응답은 JSON 객체여야 합니다.")
        return body
