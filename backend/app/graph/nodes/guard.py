import uuid

from sqlalchemy import exists, select, update

from app.db.models import Sentence
from app.graph.deps import Deps
from app.graph.state import RunState
from app.providers.budget import Budget, BudgetExhausted
from app.providers.errors import ProviderUnavailable
from app.voice.guard import MeaningResult, meaning_prompt, numbers_match

MAX_ATTEMPTS = 2
MEANING_BATCH = 8


async def needs_translation(state: RunState, deps: Deps) -> bool:
    async with deps.sessions() as session:
        return bool(
            await session.scalar(
                select(
                    exists().where(
                        Sentence.run_id == uuid.UUID(state["run_id"]),
                        Sentence.language == state["language"],
                        Sentence.guard_status == "pending",
                    )
                )
            )
        )


async def _meaning_failures(
    run_id: str, sentences: list[Sentence], deps: Deps
) -> dict[uuid.UUID, str]:
    """Checked in batches, so a 20 sentence script costs 3 calls and not 20."""
    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    failures: dict[uuid.UUID, str] = {}
    for start in range(0, len(sentences), MEANING_BATCH):
        batch = sentences[start : start + MEANING_BATCH]
        prompt = meaning_prompt([(s.source_text, s.translated_text) for s in batch])
        try:
            result = await deps.gateway.structured("meaning", prompt, MeaningResult, budget)
        except (ProviderUnavailable, BudgetExhausted):
            # A meaning nobody could check isn't safe to read aloud.
            failures |= {sentence.id: "MEANING_UNCHECKED" for sentence in batch}
            continue
        labels = {verdict.index: verdict.label for verdict in result.verdicts}
        for index, sentence in enumerate(batch):
            label = labels.get(index)
            if label is None:
                failures[sentence.id] = "MEANING_UNCHECKED"
            elif label == "CHANGED":
                failures[sentence.id] = "MEANING_CHANGED"
    return failures


async def guard(state: RunState, deps: Deps) -> dict:
    run_id = state["run_id"]
    async with deps.sessions() as session:
        sentences = (
            await session.scalars(
                select(Sentence)
                .where(
                    Sentence.run_id == uuid.UUID(run_id),
                    Sentence.language == state["language"],
                    Sentence.guard_status == "pending",
                )
                .order_by(Sentence.ordinal)
            )
        ).all()

    failures: dict[uuid.UUID, str] = {}
    for sentence in sentences:
        if sentence.translated_text is None:
            failures[sentence.id] = "NOT_TRANSLATED"
        elif not numbers_match(sentence.source_text, sentence.translated_text):
            failures[sentence.id] = "NUMBER_CHANGED"
    # Only what passed the free check goes on to the paid one.
    unchecked = [s for s in sentences if s.id not in failures]
    if unchecked:
        failures |= await _meaning_failures(run_id, unchecked, deps)

    attempts = dict(state.get("guard_attempts", {}))
    for sentence in sentences:
        reason = failures.get(sentence.id)
        key = str(sentence.id)
        if reason is None:
            values = {"guard_status": "passed"}
        else:
            attempts[key] = attempts.get(key, 0) + 1
            # With nothing to check it against, or no provider left, another try won't help.
            final = attempts[key] >= MAX_ATTEMPTS or reason == "MEANING_UNCHECKED"
            values = {
                "guard_status": "flagged" if final else "pending",
                "translated_text": sentence.translated_text if final else None,
            }
            await deps.events.emit(
                run_id,
                "guard_failed",
                {"sentence_id": key, "reason": reason, "attempt": attempts[key]},
            )
            if not final:
                await deps.events.emit(run_id, "retry", {"reason": reason, "attempt": attempts[key]})
        async with deps.sessions() as session:
            await session.execute(update(Sentence).where(Sentence.id == sentence.id).values(**values))
            await session.commit()
    return {"guard_attempts": attempts}
