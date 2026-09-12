"""Remove explicit reasoning markup without changing quoted source evidence."""

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any


_TAG_RE = re.compile(r"</?(?:think|thinking|analysis|reasoning)\s*>", re.IGNORECASE)
_TAG_PREFIXES = tuple(
    f"<{closing}{name}"
    for closing in ("", "/")
    for name in ("think", "thinking", "analysis", "reasoning")
)
_GENERATED_KEYS = {
    "answer", "claim", "definition", "description", "negative", "positive",
    "question", "questions", "role", "summary", "value", "topic", "outline",
    "points", "text", "name",
}


class ReasoningFilter:
    """Withhold incomplete tags so a tag split over transport chunks stays private."""

    def __init__(self) -> None:
        self._pending = ""
        self._depth = 0

    def feed(self, text: str, *, final: bool = False) -> str:
        self._pending += text
        visible = []
        while self._pending:
            match = _TAG_RE.search(self._pending)
            if match:
                if self._depth == 0:
                    visible.append(self._pending[:match.start()])
                closing = match.group().startswith("</")
                self._depth = max(0, self._depth - 1) if closing else self._depth + 1
                self._pending = self._pending[match.end():]
                continue

            # Keep a trailing possible tag prefix until the next chunk. Drop an
            # unfinished reasoning block at EOF, rather than exposing its body.
            pending_start = self._pending.rfind("<")
            suffix = self._pending[pending_start:].lower() if pending_start >= 0 else ""
            possible_tag = suffix and any(
                tag.startswith(suffix) or suffix.startswith(tag) for tag in _TAG_PREFIXES
            )
            if possible_tag and not final:
                if self._depth == 0:
                    visible.append(self._pending[:pending_start])
                self._pending = self._pending[pending_start:]
                break
            if self._depth == 0:
                visible.append(self._pending[:pending_start] if possible_tag else self._pending)
            self._pending = ""
        return "".join(visible)


def clean_model_text(text: str) -> str:
    return ReasoningFilter().feed(text, final=True).strip()


def extract_json_object(text: str, required_keys: Iterable[str] = ()) -> dict:
    """Parse complete objects outside reasoning; never join separate JSON objects."""
    cleaned = text
    required = set(required_keys)
    decoder = json.JSONDecoder()
    cursor = 0
    first = None
    depth = 0
    while cursor < len(cleaned):
        start = cleaned.find("{", cursor)
        tag = _TAG_RE.search(cleaned, cursor)
        if tag is not None and (depth or start < 0 or tag.start() < start):
            depth = max(0, depth - 1) if tag.group().startswith("</") else depth + 1
            cursor = tag.end()
            continue
        if depth or start < 0:
            break
        try:
            value, end = decoder.raw_decode(cleaned, start)
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        cursor = end
        if isinstance(value, dict):
            if first is None:
                first = value
            if required.issubset(value):
                return value
    if first is not None:
        return first  # Let the response schema report missing required fields.
    raise json.JSONDecodeError("no public JSON object found", cleaned, 0)


def sanitize_payload(value: Any, key: str | None = None) -> Any:
    if key in {"sources", "evidence"}:
        return value  # These are original quotations, not model-facing prose.
    if isinstance(value, dict):
        return {k: sanitize_payload(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(v, key) for v in value]
    if isinstance(value, str) and key in _GENERATED_KEYS:
        return clean_model_text(value)
    return value


def clean_chat_text(text: str, max_lines: int = 30) -> str:
    """Bound final prose and drop repeated non-empty lines, preserving first occurrence."""
    lines = []
    seen = set()
    for line in clean_model_text(text).splitlines():
        normalized = " ".join(line.split())
        if normalized and normalized in seen:
            continue
        if normalized:
            seen.add(normalized)
        lines.append(line.rstrip())
        if len(lines) >= max_lines:
            break
    return "\n".join(lines).strip()


def safe_stream(chunks: Iterable[str], max_lines: int = 30) -> Iterator[str]:
    """Preserve token events while filtering reasoning and enforce the same line cap."""
    reasoning = ReasoningFilter()
    line_breaks = 0
    iterator = iter(chunks)
    try:
        for chunk in iterator:
            visible = reasoning.feed(chunk)
            if not visible:
                continue
            remaining = max_lines - line_breaks
            parts = visible.split("\n")
            at_limit = len(parts) > remaining
            if at_limit:
                visible = "\n".join(parts[:remaining])
            if visible:
                yield visible
                line_breaks += visible.count("\n")
            if at_limit:
                return
        tail = reasoning.feed("", final=True)
        if tail:
            yield "\n".join(tail.split("\n")[:max_lines - line_breaks])
    finally:
        close = getattr(iterator, "close", None)
        if close:
            close()
