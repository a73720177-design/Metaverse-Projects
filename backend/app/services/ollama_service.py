import json
import os
from typing import Any

import httpx


class OllamaConnectionError(RuntimeError):
    pass


class OllamaResponseError(RuntimeError):
    pass


class OllamaService:
    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.timeout = float(os.getenv("OLLAMA_TIMEOUT", "120"))

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        payload = {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaConnectionError(
                f"Ollama에 연결할 수 없습니다: {self.base_url}. Ollama 실행 상태를 확인하세요."
            ) from exc

        try:
            body = response.json()
            return json.loads(body["response"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaResponseError("Ollama가 유효한 JSON을 반환하지 않았습니다.") from exc
