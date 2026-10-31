import asyncio
import logging
import uuid

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clause, DocumentPage
from app.documents.normalize import detect_language, normalize
from app.documents.segment import find_furniture, segment_page
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState
from app.providers.gateway import EMBED_BATCH, ProviderUnavailable

log = logging.getLogger(__name__)

EMBED_TIMEOUT_S = 60


async def segment(state: RunState, deps: Deps) -> dict:
    """Turn pages into clauses, keeping existing ones so older runs' citations stay valid."""
    document_id = uuid.UUID(state["document_id"])
    async with deps.sessions() as session:
        # A second run of this document waits here, then finds the work already done.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": str(document_id)}
        )
        pages = (
            await session.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == document_id)
                .order_by(DocumentPage.page)
            )
        ).all()
        usable = [page for page in pages if page.status == "done"]
        failed_pages = [page.page for page in pages if page.status == "failed"]
        pending = [page for page in usable if not page.segmented]

        if pending:
            furniture = find_furniture([page.data for page in usable])
            ordinal = await session.scalar(
                select(func.coalesce(func.max(Clause.ordinal), 0)).where(
                    Clause.document_id == document_id
                )
            )
            rows = []
            for page in pending:
                for draft in segment_page(page.page, page.data, furniture, page.extraction):
                    ordinal += 1
                    rows.append(
                        {
                            "document_id": document_id,
                            "ordinal": ordinal,
                            "page": draft.page,
                            "bbox": draft.bbox,
                            "text": draft.text,
                            "norm_text": normalize(draft.text),
                            "lang": detect_language(draft.text),
                            "kind": draft.kind,
                            "extraction": draft.extraction,
                        }
                    )
            if rows:
                await session.execute(insert(Clause), rows)
                await _renumber(session, document_id)
            await session.execute(
                update(DocumentPage)
                .where(
                    DocumentPage.document_id == document_id,
                    DocumentPage.page.in_([page.page for page in pending]),
                )
                .values(segmented=True)
            )
        total = await session.scalar(
            select(func.count()).select_from(Clause).where(Clause.document_id == document_id)
        )
        await session.commit()

    if not total:
        if failed_pages:
            raise RunFailed(
                "PROVIDERS_UNAVAILABLE", "We couldn't read this document just now.", action="retry"
            )
        raise RunFailed(
            "NO_READABLE_TEXT", "We couldn't find any text in this document.", action="upload"
        )

    # Before embedding, because the clauses can be read now and rate limits can make embedding slow.
    await deps.events.emit(
        state["run_id"], "segment_done", {"clauses": total, "failed_pages": failed_pages}
    )
    embedded = await _embed_missing(document_id, deps)
    await deps.events.emit(state["run_id"], "embeddings_done", {"embedded": embedded})
    return {"partial": True} if failed_pages else {}


async def _renumber(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Keep ordinals in reading order when a retry recovers an earlier page.

    Citations store clause ids, so they survive this. Going through negative numbers
    keeps the unique constraint on (document_id, ordinal) satisfied at every row.
    """
    await session.execute(
        text(
            "UPDATE clauses c SET ordinal = -r.position FROM ("
            "  SELECT id, row_number() OVER (ORDER BY page, ordinal) AS position"
            "  FROM clauses WHERE document_id = :id"
            ") r WHERE c.id = r.id"
        ),
        {"id": document_id},
    )
    await session.execute(
        text("UPDATE clauses SET ordinal = -ordinal WHERE document_id = :id"),
        {"id": document_id},
    )


async def _embed_missing(document_id: uuid.UUID, deps: Deps) -> bool:
    """Embeddings only help retrieval, so a failure here leaves them for the next run."""
    async with deps.sessions() as session:
        rows = (
            await session.execute(
                select(Clause.id, Clause.text).where(
                    Clause.document_id == document_id, Clause.embedding.is_(None)
                )
            )
        ).all()
    try:
        async with asyncio.timeout(EMBED_TIMEOUT_S):
            for start in range(0, len(rows), EMBED_BATCH):
                batch = rows[start : start + EMBED_BATCH]
                vectors = await deps.gateway.embed([row.text for row in batch])
                async with deps.sessions() as session:
                    await session.execute(
                        update(Clause),
                        [
                            {"id": row.id, "embedding": v}
                            for row, v in zip(batch, vectors, strict=True)
                        ],
                    )
                    await session.commit()
    except (ProviderUnavailable, TimeoutError) as exc:
        log.warning("Embedding failed for document %s: %s", document_id, exc)
        return False
    return True
