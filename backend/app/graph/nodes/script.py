import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.claims import numbers
from app.db.models import Claim, Sentence
from app.eligibility.interpreter import CANNOT_DETERMINE, DOES_NOT_MEET, MEETS, NEEDS_INFO
from app.graph.deps import Deps
from app.graph.state import RunState
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.gateway import ProviderUnavailable

MAX_SENTENCES = 20

# Fixed text, so no LLM can reword the outcome. Each cites the claims behind that outcome.
VERDICT_TEXT = {
    MEETS: ("You appear to meet the eligibility criteria this document states.", "met"),
    DOES_NOT_MEET: ("You do not appear to meet at least one criterion in this document.", "failed"),
    NEEDS_INFO: ("We need more details to tell whether you qualify under this document.", "unknown"),
    CANNOT_DETERMINE: ("We cannot tell from this document whether you qualify.", "unknown"),
}


class ScriptSentence(BaseModel):
    text: str = Field(max_length=220)
    claim_indexes: list[int] = Field(min_length=1)


class ScriptResult(BaseModel):
    sentences: list[ScriptSentence] = []


def sentence_problem(sentence: ScriptSentence, claims: list[Claim]) -> str | None:
    if not sentence.text.strip():
        return "it is empty"
    if any(not 0 <= index < len(claims) for index in sentence.claim_indexes):
        return "it cites a claim that doesn't exist"
    cited: set[str] = set()
    for index in sentence.claim_indexes:
        cited |= numbers.parse(claims[index].text)
    if not numbers.is_subset(numbers.parse(sentence.text), cited):
        return "it has a number that isn't in the claims it cites"
    return None


def _prompt(claims: list[Claim], feedback: str) -> str:
    items = "\n".join(
        f'<claim index="{index}" field="{claim.field}">{as_data(claim.text)}</claim>'
        for index, claim in enumerate(claims)
    )
    return (
        load("script")
        .replace("{max_sentences}", str(MAX_SENTENCES))
        .replace("{feedback}", feedback)
        .replace("{claims}", items)
    )


async def _write(
    run_id: str, claims: list[Claim], deps: Deps
) -> tuple[list[tuple[str, list[uuid.UUID]]], bool]:
    """Valid sentences with their claim IDs, and whether the provider let us finish."""
    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    best: list[ScriptSentence] = []
    feedback = ""
    for attempt in (1, 2):
        try:
            result = await deps.gateway.structured("script", _prompt(claims, feedback), ScriptResult, budget)
        except (ProviderUnavailable, BudgetExhausted):
            return _resolved(best, claims), False
        valid = []
        problems = []
        for sentence in result.sentences:
            problem = sentence_problem(sentence, claims)
            if problem:
                problems.append(f"- {as_data(sentence.text)!r} was removed because {problem}.")
            else:
                valid.append(sentence)
        if len(valid) > len(best):
            best = valid
        if not problems or attempt == 2:
            break
        await deps.events.emit(run_id, "retry", {"reason": "SCRIPT_INVALID", "attempt": attempt})
        feedback = "\nYour last attempt broke these rules. Write the script again:\n" + "\n".join(problems) + "\n"
    return _resolved(best, claims), True


def _resolved(sentences: list[ScriptSentence], claims: list[Claim]) -> list[tuple[str, list[uuid.UUID]]]:
    return [
        (s.text.strip(), [claims[index].id for index in dict.fromkeys(s.claim_indexes)])
        for s in sentences[:MAX_SENTENCES]
    ]


async def script(state: RunState, deps: Deps) -> dict:
    run_id = state["run_id"]
    run_uuid = uuid.UUID(run_id)
    language = state["language"]
    async with deps.sessions() as session:
        existing = (
            await session.scalars(
                select(Sentence.id).where(Sentence.run_id == run_uuid, Sentence.language == language)
            )
        ).all()
        if existing:
            return {"sentence_ids": [str(sentence_id) for sentence_id in existing]}
        claims = (
            await session.scalars(
                select(Claim)
                .where(Claim.run_id == run_uuid, Claim.status == "verified")
                .order_by(Claim.id)
            )
        ).all()

    lines: list[tuple[str, list[uuid.UUID]]] = []
    complete = True
    verdict = state.get("verdict")
    if verdict:
        text, group = VERDICT_TEXT[verdict["outcome"]]
        # With no eligibility claim there's nothing to cite. The UI still shows the outcome.
        if verdict[group]:
            lines.append((text, [uuid.UUID(claim_id) for claim_id in verdict[group]]))
    if claims:
        written, complete = await _write(run_id, claims, deps)
        lines += written

    async with deps.sessions() as session:
        sentences = [
            Sentence(
                run_id=run_uuid,
                ordinal=ordinal,
                language=language,
                source_text=text,
                claim_ids=claim_ids,
                guard_status="pending",
            )
            for ordinal, (text, claim_ids) in enumerate(lines)
        ]
        session.add_all(sentences)
        await session.flush()
        sentence_ids = [str(sentence.id) for sentence in sentences]
        await session.commit()
    await deps.events.emit(run_id, "script_ready", {"sentences": len(sentence_ids)})
    update: dict = {"sentence_ids": sentence_ids}
    if not complete:
        update["partial"] = True
    return update
