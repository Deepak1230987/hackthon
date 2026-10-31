import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.acquisition import fetchers
from app.acquisition.validate import PdfRejected, validate_pdf
from app.db.models import Document, Run
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState


async def acquire(state: RunState, deps: Deps) -> dict:
    """Get the PDF and link it to the run. Safe to re-run after a restart."""
    run_id = state["run_id"]
    source = state["source"]
    async with deps.sessions() as session:
        run = await session.get(Run, uuid.UUID(run_id))
        document_id = run.document_id if run else None

    if document_id is None:
        if "document_id" in source:
            document_id = uuid.UUID(source["document_id"])
        elif "url" in source:
            document_id = await _from_url(run_id, source["url"], deps)
        else:
            document_id = await _from_upload(run_id, source, deps)
        async with deps.sessions() as session:
            await session.execute(
                update(Run).where(Run.id == uuid.UUID(run_id)).values(document_id=document_id)
            )
            await session.commit()

    if "upload_path" in source:
        Path(source["upload_path"]).unlink(missing_ok=True)
    return {"document_id": str(document_id)}


async def _from_upload(run_id: str, source: dict, deps: Deps) -> uuid.UUID:
    await deps.events.emit(run_id, "fetch_attempt", {"method": "upload"})
    sha256 = source["sha256"]
    existing = await _find(sha256, deps)
    if existing:
        return existing
    path = Path(source["upload_path"])
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError as exc:
        raise RunFailed(
            "UPLOAD_LOST", "The uploaded file is no longer available.", action="upload"
        ) from exc
    try:
        return await _store(content, sha256, "upload", None, deps)
    except RunFailed:
        path.unlink(missing_ok=True)
        raise


async def _from_url(run_id: str, url: str, deps: Deps) -> uuid.UUID:
    fetched = await _fetch(run_id, url, deps)
    content = fetched.content
    sha256 = hashlib.sha256(content).hexdigest()
    existing = await _find(sha256, deps)
    if existing is None:
        return await _store(content, sha256, fetched.method, fetched.url, deps)
    # The same file was uploaded earlier. Now we know where it officially lives, so record it.
    async with deps.sessions() as session:
        await session.execute(
            update(Document)
            .where(Document.id == existing, Document.source_url.is_(None))
            .values(source_url=fetched.url, fetch_method=fetched.method)
        )
        await session.commit()
    return existing


async def _fetch(run_id: str, url: str, deps: Deps) -> fetchers.Fetched:
    limit = deps.settings.max_pdf_mb * 1024 * 1024
    attempts: list[dict[str, str]] = []
    found_html = False
    for method, fetcher in (("http", fetchers.http_fetch), ("browser", fetchers.browser_fetch)):
        await deps.events.emit(run_id, "fetch_attempt", {"method": method})
        try:
            result = await fetcher(url, limit)
            if result.links and len(result.links) == 1:
                result = await fetcher(result.links[0]["url"], limit)
        except fetchers.FetchFailed as exc:
            # Another tier can't help with these, and mustn't fetch the same address or file.
            if exc.reason == "blocked":
                raise RunFailed(
                    "URL_BLOCKED", "That link points somewhere we can't fetch from.", action="upload"
                ) from exc
            if exc.reason == "too_large":
                raise RunFailed(
                    "FILE_TOO_LARGE",
                    f"The file is larger than {deps.settings.max_pdf_mb} MB.",
                    action="upload",
                ) from exc
            attempts.append({"method": method, "reason": exc.reason})
            found_html = found_html or exc.reason == "not_a_pdf"
            continue
        except TimeoutError:
            attempts.append({"method": method, "reason": "timeout"})
            continue
        if result.content:
            return result
        if result.links:
            raise RunFailed(
                "MULTIPLE_PDFS",
                "This page links to several PDFs. Choose the one you want.",
                action="choose_source",
                details={"options": result.links},
            )
        found_html = True
        attempts.append({"method": method, "reason": "no_pdf_on_page"})

    if found_html:
        raise RunFailed(
            "NOT_A_PDF",
            "That link doesn't lead to a PDF.",
            action="upload",
            details={"attempts": attempts},
        )
    raise RunFailed(
        "SOURCE_UNREACHABLE",
        "The site didn't respond. You can upload the PDF or pick one from the library.",
        action="upload",
        details={"attempts": attempts},
    )


async def _find(sha256: str, deps: Deps) -> uuid.UUID | None:
    async with deps.sessions() as session:
        return await session.scalar(select(Document.id).where(Document.sha256 == sha256))


async def _store(
    content: bytes, sha256: str, method: str, source_url: str | None, deps: Deps
) -> uuid.UUID:
    try:
        info = await asyncio.to_thread(validate_pdf, content)
    except PdfRejected as exc:
        raise RunFailed(exc.code, exc.message, action="upload") from exc

    storage_path = f"pdfs/{sha256}.pdf"
    await deps.storage.put(storage_path, content, "application/pdf")

    statement = insert(Document).values(
        sha256=sha256,
        source_url=source_url,
        fetch_method=method,
        fetched_at=datetime.now(UTC),
        storage_path=storage_path,
        page_count=info.page_count,
    )
    # Two runs can bring in the same file at once; both end up with the one row.
    statement = statement.on_conflict_do_update(
        index_elements=[Document.sha256], set_={"storage_path": storage_path}
    ).returning(Document.id)
    async with deps.sessions() as session:
        document_id = (await session.execute(statement)).scalar_one()
        await session.commit()
    return document_id
