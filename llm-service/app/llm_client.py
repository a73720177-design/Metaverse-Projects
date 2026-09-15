"""
Ollama 또는 vLLM OpenAI 호환 서버를 호출하는 클라이언트.

모델 출력을 구조화된 JSON으로 검증하는 부분(파싱)은 이 모듈이 아니라 호출하는
쪽(app/main.py)이 담당한다. 이 모듈은 Ollama HTTP 호출, 응답 형식을 JSON
Schema로 강제하는 것(response_schema), 연결 오류 처리만 담당한다.
"""

import os
import json
import math
from collections.abc import Iterator
from threading import BoundedSemaphore

import requests
from dotenv import load_dotenv

# os.getenv()가 모듈 로드 시점에 바로 읽히므로, 반드시 그 전에 .env를 로드해야 한다.
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "").strip() or OLLAMA_MODEL
OLLAMA_REVIEW_MODEL = os.getenv("OLLAMA_REVIEW_MODEL", "qwen3:8b").strip()
OLLAMA_QUESTION_MODEL = os.getenv("OLLAMA_QUESTION_MODEL", "").strip() or OLLAMA_REVIEW_MODEL
OLLAMA_SUMMARY_MODEL = os.getenv("OLLAMA_SUMMARY_MODEL", "").strip() or OLLAMA_REVIEW_MODEL
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3").strip()
OLLAMA_EMBED_BATCH = int(os.getenv("OLLAMA_EMBED_BATCH", "32"))
if OLLAMA_EMBED_BATCH < 1:
    raise RuntimeError("OLLAMA_EMBED_BATCH must be at least 1")

# 응답 생성이 오래 걸릴 수 있어 타임아웃을 넉넉히 잡는다 (초 단위)
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_MAX_OUTPUT_TOKENS = int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "1024"))
LLM_MAX_CONCURRENT_GENERATIONS = int(
    os.getenv("LLM_MAX_CONCURRENT_GENERATIONS", "3")
)
if LLM_MAX_CONCURRENT_GENERATIONS < 1:
    raise RuntimeError("LLM_MAX_CONCURRENT_GENERATIONS must be at least 1")
_GENERATION_SLOTS = BoundedSemaphore(LLM_MAX_CONCURRENT_GENERATIONS)
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


def _disable_thinking_prompt(prompt: str, *, think: bool = False) -> str:
    """Use Qwen's prompt switch as a second guard in addition to API options."""
    if think or prompt.rstrip().endswith("/no_think"):
        return prompt
    return f"{prompt.rstrip()}\n/no_think"


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
    guarded_prompt = _disable_thinking_prompt(prompt, think=think)
    if _provider() == "vllm":
        payload = {
            "model": _vllm_model(model),
            "messages": [{"role": "user", "content": guarded_prompt}],
            "stream": False,
            "max_tokens": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
            "temperature": 0.35,
            "repetition_penalty": 1.18,
            "chat_template_kwargs": {"enable_thinking": think},
        }
        if response_schema is not None:
            payload["structured_outputs"] = {"json": response_schema}
        try:
            with _GENERATION_SLOTS:
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
        "prompt": guarded_prompt,
        "stream": False,
        "think": think,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
            "temperature": 0.35,
            "repeat_penalty": 1.18,
            "repeat_last_n": 256,
        },
    }
    if response_schema is not None:
        payload["format"] = response_schema

    try:
        with _GENERATION_SLOTS:
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

    try:
        body = response.json()
        text = body.get("response", "")
        if body.get("error") or not isinstance(text, str):
            raise ValueError("invalid generation response")
        return text
    except (ValueError, AttributeError, TypeError) as exc:
        raise LLMError("Ollama 응답 형식이 올바르지 않습니다.") from exc


