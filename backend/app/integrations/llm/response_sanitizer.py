"""LLM provider 출력에서 내부 추론을 제거하고 공개 응답만 추출한다."""

from __future__ import annotations

import json
import re
from typing import Any


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.IGNORECASE | re.DOTALL)
_REASONING_TAG_RE = re.compile(
    r"<\s*(/?)\s*(think|thinking|analysis|reasoning)\s*>", re.IGNORECASE
)
_PRIVATE_KEYS = {"think", "thinking", "analysis", "reasoning", "reasoning_content"}
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
    "title",
    "points",
    "key_topics",
}


def _without_reasoning(value: str) -> str:
    """Suppress nested/unclosed blocks and prefixes before orphan closing tags."""
    visible: list[str] = []
    stack: list[str] = []
    cursor = 0
    for tag in _REASONING_TAG_RE.finditer(value):
        if not stack:
            visible.append(value[cursor:tag.start()])
        name = tag.group(2).lower()
        if not tag.group(1):
            stack.append(name)
        elif stack:
            if stack[-1] == name:
                stack.pop()
        else:
            # Some model templates omit the opening <think> token.
            visible.clear()
        cursor = tag.end()
    if not stack:
        visible.append(value[cursor:])
    return "".join(visible)


def extract_json_object(response_text: str) -> dict[str, Any]:
    """추론을 제외한 문자열에서 유일한 유효 JSON 객체를 찾는다.

    ``re.search(r"{.*}", ..., re.DOTALL)`` 같은 탐욕 정규식은 여러 객체,
    문자열 내부 중괄호와 중첩 객체를 구분하지 못한다. JSONDecoder를 각 여는
    중괄호 위치에서 시도해 실제로 해석 가능한 객체만 반환한다.
    """

    cleaned = _without_reasoning(response_text).strip()
    fence = _JSON_FENCE_RE.fullmatch(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    cursor = 0
    while match := re.search(r"[\{\[]", cleaned[cursor:]):
        start = cursor + match.start()
        try:
            value, end = decoder.raw_decode(cleaned, start)
        except json.JSONDecodeError:
            # Do not reinterpret a nested object in broken JSON as the answer.
            raise json.JSONDecodeError("invalid JSON object", cleaned, start) from None
        cursor = end
        if isinstance(value, dict):
            candidates.append(value)
        else:
            raise json.JSONDecodeError("root must be an object", cleaned, start)
    if len(candidates) != 1:
        raise json.JSONDecodeError("expected exactly one JSON object", cleaned, 0)
    return candidates[0]


def clean_model_text(value: str) -> str:
    """사용자에게 노출하면 안 되는 명시적 reasoning 블록을 제거한다."""

    cleaned = _without_reasoning(value).strip()

    # 일부 provider는 answer 문자열 안에 reasoning + 최종 JSON을 넣는다.
    # 이 경우 공개 answer만 꺼내고 임의의 일반 문장 속 JSON은 건드리지 않는다.
    if "{" in cleaned:
        try:
            embedded = extract_json_object(cleaned)
        except json.JSONDecodeError:
            pass
        else:
            answer = embedded.get("answer")
            if isinstance(answer, str):
                # Avoid recursive calls on arbitrarily nested model output.
                return _without_reasoning(answer).strip()
    return cleaned


def sanitize_llm_payload(value: Any, *, key: str | None = None) -> Any:
    """LLM 응답 중 모델 생성 텍스트만 정제하고 출처 원문은 보존한다."""

    if isinstance(value, dict):
        return {
            item_key: sanitize_llm_payload(item_value, key=item_key)
            for item_key, item_value in value.items()
            if item_key.lower() not in _PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [sanitize_llm_payload(item, key=key) for item in value]
    if isinstance(value, str) and key in _PUBLIC_TEXT_KEYS:
        return clean_model_text(value)
    return value
