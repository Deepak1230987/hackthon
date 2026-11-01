import asyncio
import logging
import uuid

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from starlette.datastructures import UploadFile

from app.api import limits
from app.api.documents import LANGUAGES
from app.api.errors import ApiError
from app.api.runs import clause_ref
from app.api.voice import read_recording, use_stt_allowance
from app.claims.schemas import MAX_CLAIM_CHARS, MAX_QUOTE_CHARS, EntailmentResult
from app.claims.verifier import CitedClause, check_claim, entailment_prompt
from app.db.models import Clause, Document, Run
from app.documents.pages import in_page_range
from app.graph.deps import Deps
from app.graph.nodes.tts import audio_path
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.errors import ProviderUnavailable
from app.voice.guard import MeaningResult, meaning_prompt, numbers_match
from app.voice.translate import TranslationResult, translation_prompt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

MAX_QUESTION_CHARS = 500
TOP_CLAUSES = 12
# Used when retrieval isn't available, so that a failed embedding doesn't lose the answer.
FALLBACK_CLAUSES = 60
RETRIEVE_TIMEOUT_S = 20
# The answer, entailment, a translation and its check, each of which may need one repair.
CALLS_PER_QUESTION = 8
ANSWERABLE = ("completed", "partial")

ABSTENTION = "This document does not say."
# Fixed, so the most common honest answer costs no call and never varies.
ABSTENTIONS = {
    "en": ABSTENTION,
    "hi": "यह दस्तावेज़ इस बारे में नहीं बताता।",
    "mr": "या दस्तऐवजात याबद्दल सांगितलेले नाही.",
    "bn": "এই নথিতে এ বিষয়ে বলা নেই।",
}


class AskRequest(BaseModel):
    question: str
    language: str | None = None


class GroundedAnswer(BaseModel):
    answer: str | None = Field(default=None, max_length=MAX_CLAIM_CHARS)
    clause_ordinals: list[int] = Field(default=[], max_length=3)
    quote: str | None = Field(default=None, max_length=MAX_QUOTE_CHARS)


async def _answerable_run(run_id: uuid.UUID, deps: Deps) -> Run:
    async with deps.sessions() as session:
        run = await session.get(Run, run_id)
    if run is None:
        raise ApiError("RUN_NOT_FOUND", "That run wasn't found.", status=404, action="restart")
    if run.status not in ANSWERABLE or run.document_id is None:
        raise ApiError("RUN_NOT_FINISHED", "Questions open once the document has been explained.", status=409)
    return run


async def _retrieve(run: Run, question: str, deps: Deps) -> list[Clause]:
    scope = (Clause.document_id == run.document_id, in_page_range(Clause.page, run.source))
    try:
        async with asyncio.timeout(RETRIEVE_TIMEOUT_S):
            vector = (await deps.gateway.embed([question]))[0]
    except (ProviderUnavailable, TimeoutError) as exc:
        log.warning("Couldn't embed a question on run %s: %s", run.id, type(exc).__name__)
        vector = None
    async with deps.sessions() as session:
        found = []
        if vector is not None:
            found = (
                await session.scalars(
                    select(Clause)
                    .where(*scope, Clause.embedding.is_not(None))
                    .order_by(Clause.embedding.cosine_distance(vector))
                    .limit(TOP_CLAUSES)
                )
            ).all()
        if not found:
            found = (
                await session.scalars(
                    select(Clause).where(*scope).order_by(Clause.ordinal).limit(FALLBACK_CLAUSES)
                )
            ).all()
    return sorted(found, key=lambda clause: clause.ordinal)


async def _verified_answer(
    question: str, clauses: list[Clause], budget: Budget, deps: Deps
) -> tuple[str, list[Clause]] | None:
    """The answer and its clauses, or None if the document doesn't support one."""
    by_ordinal = {clause.ordinal: clause for clause in clauses}
    document = "\n".join(f"[{clause.ordinal}] {as_data(clause.text)}" for clause in clauses)
    prompt = (
        load("qa").replace("{question}", as_data(question)).replace("{clauses}", document)
    )
    result = await deps.gateway.structured("qa", prompt, GroundedAnswer, budget)
    if not result.answer or not result.answer.strip():
        return None

    # Any unknown ordinal leaves the answer citing nothing, which the verifier rejects.
    cited = (
        [by_ordinal[ordinal] for ordinal in result.clause_ordinals]
        if all(ordinal in by_ordinal for ordinal in result.clause_ordinals)
        else []
    )
    answer = result.answer.strip()
    if check_claim(
        answer, result.quote, [CitedClause(clause.norm_text, clause.extraction) for clause in cited]
    ):
        return None
    prompt = entailment_prompt([(answer, [clause.text for clause in cited])])
    verdicts = (await deps.gateway.structured("entail", prompt, EntailmentResult, budget)).verdicts
    # An answer the model skipped hasn't been shown to be supported.
    if not any(verdict.index == 0 and verdict.label == "ENTAILED" for verdict in verdicts):
        return None
    return answer, cited


async def _add_chars(run_id: uuid.UUID, chars: int, deps: Deps) -> None:
    async with deps.sessions() as session:
        await session.execute(
            update(Run).where(Run.id == run_id).values(sarvam_chars=Run.sarvam_chars + chars)
        )
        await session.commit()