def stream_llm(
    prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Ollama token chunks for latency-sensitive chat responses."""
    guarded_prompt = _disable_thinking_prompt(prompt)
    if _provider() == "vllm":
        payload = {
            "model": _vllm_model(model),
            "messages": [{"role": "user", "content": guarded_prompt}],
            "stream": True,
            "max_tokens": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
            "temperature": 0.35,
            "repetition_penalty": 1.18,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            with _GENERATION_SLOTS:
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
                        event = json.loads(data)
                        if event.get("error"):
                            raise LLMError("vLLM 스트리밍 호출 실패")
                        choices = event.get("choices")
                        if choices == []:  # Optional usage-only SSE event.
                            continue
                        chunk = choices[0]["delta"].get("content", "")
                        if chunk is not None and not isinstance(chunk, str):
                            raise ValueError("invalid stream content")
                        if chunk:
                            yield chunk
            return
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise LLMError("vLLM 스트리밍 호출 실패") from exc

    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": guarded_prompt,
        "stream": True,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
            "temperature": 0.35,
            "repeat_penalty": 1.18,
            "repeat_last_n": 256,
        },
    }
    try:
        with _GENERATION_SLOTS:
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
                    event = json.loads(line)
                    if event.get("error"):
                        raise LLMError("Ollama 스트리밍 호출 실패")
                    chunk = event.get("response", "")
                    if not isinstance(chunk, str):
                        raise ValueError("invalid stream content")
                    if chunk:
                        yield chunk
                    if event.get("done"):
                        break
    except (requests.RequestException, ValueError, AttributeError, TypeError) as exc:
        raise LLMError("Ollama 스트리밍 호출 실패") from exc


def check_ollama_health() -> bool:
    """Configured provider health check. Kept name for API compatibility.

    For Ollama this also confirms the configured embedding model has been
    pulled (checked via /api/tags), since /api/v1/embeddings silently fails
    otherwise.
    """
    try:
        if _provider() == "vllm":
            response = requests.get(
                f"{os.getenv('VLLM_BASE_URL', VLLM_BASE_URL).rstrip('/')}/v1/models",
                headers=_vllm_headers(),
                timeout=5,
            )
            return response.ok
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if not response.ok:
            return False
        available = {
            str(model.get("name", "")).split(":")[0]
            for model in response.json().get("models", [])
        }
        required = {
            OLLAMA_CHAT_MODEL.split(":")[0],
            OLLAMA_REVIEW_MODEL.split(":")[0],
            OLLAMA_QUESTION_MODEL.split(":")[0],
            OLLAMA_SUMMARY_MODEL.split(":")[0],
            OLLAMA_EMBEDDING_MODEL.split(":")[0],
        }
        return required <= available
    except (requests.RequestException, LLMError, ValueError):
        return False


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create retrieval vectors with the configured embedding model.

    Requests are chunked to OLLAMA_EMBED_BATCH items so a large indexing job
    doesn't send one oversized call to Ollama; batch order is preserved.
    """
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), OLLAMA_EMBED_BATCH):
        batch = texts[start : start + OLLAMA_EMBED_BATCH]
        try:
            response = requests.post(
                f"{OLLAMA_HOST}/api/embed",
                json={"model": OLLAMA_EMBEDDING_MODEL, "input": batch},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            batch_embeddings = response.json().get("embeddings")
            if not isinstance(batch_embeddings, list) or len(batch_embeddings) != len(batch):
                raise ValueError("invalid embedding response")
            if any(
                not isinstance(vector, list) or not vector or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) for value in vector
                ) for vector in batch_embeddings
            ):
                raise ValueError("invalid embedding vector")
        except (requests.RequestException, ValueError, AttributeError, TypeError) as exc:
            raise LLMError("임베딩 모델 호출 실패") from exc
        embeddings.extend(batch_embeddings)
    return embeddings


async def stream_llm_async(prompt: str, model: str | None = None, max_tokens: int | None = None):
    """Cancellation closes the provider HTTP response, including while awaiting tokens."""
    import asyncio
    import httpx
    provider = _provider()
    guarded = _disable_thinking_prompt(prompt)
    if provider == "vllm":
        url = f"{os.getenv('VLLM_BASE_URL', VLLM_BASE_URL).rstrip('/')}/v1/chat/completions"
        payload = {"model": _vllm_model(model), "messages": [{"role": "user", "content": guarded}],
                   "stream": True, "max_tokens": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
                   "temperature": 0.35, "chat_template_kwargs": {"enable_thinking": False}}
    else:
        url = f"{OLLAMA_HOST}/api/generate"
        payload = {"model": model or OLLAMA_MODEL, "prompt": guarded, "stream": True,
                   "think": False, "keep_alive": OLLAMA_KEEP_ALIVE,
                   "options": {"num_predict": max_tokens or OLLAMA_MAX_OUTPUT_TOKENS,
                               "temperature": 0.35, "repeat_penalty": 1.18}}
    acquired = False
    completed = False
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            while not _GENERATION_SLOTS.acquire(blocking=False):
                await asyncio.sleep(0.05)
            acquired = True
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                async with client.stream("POST", url, json=payload,
                                         headers=_vllm_headers() if provider == "vllm" else {}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if provider == "vllm":
                            if not line.startswith("data:"):
                                continue
                            line = line[5:].strip()
                            if line == "[DONE]":
                                completed = True
                                break
                        event = json.loads(line)
                        if event.get("error"):
                            raise LLMError("모델 스트리밍 생성 실패")
                        if provider == "vllm":
                            choices = event.get("choices", [])
                            chunk = choices[0]["delta"].get("content") or "" if choices else ""
                        else:
                            chunk = event.get("response", "")
                        if not isinstance(chunk, str):
                            raise ValueError("invalid token")
                        if chunk:
                            yield chunk
                        if provider == "ollama" and event.get("done"):
                            completed = True
                            break
        if not completed:
            raise LLMError("모델 스트림이 완료 전에 종료되었습니다.")
    except (httpx.HTTPError, TimeoutError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise LLMError("모델 스트리밍 연결 또는 응답 오류") from exc
    finally:
        if acquired:
            _GENERATION_SLOTS.release()
