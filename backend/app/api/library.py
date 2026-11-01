import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api import limits
from app.api.documents import LANGUAGES
from app.api.errors import ApiError
from app.api.runs import document_view
from app.db.models import Document

router = APIRouter(prefix="/v1")


class LibraryRunRequest(BaseModel):
    language: str


@router.get("/library")
async def list_library(request: Request) -> dict:
    services = request.app.state.services
    async with services.deps.sessions() as session:
        documents = await session.scalars(
            select(Document).where(Document.in_library).order_by(Document.fetched_at.desc())
        )
        return {"documents": [document_view(document) for document in documents]}


@router.post("/library/{document_id}/runs", status_code=202)
async def create_library_run(
    document_id: uuid.UUID, body: LibraryRunRequest, request: Request
) -> dict:
    services = request.app.state.services
    if body.language not in LANGUAGES:
        raise ApiError("INVALID_LANGUAGE", "Choose a supported language.")
    source = {"document_id": str(document_id)}
    async with services.deps.sessions() as session:
        document = await session.get(Document, document_id)
        if document is None or not document.in_library:
            raise ApiError("DOCUMENT_NOT_FOUND", "That document wasn't found.", status=404)
    return {"run_id": await limits.new_run(request, body.language, source)}
