import hashlib
import hmac
import math
from datetime import timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import Run


def client_hash(request: Request) -> str:
    """A keyed hash, so raw IPs are never stored and a stored hash can't be reversed by guessing."""
    key = request.app.state.services.settings.database_url.encode()
    host = request.client.host if request.client else "unknown"
    return hmac.new(key, host.encode(), hashlib.sha256).hexdigest()


async def _refuse_if_over_limit(session: AsyncSession, client: str, request: Request) -> None:
    settings = request.app.state.services.settings
    window = func.now() - timedelta(seconds=settings.run_limit_window_s)
    count, oldest_age = (
        await session.execute(
            select(
                func.count(),
                func.extract("epoch", func.now() - func.min(Run.created_at)),
            ).where(Run.client_hash == client, Run.created_at > window)
        )
    ).one()
    if count < settings.max_runs_per_ip:
        return
    wait_s = max(1, math.ceil(settings.run_limit_window_s - float(oldest_age)))
    minutes = math.ceil(wait_s / 60)
    raise ApiError(
        "RATE_LIMITED",
        f"You've started several documents in a short time. Try again in about {minutes} "
        f"{'minute' if minutes == 1 else 'minutes'}.",
        status=429,
        action="wait",
        details={"retry_after_s": wait_s},
    )


async def check_run_limit(request: Request) -> None:
    """Refuse early, before a large upload is read."""
    async with request.app.state.services.deps.sessions() as session:
        await _refuse_if_over_limit(session, client_hash(request), request)


async def new_run(request: Request, language: str, source: dict[str, Any]) -> str:
    services = request.app.state.services
    client = client_hash(request)
    async with services.deps.sessions() as session:
        # Held until commit, so rapid requests from one address can't all pass the count at once.
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": client})
        await _refuse_if_over_limit(session, client, request)
        run = Run(language=language, status="queued", source=source, client_hash=client)
        session.add(run)
        await session.commit()
        run_id = str(run.id)
    services.runner.start(run_id, language, source)
    return run_id


async def use_allowance(request: Request, run_id: Any, column: Any, limit: int) -> bool:
    """Count one use against a run's limit. False if it has none left."""
    async with request.app.state.services.deps.sessions() as session:
        used = await session.scalar(
            update(Run)
            .where(Run.id == run_id, column < limit)
            .values({column: column + 1})
            .returning(column)
        )
        await session.commit()
    return used is not None
