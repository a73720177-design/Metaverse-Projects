"""
Ollama 로컬 서버를 호출하는 클라이언트.

모델은 역할에 따라 둘로 나눈다.
- OLLAMA_MODEL (qwen3:8b): 추론(think)이 필요한 경로. 최초 평가, 채팅 피드백.
- OLLAMA_CHAT_MODEL (qwen3:4b): 추론 없이 빠르게 끝내는 경로. 페르소나 생성,
  인사말 응답.
임베딩(OLLAMA_EMBED_MODEL, bge-m3)은 세 모델 중 유일하게 항상 호출되며,
모든 답변 경로가 생성 전에 이 모델로 자료를 검색한다.

모델 출력을 구조화된 JSON으로 검증하는 부분(파싱)은 이 모듈이 아니라 호출하는
쪽(app/main.py)이 담당한다. 이 모듈은 Ollama HTTP 호출, 응답 형식을 JSON
Schema로 강제하는 것(response_schema), 연결 오류 처리만 담당한다.
"""

import os
import re

import requests
from dotenv import load_dotenv

# os.getenv()가 모듈 로드 시점에 바로 읽히므로, 반드시 그 전에 .env를 로드해야 한다.
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "").strip() or "qwen3:4b"
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_MAX_OUTPUT_TOKENS = int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "1024"))
# KV 캐시는 num_ctx에 비례해 VRAM을 먹는다. 세 모델을 16GB에 함께 올리려면
# Ollama 서버에도 OLLAMA_NUM_PARALLEL=1을 설정해야 이 값이 곱해지지 않는다.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

# 임베딩은 조각 수가 많아 한 번에 다 보내면 요청이 지나치게 커진다.
EMBED_BATCH_SIZE = int(os.getenv("OLLAMA_EMBED_BATCH", "64"))

# think=True일 때 Ollama 버전에 따라 사고 과정이 thinking 필드로 분리되지 않고
# response에 <think>...</think>로 섞여 나오는 경우가 있어 방어적으로 걷어낸다.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMError(Exception):
    """Ollama 서버 호출 실패 시 발생하는 에러"""


def call_llm(
    prompt: str,
    model: str | None = None,
    response_schema: dict | None = None,
    think: bool = False,
    max_tokens: int | None = None,
) -> str:
    """
    Ollama /api/generate를 호출하고 응답 텍스트를 반환한다.

    response_schema를 넘기면 Ollama의 structured output 기능으로 모델이
    해당 JSON Schema를 따르는 출력만 내도록 강제한다.

    think=True면 qwen3의 추론 과정을 켠다. 추론 토큰도 num_predict를
    소비하므로 max_tokens를 넉넉히 잡아야 답변이 잘리지 않는다.

    Raises:
        LLMError: Ollama 서버 호출 실패 시
    """
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
            "num_ctx": OLLAMA_NUM_CTX,
        },
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

    return _THINK_BLOCK_RE.sub("", response.json().get("response", ""))


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Ollama /api/embed로 텍스트 목록의 임베딩 벡터를 얻는다.

    Raises:
        LLMError: Ollama 서버 호출 실패 시, 또는 응답 개수가 입력과 다를 때
    """
    if not texts:
        return []

    embed_model = model or OLLAMA_EMBED_MODEL
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        try:
            response = requests.post(
                f"{OLLAMA_HOST}/api/embed",
                json={
                    "model": embed_model,
                    "input": batch,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as e:
            raise LLMError(
                f"Ollama 임베딩 호출 실패 (host={OLLAMA_HOST}, model={embed_model}): {e}"
            ) from e
        except ValueError as e:
            raise LLMError("Ollama 임베딩 응답이 JSON이 아닙니다.") from e

        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(batch):
            raise LLMError("Ollama 임베딩 응답 개수가 요청과 다릅니다.")
        vectors.extend(embeddings)

    return vectors


def check_ollama_health() -> bool:
    """Ollama가 응답하는지 확인한다. 예외를 던지지 않고 True/False만 반환."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.ok
    except requests.RequestException:
        return False
