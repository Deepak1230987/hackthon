import asyncio
import time


class TokenBucket:
    """Lets one call through per interval, however many are waiting."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1 / per_second
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)
