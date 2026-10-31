import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from app.db.models import Claim, Run
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
                    result = await self._invoke(run_id, language, source)
            except RunFailed as exc:
                await self._fail(run_id, exc.code, exc.message, exc.action, exc.details)
            except TimeoutError:
                await self._on_timeout(run_id)
            except Exception:
                log.exception("Run %s failed", run_id)
                await self._fail(run_id, "INTERNAL_ERROR", "Something went wrong.", "retry")
            else:
                status = "partial" if result.get("partial") else "completed"
                await self._set_status(run_id, status, finished=True)

    async def _invoke(self, run_id: str, language: str, source: SourceRequest) -> dict[str, Any]:
        config = {"configurable": {"thread_id": run_id}}
        checkpoint = await self._graph.aget_state(config)
        # With a checkpoint, None continues from it. Without one, start from the beginning.
        started = bool(checkpoint.values)
        return await self._graph.ainvoke(
            None if started else initial_state(run_id, language, source), config
        )

    async def _on_timeout(self, run_id: str) -> None:
        """Keep what was verified. Anything still unchecked is never shown."""
        run_uuid = uuid.UUID(run_id)
        async with self._deps.sessions() as session:
            await session.execute(
                update(Claim)
                .where(Claim.run_id == run_uuid, Claim.status == "pending")
                .values(status="not_stated", failure_reason="RUN_TIMEOUT")
            )
            verified = await session.scalar(
                select(func.count())
                .select_from(Claim)
                .where(Claim.run_id == run_uuid, Claim.status == "verified")
            )
            await session.commit()
        if verified:
            await self._set_status(run_id, "partial", finished=True)
        else:
            await self._fail(
                run_id, "RUN_TIMEOUT", "This run took too long and was stopped.", "retry"
            )

    async def _fail(
        self,
        run_id: str,
        code: str,
        message: str,
        action: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error = {"code": code, "message": message, "action": action, "details": details or {}}
        await self._set_status(run_id, "failed", finished=True, error=error)

    async def _set_status(
        self,
        run_id: str,
        status: str,
        finished: bool = False,
        error: dict[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "error_code": error["code"] if error else None}
        if finished:
            values["finished_at"] = datetime.now(UTC)
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error
        # Together, so a reader never sees a failed run without its error.
        await self._deps.events.emit(run_id, "run_status", payload, run_values=values)
