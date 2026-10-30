import asyncio
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RunEvent

TERMINAL_STATUSES = {"completed", "partial", "failed"}

_INSERT = text(
    """
    INSERT INTO run_events (run_id, seq, type, payload)
    SELECT :run_id, COALESCE(MAX(seq), 0) + 1, :type, CAST(:payload AS jsonb)
    FROM run_events WHERE run_id = :run_id
    RETURNING seq
    """
)


def is_terminal(event: RunEvent) -> bool:
    return event.type == "run_status" and event.payload.get("status") in TERMINAL_STATUSES


class EventStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._wakeups: dict[str, asyncio.Event] = {}

    async def emit(self, run_id: str, type: str, payload: dict[str, Any] | None = None) -> int:
        async with self._sessions() as session:
            # The lock lasts for this transaction, so concurrent emits can't share a seq.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:run_id))"), {"run_id": run_id}
            )
            result = await session.execute(
                _INSERT, {"run_id": run_id, "type": type, "payload": json.dumps(payload or {})}
            )
            seq = result.scalar_one()
            await session.commit()
        wake = self._wakeups.pop(run_id, None)
        if wake:
            wake.set()
        return seq

    def waiter(self, run_id: str) -> asyncio.Event:
        """An event that is set the next time this run emits."""
        return self._wakeups.setdefault(run_id, asyncio.Event())

    async def since(
        self, session: AsyncSession, run_id: Any, seq: int
    ) -> Sequence[RunEvent]:
        result = await session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.seq > seq)
            .order_by(RunEvent.seq)
        )
        return result.all()