async def _passes_guard(source: str, translated: str, budget: Budget, deps: Deps) -> bool:
    if not numbers_match(source, translated):
        return False
    prompt = meaning_prompt([(source, translated)])
    verdicts = (await deps.gateway.structured("meaning", prompt, MeaningResult, budget)).verdicts
    return any(verdict.index == 0 and verdict.label != "CHANGED" for verdict in verdicts)


async def _translated(run: Run, text: str, language: str, budget: Budget, deps: Deps) -> str | None:
    """A translation that passed the guard, or None, which means the citizen sees the English."""
    try:
        translated = await deps.gateway.sarvam.translate(text, language)
    except ProviderUnavailable:
        translated = None
    else:
        await _add_chars(run.id, len(text), deps)
    try:
        if translated and await _passes_guard(text, translated, budget, deps):
            return translated
        # Sarvam would repeat the same wording, so the second try is the LLM's.
        prompt = translation_prompt([text], language)
        result = await deps.gateway.structured("translate", prompt, TranslationResult, budget)
        translated = next((t.text.strip() for t in result.translations if t.index == 0), None)
        if translated and await _passes_guard(text, translated, budget, deps):
            return translated
    except (ProviderUnavailable, BudgetExhausted) as exc:
        log.warning("Couldn't check a translated answer on run %s: %s", run.id, type(exc).__name__)
    return None


async def _spoken(run: Run, text: str, language: str, deps: Deps) -> str | None:
    """Where the audio is, or None. The citizen still has the text, so this never fails the answer."""
    settings = deps.settings
    path = audio_path(settings.tts_model, settings.voice_for(language), language, text)
    try:
        # The name is a hash of the words, so a repeated answer isn't paid for twice.
        await deps.storage.get(path)
    except Exception:
        log.debug("No stored audio yet for %s", path)
    else:
        return path
    try:
        audio = await deps.gateway.sarvam.tts(text, language)
        await deps.storage.put(path, audio, "audio/mpeg")
    except (ProviderUnavailable, httpx.HTTPError) as exc:
        log.warning("Couldn't speak an answer on run %s: %s", run.id, type(exc).__name__)
        return None
    await _add_chars(run.id, len(text), deps)
    return path


@router.post("/runs/{run_id}/qa")
async def ask(run_id: uuid.UUID, body: AskRequest, request: Request) -> dict:
    """The question is never stored or logged, since it can hold personal details."""
    services = request.app.state.services
    deps, settings = services.deps, services.settings
    question = body.question.strip()
    if not question:
        raise ApiError("INVALID_QUESTION", "Type a question first.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ApiError("INVALID_QUESTION", f"Keep your question under {MAX_QUESTION_CHARS} characters.")
    if body.language is not None and body.language not in LANGUAGES:
        raise ApiError("INVALID_LANGUAGE", "Choose a supported language.")

    run = await _answerable_run(run_id, deps)
    language = body.language or run.language
    if not await limits.use_allowance(request, run_id, Run.qa_calls, settings.max_questions_per_run):
        raise ApiError(
            "QUESTION_LIMIT", "That's the most questions we can answer for this document.", status=429
        )

    # On top of what the explanation used, so a long document can't use up its questions.
    allowance = settings.max_llm_calls + settings.max_questions_per_run * CALLS_PER_QUESTION
    budget = Budget(deps.sessions, deps.events, str(run_id), allowance)
    try:
        clauses = await _retrieve(run, question, deps)
        verified = await _verified_answer(question, clauses, budget, deps) if clauses else None
    except (ProviderUnavailable, BudgetExhausted) as exc:
        # Not an abstention: nobody has found that the document doesn't say.
        raise ApiError(
            "QA_UNAVAILABLE", "We can't check answers right now. Try again soon.", status=503, action="retry"
        ) from exc

    async with deps.sessions() as session:
        document = await session.get(Document, run.document_id)

    if verified is None:
        text, english, cited, shown_language = ABSTENTIONS[language], ABSTENTION, [], language
    else:
        english, cited = verified
        translated = (
            None if language == "en" else await _translated(run, english, language, budget, deps)
        )
        text = translated or english
        shown_language = language if translated else "en"
    # An answer whose translation failed the guard isn't safe to read aloud.
    speakable = shown_language == language

    return {
        "answer": text,
        "answer_en": english,
        "language": shown_language,
        "abstained": verified is None,
        "citations": [clause_ref(clause) for clause in cited],
        "authority": document.issuing_authority if verified is None else None,
        "audio_path": await _spoken(run, text, language, deps) if speakable else None,
    }


@router.post("/runs/{run_id}/qa/stt")
async def question_from_speech(run_id: uuid.UUID, request: Request) -> dict:
    """What was heard, for the citizen to check before asking. Nothing here is saved."""
    deps = request.app.state.services.deps
    form = await request.form()
    audio = form.get("audio")
    if not isinstance(audio, UploadFile):
        raise ApiError("INVALID_REQUEST", "Send a recording of your question.")
    content, content_type = await read_recording(audio)
    run = await _answerable_run(run_id, deps)
    await use_stt_allowance(request, run_id)
    try:
        transcript, _ = await deps.gateway.sarvam.stt(content, content_type, run.language)
    except ProviderUnavailable as exc:
        raise ApiError(
            "SPEECH_UNAVAILABLE", "We can't hear questions right now. Please type it.", status=503, action="type"
        ) from exc
    return {"transcript": transcript}
