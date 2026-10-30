import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.db.models import Run
from app.graph.deps import Deps, RunFailed
from app.graph.state import SourceRequest, initial_state

log = logging.getLogger(__name__)


class RunRunner:
    def __init__(self, graph: Any, deps: Deps) -> None:
        self._graph = graph
        self._deps = deps
        self._semaphore = asyncio.Semaphore(deps.settings.max_concurrent_runs)
        self._tasks: set[asyncio.Task] = set()

    def start(self, run_id: str, language: str, source: SourceRequest) -> None:
        task = asyncio.create_task(self._execute(run_id, language, source))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def recover(self) -> None:
        """Pick up runs that a restart left unfinished."""
        async with self._deps.sessions() as session:
            runs = await session.scalars(select(Run).where(Run.status.in_(("queued", "running"))))
            unfinished = runs.all()
        for run in unfinished:
            log.info("Recovering run %s", run.id)
            self.start(str(run.id), run.language, run.source)

    async def shutdown(self) -> None:
        # Cancelled runs stay marked running, so the next startup resumes them.
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, run_id: str, language: str, source: SourceRequest) -> None:
        async with self._semaphore:
            try:
                await self._set_status(run_id, "running")
                async with asyncio.timeout(self._deps.settings.run_timeout_s):
                    await self._invoke(run_id, language, source)
            except RunFailed as exc:
                await self._fail(run_id, exc.code, exc.message, exc.action)
            except TimeoutError:
                await self._fail(
                    run_id, "RUN_TIMEOUT", "This run took too long and was stopped.", "retry"
                )
            except Exception:
                log.exception("Run %s failed", run_id)
                await self._fail(run_id, "INTERNAL_ERROR", "Something went wrong.", "retry")
            else:
                await self._set_status(run_id, "completed", finished=True)
                await self._deps.events.emit(run_id, "run_completed")

    async def _invoke(self, run_id: str, language: str, source: SourceRequest) -> None:
        config = {"configurable": {"thread_id": run_id}}
        checkpoint = await self._graph.aget_state(config)
        # With a checkpoint, None continues from it. Without one, start from the beginning.
        started = bool(checkpoint.values)
        await self._graph.ainvoke(
            None if started else initial_state(run_id, language, source), config
        )

    async def _fail(self, run_id: str, code: str, message: str, action: str | None) -> None:
        await self._set_status(run_id, "failed", finished=True, error_code=code)
        await self._deps.events.emit(
            run_id, "run_failed", {"code": code, "message": message, "action": action, "details": {}}
        )

    async def _set_status(
        self, run_id: str, status: str, finished: bool = False, error_code: str | None = None
    ) -> None:
        values: dict[str, Any] = {"status": status, "error_code": error_code}
        if finished:
            values["finished_at"] = datetime.now(UTC)
        async with self._deps.sessions() as session:
            await session.execute(update(Run).where(Run.id == run_id).values(**values))
            await session.commit()
