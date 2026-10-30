import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.acquisition.validate import PdfRejected, validate_pdf
from app.db.models import Document, Run
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState


async def acquire(state: RunState, deps: Deps) -> dict:
    """Store an uploaded PDF and link it to the run. Safe to re-run after a restart."""
    run_id = state["run_id"]
    source = state["source"]
    sha256 = source["sha256"]
    path = Path(source["upload_path"])
    await deps.events.emit(run_id, "fetch_attempt", {"method": "upload"})

    async with deps.sessions() as session:
        document_id = await session.scalar(select(Document.id).where(Document.sha256 == sha256))

    if document_id is None:
        document_id = await _store(path, sha256, deps)

    async with deps.sessions() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(document_id=document_id))
        await session.commit()
    path.unlink(missing_ok=True)
    return {"document_id": str(document_id)}


async def _store(path: Path, sha256: str, deps: Deps):
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError as exc:
        raise RunFailed(
            "UPLOAD_LOST", "The uploaded file is no longer available.", action="upload"
        ) from exc

    try:
        info = await asyncio.to_thread(validate_pdf, content)
    except PdfRejected as exc:
        path.unlink(missing_ok=True)
        raise RunFailed(exc.code, exc.message, action="upload") from exc

    storage_path = f"pdfs/{sha256}.pdf"
    await deps.storage.put(storage_path, content, "application/pdf")

    statement = insert(Document).values(
        sha256=sha256,
        fetch_method="upload",
        fetched_at=datetime.now(UTC),
        storage_path=storage_path,
        page_count=info.page_count,
    )
    # Two runs can upload the same file at once; both end up with the one row.
    statement = statement.on_conflict_do_update(
        index_elements=[Document.sha256], set_={"storage_path": storage_path}
    ).returning(Document.id)
    async with deps.sessions() as session:
        document_id = (await session.execute(statement)).scalar_one()
        await session.commit()
    return document_id
