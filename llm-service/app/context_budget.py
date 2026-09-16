"""One input/output budget for prompt construction and model requests.

Token counts are estimates, not a substitute for the model tokenizer. The
safety reserve covers chat templates and constrained-output overhead.
"""
import math
import os
from functools import lru_cache

from fastapi import HTTPException


def positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if value > 0:
            return value
    except ValueError:
        pass
    raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.")


def context_length() -> int:
    length = positive_int("LLM_MAX_MODEL_LEN", 8192)
    if os.getenv("LLM_PROVIDER", "ollama").strip().lower() == "vllm":
        # The client cannot enlarge an already running vLLM server.
        length = min(length, positive_int("VLLM_MAX_MODEL_LEN", 8192))
    return length


@lru_cache(maxsize=2)
def _local_tokenizer(path: str):
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(path, local_files_only=True)
    except (ImportError, OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="LLM_TOKENIZER_PATH의 로컬 토크나이저를 불러올 수 없습니다.") from exc


def estimated_tokens(text: str) -> int:
    path = os.getenv("LLM_TOKENIZER_PATH", "").strip()
    if path:
        # Must match the served model; no network calls or implicit downloads.
        return len(_local_tokenizer(path).encode(text, add_special_tokens=False))
    try:
        ratio = float(os.getenv("LLM_APPROX_CHARS_PER_TOKEN", "2.0"))
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="LLM_APPROX_CHARS_PER_TOKEN 설정이 올바르지 않습니다.") from exc
    return math.ceil(len(text) / ratio)


def input_budget(output_tokens: int) -> int:
    remaining = context_length() - output_tokens - positive_int("LLM_CONTEXT_SAFETY_TOKENS", 512)
    if output_tokens < 1 or remaining < 256:
        raise HTTPException(status_code=422, detail="출력 길이가 모델 컨텍스트에 비해 너무 큽니다.")
    return remaining


def prompt_fits(prompt: str, output_tokens: int) -> bool:
    # Reserve the existing Qwen prompt suffix even when the caller adds it later.
    guarded = prompt if prompt.rstrip().endswith("/no_think") else prompt + "\n/no_think"
    return estimated_tokens(guarded) <= input_budget(output_tokens)


def require_prompt_fits(prompt: str, output_tokens: int) -> None:
    if not prompt_fits(prompt, output_tokens):
        raise HTTPException(status_code=422, detail="입력과 출력이 모델 컨텍스트 한도를 초과했습니다. 입력을 줄이거나 컨텍스트 설정을 늘려주세요.")
