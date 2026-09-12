"""LLM provider 출력에서 내부 추론을 제거하고 공개 응답만 추출한다."""

from __future__ import annotations

import json
import re
from typing import Any


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*|```", re.IGNORECASE)
_REASONING_BLOCK_RE = re.compile(
    r"<(?:think|thinking|analysis|reasoning)>.*?</(?:think|thinking|analysis|reasoning)>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_REASONING_RE = re.compile(
    r"^\s*<(?:think|thinking|analysis|reasoning)>.*$",
    re.IGNORECASE | re.DOTALL,
)
_PUBLIC_TEXT_KEYS = {
    "answer",
    "claim",
    "definition",
    "negative",
    "positive",
    "question",
    "questions",
    "role",
    "summary",
    "value",
}


def extract_json_object(response_text: str) -> dict[str, Any]:
    """설명이 앞뒤에 섞인 문자열에서 첫 번째 유효한 JSON 객체를 찾는다.

    ``re.search(r"{.*}", ..., re.DOTALL)`` 같은 탐욕 정규식은 여러 객체,
    문자열 내부 중괄호와 중첩 객체를 구분하지 못한다. JSONDecoder를 각 여는
    중괄호 위치에서 시도해 실제로 해석 가능한 객체만 반환한다.
    """

    cleaned = _CODE_FENCE_RE.sub("", response_text).strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _end = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise json.JSONDecodeError("no JSON object found", cleaned, 0)


def clean_model_text(value: str) -> str:
    """사용자에게 노출하면 안 되는 명시적 reasoning 블록을 제거한다."""

    cleaned = _REASONING_BLOCK_RE.sub("", value)
    # 닫히지 않은 reasoning 태그는 안전하게 전체를 숨긴다.
    cleaned = _UNCLOSED_REASONING_RE.sub("", cleaned)
    cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()

    # 일부 provider는 answer 문자열 안에 reasoning + 최종 JSON을 넣는다.
    # 이 경우 공개 answer만 꺼내고 임의의 일반 문장 속 JSON은 건드리지 않는다.
    if "{" in cleaned and not cleaned.lstrip().startswith("{"):
        try:
            embedded = extract_json_object(cleaned)
        except json.JSONDecodeError:
            pass
        else:
            answer = embedded.get("answer")
            if isinstance(answer, str):
                return clean_model_text(answer)
    return cleaned


def sanitize_llm_payload(value: Any, *, key: str | None = None) -> Any:
    """LLM 응답 중 모델 생성 텍스트만 정제하고 출처 원문은 보존한다."""

    if isinstance(value, dict):
        return {
            item_key: sanitize_llm_payload(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_llm_payload(item, key=key) for item in value]
    if isinstance(value, str) and key in _PUBLIC_TEXT_KEYS:
        return clean_model_text(value)
    return value
