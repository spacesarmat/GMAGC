"""Код доступа телефона и защита от его подбора."""

from __future__ import annotations

import hmac
import math
import secrets
import threading
import time
from collections.abc import Callable

from gmagc_common.protocol import CODE_ALPHABET, CODE_LENGTH, normalize_code


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def codes_equal(expected: str, given: str) -> bool:
    """Сравнение за постоянное время; пустой код на ПК не совпадает ни с чем."""
    if not expected:
        return False
    return hmac.compare_digest(normalize_code(expected).encode("utf-8"), normalize_code(given).encode("utf-8"))


class RateLimiter:
    """После max_failures неверных кодов подряд адрес блокируется на block_seconds."""

    def __init__(
        self, max_failures: int = 5, block_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic
    ):
        if max_failures < 1:
            raise ValueError("max_failures должен быть положительным")
        self._max_failures = max_failures
        self._block_seconds = block_seconds
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """Сколько секунд адрес ещё заблокирован (0: можно пробовать)."""
        with self._lock:
            until = self._blocked_until.get(client)
            if until is None:
                return 0
            left = until - self._clock()
            if left <= 0:
                del self._blocked_until[client]
                return 0
            return math.ceil(left)

    def failure(self, client: str) -> None:
        with self._lock:
            count = self._failures.get(client, 0) + 1
            if count >= self._max_failures:
                self._blocked_until[client] = self._clock() + self._block_seconds
                count = 0
            self._failures[client] = count

    def success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
