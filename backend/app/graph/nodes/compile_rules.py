import logging
import uuid

from pydantic import BaseModel, ValidationError
from sqlalchemy import exists, select

from app.db.models import Claim, Rule
from app.eligibility.ast import EXPR, Expr, Not, Or, Unevaluable, comparisons
from app.eligibility.fields import FIELDS, rule_problem
from app.graph.deps import Deps
from app.graph.state import RunState
from app.prompts import as_data, load
from app.providers.budget import Budget, BudgetExhausted
from app.providers.gateway import ProviderUnavailable

log = logging.getLogger(__name__)


class CompiledClaim(BaseModel):
    index: int
    # Gemini's response schema can't express a recursive union, so code validates this string.
    expr: str
    # Code applies the inversion. A model told to invert exclusions itself got one wrong on a real
    # scheme, and told a farmer with 1 hectare that "more than 2 hectares" ruled them out.
    excludes: bool = False
    alternative_group: str | None = None


class RulesResult(BaseModel):
    rules: list[CompiledClaim] = []


def _prompt(claims: list[Claim]) -> str:
    fields = "\n".join(
        f"- {field.name} ({field.type}"
        + (f": {', '.join(field.options)}" if field.options else "")
        + (f", in {field.unit}" if field.unit else "")
        + ")"
        for field in FIELDS.values()
        if field.type != "str"
    )
    items = "\n".join(
        f'<claim index="{index}">{as_data(claim.text)}</claim>' for index, claim in enumerate(claims)
    )
    return load("rules").replace("{fields}", fields).replace("{claims}", items)


def parse_rule(raw: str, claim_text: str, excludes: bool = False) -> Expr:
    """The compiled rule, or Unevaluable. A bad compile must never decide someone's eligibility."""
    try:
        expr = EXPR.validate_json(raw)
    except (ValidationError, ValueError, RecursionError):
        log.info("Rule did not parse")
        return Unevaluable(type="unevaluable", source_text=claim_text)
    problem = rule_problem(expr, claim_text)
    if problem:
        log.info("Rule rejected: %s", problem)
        return Unevaluable(type="unevaluable", source_text=claim_text)
    return Not(type="not", item=expr) if excludes else expr


def combine(claims: list[Claim], compiled: list[CompiledClaim]) -> list[Expr]:
    """One rule per claim. Alternatives each carry the whole "or", so each still cites its claim."""
    rules: dict[int, Expr] = {}
    groups: dict[str, list[int]] = {}
    for item in compiled:
        if 0 <= item.index < len(claims) and item.index not in rules:
            rules[item.index] = parse_rule(item.expr, claims[item.index].text, item.excludes)
            if item.alternative_group:
                groups.setdefault(item.alternative_group, []).append(item.index)

    final = [
        rules.get(index, Unevaluable(type="unevaluable", source_text=claim.text))
        for index, claim in enumerate(claims)
    ]
    for members in groups.values():
        if len(members) > 1:
            either = Or(type="or", items=[final[index] for index in members])
            for index in members:
                final[index] = either
    return final


async def compile_rules(state: RunState, deps: Deps) -> dict | None:
    run_id = state["run_id"]
    run_uuid = uuid.UUID(run_id)
    async with deps.sessions() as session:
        # A retried node mustn't pay for this twice, or leave two rules for one claim.
        if await session.scalar(select(exists().where(Rule.run_id == run_uuid))):
            return None
        claims = (
            await session.scalars(
                select(Claim)
                .where(
                    Claim.run_id == run_uuid,
                    Claim.field == "eligibility",
                    Claim.status == "verified",
                )
                .order_by(Claim.id)
            )
        ).all()

    update = None
    compiled: list[CompiledClaim] = []
    if claims:
        budget = Budget(deps.sessions, deps.events, run_id, deps.settings.max_llm_calls)
        try:
            result = await deps.gateway.structured("rules", _prompt(claims), RulesResult, budget)
            compiled = result.rules
        except (ProviderUnavailable, BudgetExhausted):
            update = {"partial": True}

    rules = combine(claims, compiled)
    async with deps.sessions() as session:
        session.add_all(
            Rule(
                run_id=run_uuid,
                claim_id=claim.id,
                ast=expr.model_dump(),
                fields_required=sorted({cmp.field for cmp in comparisons(expr)}),
            )
            for claim, expr in zip(claims, rules, strict=True)
        )
        await session.commit()
    await deps.events.emit(run_id, "rules_compiled", {"count": len(rules)})
    return update
