import re
import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.api.errors import ApiError
from app.db.models import Rule, Run
from app.eligibility.fields import FIELDS
from app.providers.budget import Budget, BudgetExhausted
from app.providers.errors import ProviderUnavailable
from app.voice.answers import ParsedAnswer, answer_prompt, checked_value, quick_parse

router = APIRouter(prefix="/v1")

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MIN_LANGUAGE_PROBABILITY = 0.3
AUDIO_TYPES = ("audio/", "video/webm", "video/mp4")
_AUDIO_NAME = re.compile(r"[0-9a-f]{64}\.mp3")


@router.get("/audio/{name}")
async def get_audio(name: str, request: Request) -> Response:
    if not _AUDIO_NAME.fullmatch(name):
        raise ApiError("AUDIO_NOT_FOUND", "That audio wasn't found.", status=404)
    storage = request.app.state.services.deps.storage
    try:
        content = await storage.get(f"audio/{name}")
    except Exception as exc:
        raise ApiError("AUDIO_NOT_FOUND", "That audio wasn't found.", status=404) from exc
    # The name is a hash of the text and voice, so its content can never change.
    return Response(
        content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/runs/{run_id}/stt")
async def speech_to_answer(run_id: uuid.UUID, request: Request) -> dict:
    """The transcript and its reading, for the citizen to confirm. Nothing here is saved."""
    deps = request.app.state.services.deps
    form = await request.form()
    audio, field_name = form.get("audio"), form.get("field")
    if not isinstance(audio, UploadFile) or not isinstance(field_name, str):
        raise ApiError("INVALID_REQUEST", "Send a recording and the question it answers.")
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if not content_type.startswith(AUDIO_TYPES):
        raise ApiError("INVALID_AUDIO", "That recording format isn't supported.", action="type")
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES:
        raise ApiError("AUDIO_TOO_LARGE", "That recording is too long.", status=413, action="reask")

    async with deps.sessions() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise ApiError("RUN_NOT_FOUND", "That run wasn't found.", status=404, action="restart")
        if run.status != "waiting_input":
            raise ApiError("NOT_WAITING_FOR_INPUT", "This run isn't waiting for an answer.", status=409)
        required = await session.scalars(select(Rule.fields_required).where(Rule.run_id == run_id))
        allowed = {name for fields in required for name in fields}
    if field_name not in FIELDS or field_name not in allowed:
        raise ApiError("INVALID_ANSWER", "This document doesn't ask about that.")

    try:
        transcript, language_probability = await deps.gateway.sarvam.stt(content, content_type)
    except ProviderUnavailable as exc:
        raise ApiError(
            "SPEECH_UNAVAILABLE", "We can't hear answers right now. Please type it.", status=503, action="type"
        ) from exc
    unclear = language_probability is not None and language_probability < MIN_LANGUAGE_PROBABILITY
    if not transcript or unclear:
        return {"transcript": "", "parsed": None, "confidence": 0.0}

    field = FIELDS[field_name]
    value = checked_value(field, quick_parse(field, transcript))
    if value is not None:
        return {"transcript": transcript, "parsed": value, "confidence": 1.0}

    budget = Budget(deps.sessions, deps.events, str(run_id), deps.settings.max_llm_calls)
    try:
        result = await deps.gateway.structured(
            "answer", answer_prompt(field, transcript), ParsedAnswer, budget
        )
    except (ProviderUnavailable, BudgetExhausted):
        # They can still see what was heard, and type it.
        return {"transcript": transcript, "parsed": None, "confidence": 0.0}
    value = checked_value(field, result.value)
    return {
        "transcript": transcript,
        "parsed": value,
        "confidence": result.confidence if value is not None else 0.0,
    }
