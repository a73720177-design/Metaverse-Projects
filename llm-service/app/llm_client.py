"""
Ollama 로컬 서버(qwen3:14b)를 호출하는 클라이언트.

모델 출력을 구조화된 JSON으로 받고 검증하는 부분(파싱)은 이 모듈이 아니라
정식 /api/v1 엔드포인트를 설계할 때 함께 정리한다. 이 모듈은 Ollama HTTP
호출과 연결 오류 처리만 담당한다.
"""

import os

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))


class LLMError(Exception):
    """Ollama 서버 호출 실패 시 발생하는 에러"""


def call_llm(prompt: str, model: str | None = None) -> str:
    """
    Ollama /api/generate를 호출하고 원본 응답 텍스트를 그대로 반환한다.

    Raises:
        LLMError: Ollama 서버 호출 실패 시
    """
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

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
