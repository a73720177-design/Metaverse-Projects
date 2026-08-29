"""
Ollama 로컬 서버(qwen3:14b)를 호출하는 클라이언트.

모델 출력을 구조화된 JSON으로 검증하는 부분(파싱)은 이 모듈이 아니라 호출하는
쪽(app/main.py)이 담당한다. 이 모듈은 Ollama HTTP 호출, 응답 형식을 JSON
Schema로 강제하는 것(response_schema), 연결 오류 처리만 담당한다.
"""

import os

import requests
from dotenv import load_dotenv

# os.getenv()가 모듈 로드 시점에 바로 읽히므로, 반드시 그 전에 .env를 로드해야 한다.
load_dotenv()

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
    think: bool = False,
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
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": think,
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


def check_ollama_health() -> bool:
    """Ollama가 응답하는지 확인한다. 예외를 던지지 않고 True/False만 반환."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.ok
    except requests.RequestException:
        return False
