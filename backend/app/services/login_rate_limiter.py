from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock


class LoginRateLimiter:
    """Process-local sliding-window limiter for failed login attempts."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts < 1 or window_seconds < 1:
            raise ValueError("Rate limit values must be positive integers.")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def retry_after(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            attempts = self._active_attempts(key, now)
            if len(attempts) < self.max_attempts:
                return 0
            return max(1, math.ceil(self.window_seconds - (now - attempts[0])))

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            attempts = self._active_attempts(key, now)
            attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _active_attempts(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts[key]
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            # Keep the deque returned to the caller, but remove abandoned keys
            # when this method is only used by retry_after().
            self._attempts[key] = attempts
        return attempts
