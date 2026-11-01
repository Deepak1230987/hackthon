import asyncio
import logging
import uuid

from sqlalchemy import select, update

from app.db.models import Run, Sentence
from app.eligibility.interpreter import CANNOT_DETERMINE, DOES_NOT_MEET, MEETS, NEEDS_INFO
from app.graph.deps import Deps
from app.graph.nodes.script import VERDICT_TEXT
from app.graph.state import RunState
from app.providers.budget import Budget, BudgetExhausted
from app.providers.errors import ProviderUnavailable
from app.voice.translate import TranslationResult, translation_prompt

log = logging.getLogger(__name__)

SARVAM_CONCURRENCY = 3
LLM_BATCH = 10

# The verdict is fixed English, so its Hindi is fixed too. A translator chose a gender for the
# listener, and an outcome this important shouldn't vary between runs or spend a call.
FIXED_TRANSLATIONS = {
    "hi": {
        VERDICT_TEXT[MEETS][0]: "आप इस दस्तावेज़ की बताई गई शर्तें पूरी करते दिखते हैं।",
        VERDICT_TEXT[DOES_NOT_MEET][0]: "इस दस्तावेज़ की कम से कम एक शर्त पूरी होती नहीं दिखती।",
        VERDICT_TEXT[NEEDS_INFO][0]: "यह बताने के लिए कि आप पात्र हैं या नहीं, हमें और जानकारी चाहिए।",
        VERDICT_TEXT[CANNOT_DETERMINE][0]: "हम इस दस्तावेज़ से यह नहीं बता सकते कि आप पात्र हैं या नहीं।",
    },
    "mr": {
        VERDICT_TEXT[MEETS][0]: "या दस्तऐवजात सांगितलेल्या अटी तुम्ही पूर्ण करत असल्याचे दिसते.",
        VERDICT_TEXT[DOES_NOT_MEET][0]: "या दस्तऐवजातील किमान एक अट पूर्ण होत असल्याचे दिसत नाही.",
        VERDICT_TEXT[NEEDS_INFO][0]: "तुम्ही पात्र आहात की नाही हे सांगण्यासाठी आम्हाला आणखी माहिती हवी आहे.",
        VERDICT_TEXT[CANNOT_DETERMINE][0]: "तुम्ही पात्र आहात की नाही हे आम्ही या दस्तऐवजावरून सांगू शकत नाही.",
    },
}


async def _pending(state: RunState, deps: Deps) -> list[Sentence]:
    async with deps.sessions() as session:
        return (
            await session.scalars(
                select(Sentence)
                .where(
                    Sentence.run_id == uuid.UUID(state["run_id"]),
                    Sentence.language == state["language"],
                    Sentence.guard_status == "pending",
                    Sentence.translated_text.is_(None),
                )
                .order_by(Sentence.ordinal)
            )
        ).all()


async def _save(run_id: str, sentence: Sentence, text: str, translator: str, deps: Deps) -> None:
    async with deps.sessions() as session:
        await session.execute(
            update(Sentence)
            .where(Sentence.id == sentence.id)
            .values(translated_text=text, translator=translator)
        )
        await session.commit()
    await deps.events.emit(
        run_id, "sentence_translated", {"sentence_id": str(sentence.id), "translator": translator}
    )


async def _with_sarvam(
    run_id: str, sentences: list[Sentence], language: str, deps: Deps
) -> tuple[list[Sentence], str]:
    """Translate what Sarvam can. Returns what's left, and why."""
    sarvam = deps.gateway.sarvam
    semaphore = asyncio.Semaphore(SARVAM_CONCURRENCY)
    left: list[Sentence] = []
    reason = ""

    async def one(sentence: Sentence) -> None:
        nonlocal reason
        async with semaphore:
            try:
                text = await sarvam.translate(sentence.source_text, language)
            except ProviderUnavailable as exc:
                left.append(sentence)
                reason = str(exc)
                return
            await _add_chars(run_id, len(sentence.source_text), deps)
            await _save(run_id, sentence, text, "sarvam", deps)

    await asyncio.gather(*(one(sentence) for sentence in sentences))
    return sorted(left, key=lambda s: s.ordinal), reason


async def _add_chars(run_id: str, chars: int, deps: Deps) -> None:
    async with deps.sessions() as session:
        await session.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(sarvam_chars=Run.sarvam_chars + chars)
        )
        await session.commit()


async def _with_llm(run_id: str, sentences: list[Sentence], language: str, deps: Deps) -> None:
    """Sentences left untranslated here are flagged by the guard, and shown in English."""
    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    for start in range(0, len(sentences), LLM_BATCH):
        batch = sentences[start : start + LLM_BATCH]
        prompt = translation_prompt([s.source_text for s in batch], language)
        try:
            result = await deps.gateway.structured("translate", prompt, TranslationResult, budget)
        except (ProviderUnavailable, BudgetExhausted) as exc:
            log.warning("LLM translation failed on run %s: %s", run_id, exc)
            return
        for item in result.translations:
            if 0 <= item.index < len(batch) and item.text.strip():
                await _save(run_id, batch[item.index], item.text.strip(), "llm", deps)


async def translate(state: RunState, deps: Deps) -> None:
    run_id = state["run_id"]
    language = state["language"]
    sentences = await _pending(state, deps)
    if not sentences:
        return
    if language == "en":
        async with deps.sessions() as session:
            for sentence in sentences:
                await session.execute(
                    update(Sentence)
                    .where(Sentence.id == sentence.id)
                    .values(translated_text=sentence.source_text, guard_status="passed")
                )
            await session.commit()
        return

    fixed = FIXED_TRANSLATIONS.get(language, {})
    for sentence in [s for s in sentences if s.source_text in fixed]:
        await _save(run_id, sentence, fixed[sentence.source_text], "fixed", deps)
    sentences = [s for s in sentences if s.source_text not in fixed]

    attempts = state.get("guard_attempts", {})
    # Sarvam would repeat the same wording, so a sentence the guard failed goes to the LLM.
    retries = [s for s in sentences if attempts.get(str(s.id))]
    first_tries = [s for s in sentences if not attempts.get(str(s.id))]
    left, reason = await _with_sarvam(run_id, first_tries, language, deps)
    if left:
        await deps.events.emit(run_id, "failover", {"from": "sarvam", "to": "the AI model", "reason": reason})
    if left or retries:
        await _with_llm(run_id, sorted(left + retries, key=lambda s: s.ordinal), language, deps)
