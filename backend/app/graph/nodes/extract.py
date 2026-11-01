import json
import uuid

from sqlalchemy import select, update

from app.claims.schemas import CLAIM_FIELDS, ExtractionResult, RepairResult
from app.db.models import Claim, Clause, Document
from app.documents.pages import in_page_range, page_range
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState, SourceRequest
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.gateway import ProviderUnavailable

FULL_TEXT_MAX_PAGES = 30
TOP_CLAUSES_PER_FIELD = 60
FIELD_QUERIES = {
    "benefit": "benefit amount financial assistance subsidy scholarship payment लाभ राशि सहायता",
    "eligibility": "who is eligible criteria income age category पात्रता आय सीमा",
    "document": "documents required certificate proof to apply आवश्यक दस्तावेज प्रमाण पत्र",
    "deadline": "last date deadline time limit within days अंतिम तिथि समय सीमा",
    "authority": "authority officer department contact helpline अधिकारी विभाग संपर्क",
    "obligation": "must shall required duty responsibility अनिवार्य दायित्व करना होगा",
    "penalty": "penalty punishment cancellation recovery action दंड कार्रवाई वसूली",
}


async def _document_clauses(document_id: uuid.UUID, deps: Deps, source: SourceRequest) -> list[Clause]:
    """Short documents go in whole. Long ones send what is closest to each field, plus headings."""
    scope = (Clause.document_id == document_id, in_page_range(Clause.page, source))
    window = page_range(source)
    async with deps.sessions() as session:
        document = await session.get(Document, document_id)
        everything = select(Clause).where(*scope).order_by(Clause.ordinal)
        pages = window[1] - window[0] + 1 if window else document.page_count
        if pages <= FULL_TEXT_MAX_PAGES:
            return (await session.scalars(everything)).all()

        chosen = {
            clause.id: clause
            for clause in await session.scalars(everything.where(Clause.kind == "heading"))
        }
        try:
            vectors = await deps.gateway.embed([FIELD_QUERIES[field] for field in CLAIM_FIELDS])
        except ProviderUnavailable:
            # Retrieval only narrows the input, so a failure here mustn't lose the document.
            for clause in await session.scalars(
                everything.limit(TOP_CLAUSES_PER_FIELD * len(CLAIM_FIELDS))
            ):
                chosen[clause.id] = clause
        else:
            for vector in vectors:
                nearest = await session.scalars(
                    select(Clause)
                    .where(*scope, Clause.embedding.is_not(None))
                    .order_by(Clause.embedding.cosine_distance(vector))
                    .limit(TOP_CLAUSES_PER_FIELD)
                )
                for clause in nearest:
                    chosen[clause.id] = clause
    return sorted(chosen.values(), key=lambda clause: clause.ordinal)


def _as_document(clauses: list[Clause]) -> str:
    return "\n".join(f"[{clause.ordinal}] {as_data(clause.text)}" for clause in clauses)


def _clause_ids(ordinals: list[int], by_ordinal: dict[int, uuid.UUID]) -> list[uuid.UUID]:
    # Any unknown ordinal leaves the claim citing nothing, which the verifier rejects.
    if any(ordinal not in by_ordinal for ordinal in ordinals):
        return []
    return [by_ordinal[ordinal] for ordinal in ordinals]


async def extract(state: RunState, deps: Deps) -> dict | None:
    run_id = state["run_id"]
    run_uuid = uuid.UUID(run_id)
    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    async with deps.sessions() as session:
        existing = (await session.scalars(select(Claim).where(Claim.run_id == run_uuid))).all()
    clauses = await _document_clauses(uuid.UUID(state["document_id"]), deps, state["source"])
    by_ordinal = {clause.ordinal: clause.id for clause in clauses}

    if existing:
        return await _repair(run_id, existing, clauses, by_ordinal, budget, deps)

    prompt = load("extract").replace("{document}", _as_document(clauses))
    try:
        result = await deps.gateway.structured("extract", prompt, ExtractionResult, budget)
    except (ProviderUnavailable, BudgetExhausted) as exc:
        raise RunFailed(
            "PROVIDERS_UNAVAILABLE", "We couldn't read this document just now.", action="retry"
        ) from exc

    rows = [
        Claim(
            run_id=run_uuid,
            field=candidate.field,
            text=candidate.text,
            clause_ids=_clause_ids(candidate.clause_ordinals, by_ordinal),
            quote=candidate.quote,
            status="pending",
        )
        for candidate in result.claims
    ]
    async with deps.sessions() as session:
        session.add_all(rows)
        await session.commit()
    for row in rows:
        await deps.events.emit(run_id, "claim_extracted", {"claim_id": str(row.id), "field": row.field})
    return None


async def _repair(
    run_id: str,
    existing: list[Claim],
    clauses: list[Clause],
    by_ordinal: dict[int, uuid.UUID],
    budget: Budget,
    deps: Deps,
) -> dict | None:
    """Send back only the rejected claims and why. A claim keeps its id when corrected."""
    failed = [c for c in existing if c.status == "pending" and c.failure_reason]
    if not failed:
        return None
    rejected = json.dumps(
        [
            {"index": index, "field": c.field, "text": c.text, "quote": c.quote, "failure": c.failure_reason}
            for index, c in enumerate(failed)
        ],
        ensure_ascii=False,
    )
    prompt = (
        load("repair").replace("{rejected}", as_data(rejected)).replace("{document}", _as_document(clauses))
    )
    try:
        result = await deps.gateway.structured("repair", prompt, RepairResult, budget)
    except (ProviderUnavailable, BudgetExhausted):
        # What is already verified still stands, so this run ends with less rather than failing.
        await _give_up(failed, deps)
        return {"partial": True}

    corrected = {item.index: item for item in result.claims if 0 <= item.index < len(failed)}
    async with deps.sessions() as session:
        for index, claim in enumerate(failed):
            item = corrected.get(index)
            values = (
                {
                    "text": item.text,
                    "quote": item.quote,
                    "clause_ids": _clause_ids(item.clause_ordinals, by_ordinal),
                    "failure_reason": None,
                }
                # The model withdrew it, which is the honest outcome when the document doesn't say.
                if item
                else {"status": "not_stated"}
            )
            await session.execute(update(Claim).where(Claim.id == claim.id).values(**values))
        await session.commit()
    for index, claim in enumerate(failed):
        if index in corrected:
            await deps.events.emit(run_id, "claim_extracted", {"claim_id": str(claim.id), "field": claim.field})
    return None


async def _give_up(claims: list[Claim], deps: Deps) -> None:
    async with deps.sessions() as session:
        await session.execute(
            update(Claim).where(Claim.id.in_([c.id for c in claims])).values(status="not_stated")
        )
        await session.commit()
