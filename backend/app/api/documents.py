import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.acquisition.ssrf import UrlRejected, check_url
from app.api import limits
from app.api.errors import ApiError
from app.db.models import Clause, Document, DocumentPage

router = APIRouter(prefix="/v1")

LANGUAGES = {"hi", "bn", "mr", "en"}
CHUNK_BYTES = 1024 * 1024


@router.post("/documents", status_code=202)
async def create_document_run(request: Request) -> dict:
    services = request.app.state.services
    await limits.check_run_limit(request)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        file, language = form.get("file"), form.get("language")
        if not isinstance(file, UploadFile):
            raise ApiError("INVALID_REQUEST", "Choose a PDF file to upload.", action="upload")
        _check_language(language)
        path, sha256 = await _save_upload(file, services.settings)
        source = {"upload_path": str(path), "sha256": sha256}
    else:
        try:
            body = await request.json()
            url, language = body["url"], body["language"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ApiError("INVALID_REQUEST", "Send a link and a language.") from exc
        _check_language(language)
        if not isinstance(url, str):
            raise ApiError("INVALID_URL", "That link isn't valid.")
        try:
            await check_url(url)
        except UrlRejected as exc:
            raise ApiError(exc.code, exc.message) from exc
        source = {"url": url}

    try:
        return {"run_id": await limits.new_run(request, language, source)}
    except ApiError:
        if "upload_path" in source:
            Path(source["upload_path"]).unlink(missing_ok=True)
        raise


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


@router.get("/documents/{document_id}/clauses")
async def get_document_clauses(document_id: uuid.UUID, request: Request) -> dict:
    services = request.app.state.services
    async with services.deps.sessions() as session:
        if await session.get(Document, document_id) is None:
            raise ApiError("DOCUMENT_NOT_FOUND", "That document wasn't found.", status=404)
        clauses = await session.scalars(
            select(Clause).where(Clause.document_id == document_id).order_by(Clause.ordinal)
        )
        failed = await session.scalars(
            select(DocumentPage.page)
            .where(DocumentPage.document_id == document_id, DocumentPage.status == "failed")
            .order_by(DocumentPage.page)
        )
        return {
            "clauses": [
                {
                    "id": str(clause.id),
                    "ordinal": clause.ordinal,
                    "page": clause.page,
                    "bbox": clause.bbox,
                    "text": clause.text,
                    "lang": clause.lang,
                    "kind": clause.kind,
                    "extraction": clause.extraction,
                }
                for clause in clauses
            ],
            "failed_pages": list(failed),
        }


def _check_language(language: object) -> None:
    # JSON can send a list here, which can't be looked up in a set.
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ApiError("INVALID_LANGUAGE", "Choose a supported language.")


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
