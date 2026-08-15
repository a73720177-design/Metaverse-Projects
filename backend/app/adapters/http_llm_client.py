import os
from typing import Any

import httpx


class LlmServiceConnectionError(RuntimeError):
    pass


class LlmServiceResponseError(RuntimeError):
    pass


class HttpLlmClient:
    """LLM 팀의 독립 FastAPI 서비스와 통신하는 HTTP 클라이언트입니다."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = os.getenv("LLM_SERVICE_URL", "http://localhost:8001").rstrip("/")
        self.api_prefix = os.getenv("LLM_API_PREFIX", "/api/v1").rstrip("/")
        self.timeout = float(os.getenv("LLM_SERVICE_TIMEOUT", "300"))
        self.transport = transport

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, payload)

    async def get_json(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

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
                f"LLM service is unavailable: {self.base_url}"
            ) from exc

        if response.status_code >= 400:
            raise LlmServiceResponseError(
                f"LLM service returned HTTP {response.status_code} for {path}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LlmServiceResponseError("LLM service returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise LlmServiceResponseError("LLM service response must be a JSON object")
        return body
