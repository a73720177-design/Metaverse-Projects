import os
import json
import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.integrations.llm.stream_sanitizer import ReasoningFilter

from app.integrations.llm.response_sanitizer import (
    clean_model_text,
    extract_json_object,
    sanitize_llm_payload,
)


class LlmServiceConnectionError(RuntimeError):
    pass


class LlmServiceResponseError(RuntimeError):
    pass


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

    async def stream_sse(
        self, path: str, payload: dict[str, Any]
    ) -> AsyncIterator[str]:
        reasoning = ReasoningFilter()
        emitted = False
        buffered_size = 0
        completed = False
        try:
            async with asyncio.timeout(self.timeout), httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}{self.api_prefix}{path}",
                    json=payload,
                    headers={"X-Backend-Contract-Version": "1"},
                ) as response:
                    if response.status_code >= 400:
                        raise LlmServiceResponseError(
                            f"LLM 서비스가 {path} 요청에 HTTP {response.status_code}를 반환했습니다."
                        )
                    event = "message"
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event = line.removeprefix("event:").strip()
                        elif line.startswith("data:"):
                            data_lines.append(line.removeprefix("data:").removeprefix(" "))
                        elif not line:
                            if data_lines:
                                data = json.loads("\n".join(data_lines))
                                if not isinstance(data, dict):
                                    raise LlmServiceResponseError("LLM 스트림 형식이 올바르지 않습니다.")
                                if event == "token":
                                    token = data.get("token")
                                    if not isinstance(token, str):
                                        raise LlmServiceResponseError("LLM 스트림 토큰 형식이 올바르지 않습니다.")
                                    buffered_size += len(token)
                                    if buffered_size > 200_000:
                                        raise LlmServiceResponseError("LLM 스트림 출력 한도를 초과했습니다.")
                                    visible = reasoning.feed(token)
                                    if visible:
                                        emitted = emitted or bool(visible.strip())
                                        yield visible
                                elif event == "error":
                                    raise LlmServiceResponseError("LLM 서비스 스트리밍 중 오류가 발생했습니다.")
                                elif event == "done":
                                    completed = True
                                    break
                            data_lines.clear()
                            event = "message"
            if not completed:
                raise LlmServiceResponseError("LLM 스트림이 완료 전에 끊겼습니다. 다시 시도해 주세요.")
            tail = reasoning.feed("", final=True)
            if tail:
                emitted = emitted or bool(tail.strip())
                yield tail
            if not emitted:
                raise LlmServiceResponseError("LLM이 유효한 최종 답변을 반환하지 않았습니다.")
        except LlmServiceResponseError:
            raise
        except ValueError as exc:
            raise LlmServiceResponseError("LLM 스트림 형식이 올바르지 않습니다.") from exc
        except (httpx.RequestError, TimeoutError) as exc:
            raise LlmServiceConnectionError(
                "LLM 서비스 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from exc

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout, 5) if method == "GET" else self.timeout,
                transport=self.transport
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{self.api_prefix}{path}",
                    json=payload,
                    headers={"X-Backend-Contract-Version": "1"},
                )
        except httpx.RequestError as exc:
            raise LlmServiceConnectionError(
                "LLM 서비스 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from exc

        if response.status_code >= 400:
            raise LlmServiceResponseError(
                f"LLM 서비스가 {path} 요청에 HTTP {response.status_code}를 반환했습니다."
            )
        try:
            body = response.json()
        except ValueError:
            try:
                body = extract_json_object(response.text)
            except json.JSONDecodeError as exc:
                raise LlmServiceResponseError(
                    "LLM 서비스가 잘못된 JSON을 반환했습니다."
                ) from exc
        if not isinstance(body, dict):
            raise LlmServiceResponseError("LLM 응답은 JSON 객체여야 합니다.")
        cleaned = sanitize_llm_payload(body)
        if "answer" in cleaned and (
            not isinstance(cleaned["answer"], str) or not cleaned["answer"].strip()
        ):
            raise LlmServiceResponseError("LLM이 유효한 최종 답변을 반환하지 않았습니다.")
        return cleaned
