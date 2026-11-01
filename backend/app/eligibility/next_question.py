from collections import Counter
from typing import Any

from app.eligibility.interpreter import CompiledRule, Tri, ev, missing_fields

MAX_QUESTIONS = 8


def next_field(rules: list[CompiledRule], profile: dict[str, Any]) -> str | None:
    """The field that could settle the most undecided rules."""
    if len(profile) >= MAX_QUESTIONS:
        return None
    undecided = [rule for rule in rules if ev(rule.ast, profile) is Tri.UNKNOWN]
    counts = Counter(field for rule in undecided for field in set(missing_fields(rule.ast, profile)))
    if not counts:
        return None
    # Ties go by name, so a resumed run asks the same question it would have asked anyway.
    return min(counts, key=lambda field: (-counts[field], field))
