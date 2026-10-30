import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.api.errors import ApiError
from app.db.models import Document, Run

router = APIRouter(prefix="/v1")

LANGUAGES = {"hi", "bn", "mr", "en"}
CHUNK_BYTES = 1024 * 1024


@router.post("/documents", status_code=202)
async def create_document_run(request: Request) -> dict:
    services = request.app.state.services
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        # URL input arrives with the fetchers and SSRF guard in phase 2.
        raise ApiError(
            "URL_INPUT_UNAVAILABLE", "Link input isn't available yet.", action="upload"
        )

    form = await request.form()
    file, language = form.get("file"), form.get("language")
    if not isinstance(file, UploadFile):
        raise ApiError("INVALID_REQUEST", "Choose a PDF file to upload.", action="upload")
    if language not in LANGUAGES:
        raise ApiError("INVALID_LANGUAGE", "Choose a supported language.")

    path, sha256 = await _save_upload(file, services.settings)
    source = {"upload_path": str(path), "sha256": sha256}
    async with services.deps.sessions() as session:
        run = Run(language=language, status="queued", source=source)
        session.add(run)
        await session.commit()
        run_id = str(run.id)

    services.runner.start(run_id, language, source)
    return {"run_id": run_id}


@router.get("/documents/{document_id}/file")
async def get_document_file(document_id: uuid.UUID, request: Request) -> Response:
    services = request.app.state.services
    async with services.deps.sessions() as session:
        path = await session.scalar(
            select(Document.storage_path).where(Document.id == document_id)
        )
    if path is None:
        raise ApiError("DOCUMENT_NOT_FOUND", "That document wasn't found.", status=404)
    content = await services.deps.storage.get(path)
    return Response(content, media_type="application/pdf")


async def _save_upload(file: UploadFile, settings) -> tuple[Path, str]:
    limit = settings.max_pdf_mb * 1024 * 1024
    path = settings.upload_dir / f"{uuid.uuid4()}.pdf"
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > limit:
                    raise ApiError(
                        "FILE_TOO_LARGE",
                        f"The file is larger than {settings.max_pdf_mb} MB.",
                        status=413,
                        action="upload",
                    )
                digest.update(chunk)
                out.write(chunk)
    except ApiError:
        path.unlink(missing_ok=True)
        raise
    return path, digest.hexdigest()
