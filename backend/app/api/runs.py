import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.errors import ApiError
from app.db.models import Document, Run, RunEvent
from app.graph.events import is_terminal

router = APIRouter(prefix="/v1")

HEARTBEAT_S = 15


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, request: Request) -> dict:
    services = request.app.state.services
    async with services.deps.sessions() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise _not_found()
        document = await session.get(Document, run.document_id) if run.document_id else None
        events = await services.deps.events.since(session, run_id, 0)

    error = next((e.payload["error"] for e in events if "error" in e.payload), None)
    return {
        "id": str(run.id),
        "status": run.status,
        "language": run.language,
        "document": _document_view(document) if document else None,
        "error": error,
        "events": [{"seq": e.seq, "type": e.type, "payload": e.payload} for e in events],
    }


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    request: Request,
    last_event_id: int = Header(default=0, ge=0),
) -> StreamingResponse:
    services = request.app.state.services
    async with services.deps.sessions() as session:
        if await session.get(Run, run_id) is None:
            raise _not_found()
    return StreamingResponse(
        _event_stream(request, str(run_id), last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_stream(request: Request, run_id: str, last_seq: int) -> AsyncIterator[str]:
    deps = request.app.state.services.deps
    while True:
        # Take the wake-up before reading, so an event emitted in between isn't missed.
        wake = deps.events.waiter(run_id)
        async with deps.sessions() as session:
            events = await deps.events.since(session, run_id, last_seq)
        for event in events:
            last_seq = event.seq
            yield _format(event)
            if is_terminal(event):
                return
        if events:
            continue
        if await request.is_disconnected():
            return
        try:
            await asyncio.wait_for(wake.wait(), timeout=HEARTBEAT_S)
        except TimeoutError:
            yield ": heartbeat\n\n"


def _format(event: RunEvent) -> str:
    return f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(event.payload)}\n\n"


def _document_view(document: Document) -> dict:
    return {
        "id": str(document.id),
        "sha256": document.sha256,
        "source_url": document.source_url,
        "fetch_method": document.fetch_method,
        "fetched_at": document.fetched_at.isoformat(),
        "page_count": document.page_count,
        "title": document.title,
        "issuing_authority": document.issuing_authority,
        "issue_date": document.issue_date.isoformat() if document.issue_date else None,
    }


def _not_found() -> ApiError:
    return ApiError("RUN_NOT_FOUND", "That run wasn't found.", status=404, action="restart")
