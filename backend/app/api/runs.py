import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api import eligibility, limits
from app.api.errors import ApiError
from app.claims.schemas import CLAIM_FIELDS
from app.db.models import Claim, Clause, Document, Run, RunEvent
from app.documents.pages import page_range
from app.graph.events import is_terminal

router = APIRouter(prefix="/v1")
router.include_router(eligibility.router)

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
        claims = await _verified_claims(session, run_id)
        eligibility_fields = await eligibility.eligibility_view(session, run, events)
        queue_position = await _queue_position(session, run)

    window = page_range(run.source)
    error =next((e.payload["error"] for e in events if "error" in e.payload), None)
    return {
        "id": str(run.id),
        "status": run.status,
        "language": run.language,
        "queue_position": queue_position,
        "page_range": {"from": window[0], "to": window[1]} if window else None,
        "document": document_view(document) if document else None,
        "error": error,
        "claims": claims,
        "not_stated": [
            field for field in CLAIM_FIELDS if not any(c["field"] == field for c in claims)
        ],
        "events": [{"seq": e.seq, "type": e.type, "payload": e.payload} for e in events],
        **eligibility_fields,
    }


class PageRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    first: int = Field(alias="from")
    last: int = Field(alias="to")


@router.post("/runs/{run_id}/page-range", status_code=202)
async def choose_page_range(run_id: uuid.UUID, body: PageRange, request: Request) -> dict:
    """A new run over the chosen pages. The stopped run stays as it was."""
    services = request.app.state.services
    async with services.deps.sessions() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise _not_found()
        document = await session.get(Document, run.document_id) if run.document_id else None
    if document is None or run.error_code != "DOC_TOO_LONG":
        raise ApiError("PAGE_RANGE_NOT_NEEDED", "This run isn't waiting for a page range.", status=409)

    limit = services.settings.max_pages
    if not 1 <= body.first <= body.last <= document.page_count:
        raise ApiError(
            "INVALID_PAGE_RANGE",
            f"Choose pages between 1 and {document.page_count}.",
            action="page_range",
        )
    if body.last - body.first + 1 > limit:
        raise ApiError("INVALID_PAGE_RANGE", f"Choose {limit} pages or fewer.", action="page_range")
    source = {"document_id": str(document.id), "page_from": body.first, "page_to": body.last}
    return {"run_id": await limits.new_run(request, run.language, source)}


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


async def _verified_claims(session, run_id: uuid.UUID) -> list[dict]:
    """Only verified claims leave the backend. Rejections appear in the trace, without their text."""
    claims = (
        await session.scalars(
            select(Claim).where(Claim.run_id == run_id, Claim.status == "verified")
        )
    ).all()
    wanted = {clause_id for claim in claims for clause_id in claim.clause_ids}
    found = await session.scalars(select(Clause).where(Clause.id.in_(wanted))) if wanted else []
    clauses = {clause.id: clause for clause in found}
    return [
        {
            "id": str(claim.id),
            "field": claim.field,
            "text": claim.text,
            "quote": claim.quote,
            "clauses": [
                clause_ref(clause) for clause in (clauses[clause_id] for clause_id in claim.clause_ids)
            ],
        }
        for claim in sorted(claims, key=lambda c: min(clauses[i].ordinal for i in c.clause_ids))
    ]


def clause_ref(clause: Clause) -> dict:
    return {
        "id": str(clause.id),
        "ordinal": clause.ordinal,
        "page": clause.page,
        "bbox": clause.bbox,
        "extraction": clause.extraction,
    }


async def _queue_position(session, run: Run) -> int | None:
    """Slots go to the waiting runs in the order they arrived."""
    if run.status != "queued":
        return None
    ahead = await session.scalar(
        select(func.count())
        .select_from(Run)
        .where(Run.status == "queued", Run.created_at < run.created_at)
    )
    return ahead + 1


def _format(event: RunEvent) -> str:
    return f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(event.payload)}\n\n"


def document_view(document: Document) -> dict:
    return {
        "id": str(document.id),
        "sha256": document.sha256,
        "source_url": document.source_url,
        "fetch_method": document.fetch_method,
        "fetched_at": document.fetched_at.isoformat(),
        "page_count": document.page_count,
        "is_scanned": document.is_scanned,
        "title": document.title,
        "issuing_authority": document.issuing_authority,
        "issue_date": document.issue_date.isoformat() if document.issue_date else None,
    }


def _not_found() -> ApiError:
    return ApiError("RUN_NOT_FOUND", "That run wasn't found.", status=404, action="restart")
