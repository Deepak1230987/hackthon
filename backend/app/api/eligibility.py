import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from app.api.errors import ApiError
from app.db.models import Rule, Run, RunEvent, Sentence
from app.eligibility.fields import FIELDS, InvalidAnswer, validate_answer
from app.eligibility.interpreter import DECLINED

router = APIRouter()


class Answers(BaseModel):
    answers: dict[str, Any] = {}
    skip: list[str] = []


@router.post("/runs/{run_id}/answers")
async def post_answers(run_id: uuid.UUID, body: Answers, request: Request) -> dict:
    if not body.answers and not body.skip:
        raise ApiError("INVALID_REQUEST", "Send an answer, or skip the question.")
    services = request.app.state.services
    deps = services.deps
    async with deps.sessions() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise ApiError("RUN_NOT_FOUND", "That run wasn't found.", status=404, action="restart")
        required = await session.scalars(select(Rule.fields_required).where(Rule.run_id == run_id))
        allowed = {field for fields in required for field in fields}

    values = {field: DECLINED for field in body.skip}
    for field, value in body.answers.items():
        values[field] = _validated(field, value)
    unknown = sorted(field for field in values if field not in allowed)
    if unknown:
        raise ApiError(
            "INVALID_ANSWER", "This document doesn't ask about that.", details={"fields": unknown}
        )

    async with deps.sessions() as session:
        # Only one request can claim the pause, so a double tap can't resume the run twice.
        resumed = await session.scalar(
            update(Run)
            .where(Run.id == run_id, Run.status == "waiting_input")
            .values(status="queued")
            .returning(Run.id)
        )
        await session.commit()
    if resumed is None:
        raise ApiError("NOT_WAITING_FOR_INPUT", "This run isn't waiting for an answer.", status=409)

    deps.profiles.merge(str(run_id), values)
    services.runner.start(str(run_id), run.language, run.source)
    return {"status": "queued"}


def _validated(field: str, value: Any) -> Any:
    if field not in FIELDS:
        raise ApiError(
            "INVALID_ANSWER", "This document doesn't ask about that.", details={"fields": [field]}
        )
    try:
        return validate_answer(field, value)
    except InvalidAnswer as exc:
        # The citizen's value stays out of the response and so out of any log of it.
        raise ApiError(
            "INVALID_ANSWER", str(exc), action="reask", details={"fields": [field]}
        ) from exc


async def eligibility_view(session, run: Run, events: Sequence[RunEvent]) -> dict:
    """What the eligibility and audio panels need. Holds no citizen's answers."""
    question = None
    if run.status == "waiting_input":
        asked = next((e.payload["field"] for e in reversed(events) if e.type == "needs_input"), None)
        if asked in FIELDS:
            question = FIELDS[asked].model_dump()
    verdict = next((e.payload for e in reversed(events) if e.type == "verdict"), None)
    sentences = await session.scalars(
        select(Sentence).where(Sentence.run_id == run.id).order_by(Sentence.ordinal)
    )
    return {
        "question": question,
        "verdict": verdict,
        "sentences": [
            {
                "id": str(sentence.id),
                "ordinal": sentence.ordinal,
                "language": sentence.language,
                "source_text": sentence.source_text,
                "translated_text": sentence.translated_text,
                "claim_ids": [str(claim_id) for claim_id in sentence.claim_ids],
                "audio_path": sentence.audio_path,
                "guard_status": sentence.guard_status,
            }
            for sentence in sentences
        ],
    }
