import uuid

from langgraph.types import interrupt
from sqlalchemy import select

from app.db.models import Rule
from app.eligibility.ast import EXPR
from app.eligibility.interpreter import NEEDS_INFO, CompiledRule, decide
from app.eligibility.next_question import next_field
from app.graph.deps import Deps
from app.graph.state import RunState


async def evaluate(state: RunState, deps: Deps) -> dict:
    """Pure code: no LLM decides eligibility. Pauses the run whenever an answer could settle it."""
    run_id = state["run_id"]
    async with deps.sessions() as session:
        stored = (
            await session.scalars(
                select(Rule).where(Rule.run_id == uuid.UUID(run_id)).order_by(Rule.claim_id)
            )
        ).all()
    rules = [CompiledRule(str(rule.claim_id), EXPR.validate_python(rule.ast)) for rule in stored]

    while True:
        # Read fresh each time: answers live here and never in the state or the interrupt.
        profile = deps.profiles.get(run_id)
        decision = decide(rules, profile)
        field = next_field(rules, profile) if decision.outcome == NEEDS_INFO else None
        if field is None:
            break
        # A resume reruns this node, and each earlier interrupt() returns at once. If a restart
        # lost the profile those earlier calls change nothing, so the same question is asked again.
        interrupt({"field": field})

    verdict = {
        "outcome": decision.outcome,
        "met": decision.met,
        "failed": decision.failed,
        "unknown": decision.unknown,
    }
    await deps.events.emit(run_id, "verdict", verdict)
    return {"verdict": verdict, "pending_fields": []}
