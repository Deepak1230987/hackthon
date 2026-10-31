import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Run
from app.graph.events import EventStore


class BudgetExhausted(Exception):
    pass


class Budget:
    """One run's allowance of LLM calls, counted in the database so a restart can't reset it."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        events: EventStore,
        run_id: str,
        limit: int,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._run_id = run_id
        self._limit = limit

    async def charge(self) -> None:
        async with self._sessions() as session:
            used = await session.scalar(
                update(Run)
                .where(Run.id == uuid.UUID(self._run_id))
                .values(llm_calls=Run.llm_calls + 1)
                .returning(Run.llm_calls)
            )
            await session.commit()
        if used > self._limit:
            raise BudgetExhausted(f"{self._limit} LLM calls used")

    async def failover(self, source: str, target: str, reason: str) -> None:
        await self._events.emit(
            self._run_id, "failover", {"from": source, "to": target, "reason": reason}
        )
