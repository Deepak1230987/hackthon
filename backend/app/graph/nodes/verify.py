import asyncio
import uuid

from sqlalchemy import exists, select, update

from app.claims.schemas import EntailmentResult
from app.claims.verifier import CitedClause, check_claim
from app.db.models import Claim, Clause
from app.graph.deps import Deps
from app.graph.state import RunState
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.gateway import ProviderUnavailable

MAX_RETRIES = 2
ENTAIL_BATCH = 8
ENTAIL_CONCURRENCY = 3


async def needs_repair(state: RunState, deps: Deps) -> bool:
    async with deps.sessions() as session:
        return bool(
            await session.scalar(
                select(
                    exists().where(
                        Claim.run_id == uuid.UUID(state["run_id"]),
                        Claim.status == "pending",
                        Claim.failure_reason.is_not(None),
                    )
                )
            )
        )


async def verify(state: RunState, deps: Deps) -> dict | None:
    """Code checks first, because no LLM can overrule them. Then entailment for what survives."""
    run_id = state["run_id"]
    async with deps.sessions() as session:
        claims = (
            await session.scalars(
                select(Claim).where(
                    Claim.run_id == uuid.UUID(run_id),
                    Claim.status == "pending",
                    Claim.failure_reason.is_(None),
                )
            )
        ).all()
        wanted = {clause_id for claim in claims for clause_id in claim.clause_ids}
        found = await session.scalars(select(Clause).where(Clause.id.in_(wanted))) if wanted else []
        clauses = {clause.id: clause for clause in found}

    survivors = []
    for claim in claims:
        cited = [
            CitedClause(clauses[clause_id].norm_text, clauses[clause_id].extraction)
            for clause_id in claim.clause_ids
        ]
        reason = check_claim(claim.text, claim.quote, cited)
        if reason:
            await _reject(run_id, claim, reason, deps)
        else:
            survivors.append(claim)

    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    semaphore = asyncio.Semaphore(ENTAIL_CONCURRENCY)

    async def judge(batch: list[Claim]) -> bool:
        async with semaphore:
            return await _judge_batch(run_id, batch, clauses, budget, deps)

    batches = [survivors[i : i + ENTAIL_BATCH] for i in range(0, len(survivors), ENTAIL_BATCH)]
    complete = await asyncio.gather(*(judge(batch) for batch in batches))
    return None if all(complete) else {"partial": True}


async def _judge_batch(
    run_id: str, batch: list[Claim], clauses: dict, budget: Budget, deps: Deps
) -> bool:
    items = "\n\n".join(
        f'<claim index="{index}">\n{as_data(claim.text)}\n</claim>\n<source index="{index}">\n'
        + "\n".join(as_data(clauses[clause_id].text) for clause_id in claim.clause_ids)
        + "\n</source>"
        for index, claim in enumerate(batch)
    )
    prompt = load("entail").replace("{claims}", items)
    try:
        result = await deps.gateway.structured("entail", prompt, EntailmentResult, budget)
    except (ProviderUnavailable, BudgetExhausted) as exc:
        # An unchecked claim must never be shown, so these stop here without a retry.
        reason = "BUDGET_EXHAUSTED" if isinstance(exc, BudgetExhausted) else "PROVIDERS_UNAVAILABLE"
        for claim in batch:
            await _reject(run_id, claim, reason, deps, final=True)
        return False

    labels = {verdict.index: verdict.label for verdict in result.verdicts}
    for index, claim in enumerate(batch):
        # A claim the model skipped hasn't been shown to be supported.
        label = labels.get(index, "NOT_ENTAILED")
        if label == "ENTAILED":
            async with deps.sessions() as session:
                await session.execute(
                    update(Claim).where(Claim.id == claim.id).values(status="verified")
                )
                await session.commit()
            await deps.events.emit(run_id, "claim_verified", {"claim_id": str(claim.id)})
        else:
            await _reject(run_id, claim, label, deps)
    return True


async def _reject(run_id: str, claim: Claim, reason: str, deps: Deps, final: bool = False) -> None:
    attempt = claim.attempts + 1
    give_up = final or attempt > MAX_RETRIES
    async with deps.sessions() as session:
        await session.execute(
            update(Claim)
            .where(Claim.id == claim.id)
            .values(
                attempts=attempt,
                failure_reason=reason,
                status="not_stated" if give_up else "pending",
            )
        )
        await session.commit()
    await deps.events.emit(
        run_id, "claim_rejected", {"claim_id": str(claim.id), "reason": reason, "attempt": attempt}
    )
    if not give_up:
        await deps.events.emit(run_id, "retry", {"reason": reason, "attempt": attempt})
