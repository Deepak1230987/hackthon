from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.eligibility.ast import And, Cmp, Expr, Not, Or, Unevaluable, comparisons

# Stored for a question the citizen skipped, so it stays unknown and isn't asked again.
DECLINED = "__declined__"

MEETS = "MEETS_STATED_CRITERIA"
DOES_NOT_MEET = "DOES_NOT_MEET"
NEEDS_INFO = "NEEDS_INFO"
CANNOT_DETERMINE = "CANNOT_DETERMINE"


class Tri(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CompiledRule:
    claim_id: str
    ast: Expr


@dataclass(frozen=True)
class Decision:
    """Outcomes and claim IDs only, because this goes into graph state. Never input values."""

    outcome: str
    met: list[str]
    failed: list[str]
    unknown: list[str]


def _tri(value: bool) -> Tri:
    return Tri.TRUE if value else Tri.FALSE


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _fold(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def compare(actual: Any, op: str, expected: Any) -> Tri:
    """UNKNOWN when the types don't fit, because a bad rule mustn't turn anyone away."""
    if op in ("in", "not_in"):
        if not isinstance(expected, list) or not isinstance(actual, str):
            return Tri.UNKNOWN
        found = _fold(actual) in map(_fold, expected)
        return _tri(found if op == "in" else not found)
    if op in ("eq", "ne"):
        same_kind = (
            (_is_number(actual) and _is_number(expected))
            or (isinstance(actual, bool) and isinstance(expected, bool))
            or (isinstance(actual, str) and isinstance(expected, str))
        )
        if not same_kind:
            return Tri.UNKNOWN
        equal = _fold(actual) == _fold(expected)
        return _tri(equal if op == "eq" else not equal)
    if not _is_number(actual) or not _is_number(expected):
        return Tri.UNKNOWN
    return _tri(
        {
            "lt": actual < expected,
            "lte": actual <= expected,
            "gt": actual > expected,
            "gte": actual >= expected,
        }[op]
    )


def ev(expr: Expr, profile: dict[str, Any]) -> Tri:
    match expr:
        case Cmp():
            if expr.field not in profile or profile[expr.field] == DECLINED:
                return Tri.UNKNOWN
            return compare(profile[expr.field], expr.op, expr.value)
        case Not():
            inner = ev(expr.item, profile)
            if inner is Tri.UNKNOWN:
                return Tri.UNKNOWN
            return Tri.FALSE if inner is Tri.TRUE else Tri.TRUE
        case And():
            values = [ev(item, profile) for item in expr.items]
            if Tri.FALSE in values:
                return Tri.FALSE
            return Tri.UNKNOWN if Tri.UNKNOWN in values else Tri.TRUE
        case Or():
            values = [ev(item, profile) for item in expr.items]
            if Tri.TRUE in values:
                return Tri.TRUE
            return Tri.UNKNOWN if Tri.UNKNOWN in values else Tri.FALSE
        case Unevaluable():
            return Tri.UNKNOWN


def missing_fields(expr: Expr, profile: dict[str, Any]) -> list[str]:
    return [cmp.field for cmp in comparisons(expr) if cmp.field not in profile]


def decide(rules: list[CompiledRule], profile: dict[str, Any]) -> Decision:
    results = [(rule, ev(rule.ast, profile)) for rule in rules]

    def having(value: Tri) -> list[str]:
        return [rule.claim_id for rule, result in results if result is value]

    met, failed, unknown = having(Tri.TRUE), having(Tri.FALSE), having(Tri.UNKNOWN)
    if failed:
        outcome = DOES_NOT_MEET
    elif any(missing_fields(rule.ast, profile) for rule, result in results if result is Tri.UNKNOWN):
        outcome = NEEDS_INFO
    elif unknown or not rules:
        # With no rules nothing was checked, so that must never read as passing.
        outcome = CANNOT_DETERMINE
    else:
        outcome = MEETS
    return Decision(outcome, met, failed, unknown)
