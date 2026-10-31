import asyncio
import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Document, DocumentPage
from app.documents.extract import extract_pages, render_page
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState
from app.providers.gateway import ProviderUnavailable

log = logging.getLogger(__name__)

OCR_CONCURRENCY = 5


async def parse(state: RunState, deps: Deps) -> None:
    """Read each page once. Pages already done, by this or any earlier run, are skipped."""
    run_id = state["run_id"]
    document_id = uuid.UUID(state["document_id"])
    async with deps.sessions() as session:
        document = await session.get(Document, document_id)
        done = set(
            await session.scalars(
                select(DocumentPage.page).where(
                    DocumentPage.document_id == document_id, DocumentPage.status == "done"
                )
            )
        )
    if document.page_count > deps.settings.max_pages:
        raise RunFailed(
            "DOC_TOO_LONG",
            f"This document has {document.page_count} pages. "
            f"The limit is {deps.settings.max_pages}.",
            action="page_range",
        )

    todo = [page for page in range(1, document.page_count + 1) if page not in done]
    if not todo:
        return
    content = await deps.storage.get(document.storage_path)
    extracted = await asyncio.to_thread(extract_pages, content, todo)

    for page in extracted:
        if page.data is not None:
            await _save_page(deps, document_id, page.page, "native", "done", page.data, None)

    needing_ocr = [page for page in extracted if page.data is None]
    semaphore = asyncio.Semaphore(OCR_CONCURRENCY)

    async def ocr_page(page) -> None:
        async with semaphore:
            await deps.events.emit(run_id, "page_ocr", {"page": page.page, "reason": page.ocr_reason})
            try:
                image = await asyncio.to_thread(render_page, content, page.page)
                items = await deps.gateway.vision_ocr(image)
            except ProviderUnavailable as exc:
                log.warning("OCR failed on page %s of run %s: %s", page.page, run_id, exc)
                await _save_page(deps, document_id, page.page, "ocr", "failed", {"items": []},
                                 page.ocr_reason)
                await deps.events.emit(
                    run_id, "page_ocr", {"page": page.page, "failed": True, "reason": str(exc)}
                )
                return
            await _save_page(deps, document_id, page.page, "ocr", "done", {"items": items},
                             page.ocr_reason)

    await asyncio.gather(*(ocr_page(page) for page in needing_ocr))

    async with deps.sessions() as session:
        # Count every OCR page, because a retry only reads the ones that failed before.
        ocr_pages = await session.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.document_id == document_id, DocumentPage.extraction == "ocr")
        )
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(is_scanned=ocr_pages * 2 > document.page_count)
        )
        await session.commit()


async def _save_page(
    deps: Deps,
    document_id: uuid.UUID,
    page: int,
    extraction: str,
    status: str,
    data: dict,
    reason: str | None,
) -> None:
    values = {"extraction": extraction, "status": status, "data": data, "ocr_reason": reason}
    statement = insert(DocumentPage).values(document_id=document_id, page=page, **values)
    statement = statement.on_conflict_do_update(
        index_elements=[DocumentPage.document_id, DocumentPage.page], set_=values
    )
    async with deps.sessions() as session:
        await session.execute(statement)
        await session.commit()
