import uuid
from datetime import date

from sqlalchemy import select

from app.claims.schemas import TriageResult
from app.db.models import Clause, Document
from app.graph.deps import Deps, RunFailed
from app.graph.state import RunState
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.gateway import ProviderUnavailable

SAMPLE_CLAUSES = 40


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


async def triage(state: RunState, deps: Deps) -> None:
    """Stop before spending on extraction if this isn't a policy document."""
    run_id = state["run_id"]
    document_id = uuid.UUID(state["document_id"])
    async with deps.sessions() as session:
        texts = await session.scalars(
            select(Clause.text)
            .where(Clause.document_id == document_id)
            .order_by(Clause.ordinal)
            .limit(SAMPLE_CLAUSES)
        )
        sample = "\n".join(as_data(text) for text in texts)

    budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
    prompt = load("triage").replace("{document}", sample)
    try:
        result = await deps.gateway.structured("triage", prompt, TriageResult, budget)
    except (ProviderUnavailable, BudgetExhausted) as exc:
        raise RunFailed(
            "PROVIDERS_UNAVAILABLE", "We couldn't read this document just now.", action="retry"
        ) from exc

    await deps.events.emit(run_id, "triage_result", {"is_policy": result.is_policy})
    if not result.is_policy:
        raise RunFailed(
            "NOT_A_POLICY",
            "This doesn't look like a government policy document, so we stopped here.",
            action="upload",
            details={"reason": result.reason},
        )

    async with deps.sessions() as session:
        document = await session.get(Document, document_id)
        # Never overwrite: a library title was chosen by a person who read the document.
        document.title = document.title or result.title
        document.issuing_authority = document.issuing_authority or result.issuing_authority
        document.issue_date = document.issue_date or _parse_date(result.issue_date)
        await session.commit()
