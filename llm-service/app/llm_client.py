"""
Ollama 로컬 서버(qwen3:14b)를 호출하는 클라이언트.

모델 출력을 구조화된 JSON으로 검증하는 부분(파싱)은 이 모듈이 아니라 호출하는
쪽(app/main.py)이 담당한다. 이 모듈은 Ollama HTTP 호출, 응답 형식을 JSON
Schema로 강제하는 것(response_schema), 연결 오류 처리만 담당한다.
"""

import os

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))


class LLMError(Exception):
    """Ollama 서버 호출 실패 시 발생하는 에러"""


def call_llm(
    prompt: str,
    model: str | None = None,
    response_schema: dict | None = None,
) -> str:
    """
    Ollama /api/generate를 호출하고 원본 응답 텍스트를 그대로 반환한다.

    response_schema를 넘기면 Ollama의 structured output 기능으로 모델이
    해당 JSON Schema를 따르는 출력만 내도록 강제한다.

    Raises:
        LLMError: Ollama 서버 호출 실패 시
    """
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
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
