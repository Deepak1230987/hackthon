import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Entry:
    values: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0.0


class ProfileStore:
    """Citizens' answers, in this process's memory only. They must never reach graph state,
    because checkpoints write that to disk. A restart loses them and the questions are asked again.
    """

    def __init__(self, ttl_s: int) -> None:
        self._ttl_s = ttl_s
        self._entries: dict[str, _Entry] = {}

    def get(self, run_id: str) -> dict[str, Any]:
        entry = self._entries.get(run_id)
        if entry is None or entry.expires_at <= time.monotonic():
            return {}
        return dict(entry.values)

    def merge(self, run_id: str, values: dict[str, Any]) -> None:
        entry = _Entry(self.get(run_id) | values, time.monotonic() + self._ttl_s)
        self._entries[run_id] = entry

    def purge_expired(self) -> None:
        now = time.monotonic()
        for run_id in [r for r, entry in self._entries.items() if entry.expires_at <= now]:
            del self._entries[run_id]
