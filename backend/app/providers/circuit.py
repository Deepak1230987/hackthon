import time
from collections import deque
from collections.abc import Callable

MAX_FAILURES = 5
WINDOW_S = 60
OPEN_S = 60


class Circuit:
    """Stops calling a provider that keeps failing, so each run doesn't wait through its retries."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: deque[float] = deque()
        self._open_until = 0.0

    def is_open(self) -> bool:
        return self._clock() < self._open_until

    def record_failure(self) -> None:
        now = self._clock()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > WINDOW_S:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            self._open_until = now + OPEN_S
            self._failures.clear()

    def record_success(self) -> None:
        self._failures.clear()
