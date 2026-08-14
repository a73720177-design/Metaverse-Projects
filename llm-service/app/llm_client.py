"""
Ollama 로컬 서버(qwen3:14b)를 호출하고, 응답에서 JSON만 안전하게 뽑아내는 모듈.

Qwen3는 reasoning 모델이라 <think>...</think> 태그로 사고 과정이
응답 앞부분에 섞여 나올 수 있음. 이 모듈이 그 부분을 제거하고
순수 JSON만 파싱해서 돌려준다.
"""

import json
import os
import re

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))


class LLMError(Exception):
    """Ollama 호출 또는 응답 파싱 과정에서 발생하는 에러"""


def _strip_think_tags(text: str) -> str:
    """<think>...</think> 블록을 제거한다."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict:
    """텍스트 안에서 첫 '{' 부터 마지막 '}' 까지를 잘라내 JSON으로 파싱한다."""
    cleaned = _strip_think_tags(text)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"응답에서 JSON 형식을 찾지 못했습니다. 원본 응답: {text[:500]}")

    json_str = cleaned[start : end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON 파싱 실패: {e}. 추출된 문자열: {json_str[:500]}") from e


def call_llm(prompt: str, model: str | None = None) -> dict:
    """
    Ollama /api/generate 엔드포인트를 호출하고, 응답에서 JSON 객체를 추출해 반환한다.

    Raises:
        LLMError: Ollama 서버 호출 실패 또는 응답 파싱 실패 시
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

    raw_text = response.json().get("response", "")
    if not raw_text:
        raise LLMError("Ollama 응답이 비어 있습니다.")

    return _extract_json(raw_text)
