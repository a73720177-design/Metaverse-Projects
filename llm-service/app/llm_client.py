"""
Ollama 또는 vLLM OpenAI 호환 서버를 호출하는 클라이언트.

모델 출력을 구조화된 JSON으로 검증하는 부분(파싱)은 이 모듈이 아니라 호출하는
쪽(app/main.py)이 담당한다. 이 모듈은 Ollama HTTP 호출, 응답 형식을 JSON
Schema로 강제하는 것(response_schema), 연결 오류 처리만 담당한다.
"""

import os
import json
from collections.abc import Iterator

import requests
from dotenv import load_dotenv

# os.getenv()가 모듈 로드 시점에 바로 읽히므로, 반드시 그 전에 .env를 로드해야 한다.
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "").strip() or OLLAMA_MODEL

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_MAX_OUTPUT_TOKENS = int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "1024"))
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8002").rstrip("/")
VLLM_MODEL = os.getenv("VLLM_MODEL", "").strip()
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "").strip()
CHAT_MODEL = VLLM_MODEL if os.getenv("LLM_PROVIDER", "ollama").lower() == "vllm" else OLLAMA_CHAT_MODEL


class LLMError(Exception):
    """Configured model server call failed."""


def _provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "vllm"}:
        raise LLMError("LLM_PROVIDER must be ollama or vllm")
    return provider


def _vllm_headers() -> dict[str, str]:
    api_key = os.getenv("VLLM_API_KEY", VLLM_API_KEY).strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _vllm_model(model: str | None) -> str:
    configured = os.getenv("VLLM_MODEL", VLLM_MODEL).strip()
    resolved = model or configured
    if not resolved:
        raise LLMError("VLLM_MODEL is required when LLM_PROVIDER=vllm")
    return resolved


def call_llm(
    prompt: str,
    model: str | None = None,
    response_schema: dict | None = None,
    think: bool = False,
    max_tokens: int | None = None,
) -> str:
    """
    Ollama /api/generate를 호출하고 원본 응답 텍스트를 그대로 반환한다.

    response_schema를 넘기면 Ollama의 structured output 기능으로 모델이
    해당 JSON Schema를 따르는 출력만 내도록 강제한다.

    qwen3는 reasoning 모델이라 think=True면 추론 과정이 응답에 섞여
    JSON 파싱이 깨질 수 있다. 기본값 False로 추론 과정을 끈다.

    Raises:
        LLMError: Ollama 서버 호출 실패 시
    """
    if _provider() == "vllm":
        payload = {
            "model": _vllm_model(model),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
        }
        if response_schema is not None:
            payload["structured_outputs"] = {"json": response_schema}
        try:
            response = requests.post(
                f"{os.getenv('VLLM_BASE_URL', VLLM_BASE_URL).rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=_vllm_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("vLLM 호출 실패") from exc

    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS},
    }
    if response_schema is not None:
        payload["format"] = response_schema

    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise LLMError(
            f"Ollama 서버 호출 실패 (host={OLLAMA_HOST}, model={model or OLLAMA_MODEL}): {e}"
        ) from e

    return response.json().get("response", "")


def stream_llm(
    prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Ollama token chunks for latency-sensitive chat responses."""
    if _provider() == "vllm":
        payload = {
            "model": _vllm_model(model),
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
        }
        try:
            with requests.post(
                f"{os.getenv('VLLM_BASE_URL', VLLM_BASE_URL).rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=_vllm_headers(),
                timeout=REQUEST_TIMEOUT,
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode() if isinstance(line, bytes) else line
                    if not decoded.startswith("data:"):
                        continue
                    data = decoded.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)["choices"][0]["delta"].get("content", "")
                    if chunk:
                        yield chunk
            return
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("vLLM 스트리밍 호출 실패") from exc

    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS},
    }
    try:
        with requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line).get("response", "")
                if chunk:
                    yield chunk
    except (requests.RequestException, ValueError) as exc:
        raise LLMError("Ollama 스트리밍 호출 실패") from exc


def check_ollama_health() -> bool:
    """Configured provider health check. Kept name for API compatibility."""
    try:
        if _provider() == "vllm":
            response = requests.get(
                f"{os.getenv('VLLM_BASE_URL', VLLM_BASE_URL).rstrip('/')}/v1/models",
                headers=_vllm_headers(),
                timeout=5,
            )
            return response.ok
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.ok
    except (requests.RequestException, LLMError):
        return False
