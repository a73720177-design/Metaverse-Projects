"""Remove explicit reasoning markup without changing quoted source evidence."""

import re


_TAG_RE = re.compile(r"</?(?:think|thinking|analysis|reasoning)\s*>", re.IGNORECASE)
_TAG_PREFIXES = tuple(
    f"<{closing}{name}"
    for closing in ("", "/")
    for name in ("think", "thinking", "analysis", "reasoning")
)
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
