import pytest
from pydantic import ValidationError

from app.eligibility.ast import EXPR, And, Cmp, Not, Or, Unevaluable
from app.eligibility.fields import FIELDS, InvalidAnswer, rule_problem, validate_answer
from app.eligibility.interpreter import (
    CANNOT_DETERMINE,
    DECLINED,
    DOES_NOT_MEET,
    MEETS,
    NEEDS_INFO,
    CompiledRule,
    Tri,
    compare,
    decide,
    ev,
)
from app.eligibility.next_question import MAX_QUESTIONS, next_field
from app.profiles import store as store_module
from app.profiles.store import ProfileStore

T = Cmp(type="cmp", field="t", op="eq", value=True)
F = Cmp(type="cmp", field="f", op="eq", value=True)
U = Cmp(type="cmp", field="u", op="eq", value=True)
PROFILE = {"t": True, "f": False}


def income_below(limit=250000):
    return Cmp(type="cmp", field="annual_income_inr", op="lt", value=limit)


def adult():
    return Cmp(type="cmp", field="age", op="gte", value=18)


def rule(expr, claim_id="c1"):
    return CompiledRule(claim_id, expr)


@pytest.mark.parametrize(
    ("left", "right", "both", "either"),
    [
        (T, T, Tri.TRUE, Tri.TRUE),
        (T, F, Tri.FALSE, Tri.TRUE),
        (T, U, Tri.UNKNOWN, Tri.TRUE),
        (F, T, Tri.FALSE, Tri.TRUE),
        (F, F, Tri.FALSE, Tri.FALSE),
        (F, U, Tri.FALSE, Tri.UNKNOWN),
        (U, T, Tri.UNKNOWN, Tri.TRUE),
        (U, F, Tri.FALSE, Tri.UNKNOWN),
        (U, U, Tri.UNKNOWN, Tri.UNKNOWN),
    ],
)
def test_three_valued_truth_table(left, right, both, either):
    assert ev(And(type="and", items=[left, right]), PROFILE) is both
    assert ev(Or(type="or", items=[left, right]), PROFILE) is either


@pytest.mark.parametrize(("item", "result"), [(T, Tri.FALSE), (F, Tri.TRUE), (U, Tri.UNKNOWN)])
def test_not(item, result):
    assert ev(Not(type="not", item=item), PROFILE) is result


def test_unevaluable_is_always_unknown():
    assert ev(Unevaluable(type="unevaluable", source_text="x"), PROFILE) is Tri.UNKNOWN


def test_declined_stays_unknown():
    assert ev(income_below(), {"annual_income_inr": DECLINED}) is Tri.UNKNOWN


@pytest.mark.parametrize(
    ("actual", "op", "expected", "result"),
    [
        (17, "lt", 18, Tri.TRUE),
        (18, "lt", 18, Tri.FALSE),
        (18, "lte", 18, Tri.TRUE),
        (18, "gte", 18, Tri.TRUE),
        (19, "gt", 18, Tri.TRUE),
        (18, "eq", 18.0, Tri.TRUE),
        (18, "ne", 18, Tri.FALSE),
        ("SC", "eq", "sc", Tri.TRUE),
        ("sc", "in", ["SC", "ST"], Tri.TRUE),
        ("general", "not_in", ["sc", "st"], Tri.TRUE),
        (True, "eq", True, Tri.TRUE),
        (True, "eq", 1, Tri.UNKNOWN),
        ("18", "lt", 20, Tri.UNKNOWN),
        (True, "lt", 20, Tri.UNKNOWN),
        (18, "in", ["18"], Tri.UNKNOWN),
        ("sc", "in", "sc", Tri.UNKNOWN),
        ("sc", "eq", 5, Tri.UNKNOWN),
    ],
)
def test_compare(actual, op, expected, result):
    assert compare(actual, op, expected) is result


def test_any_failed_rule_decides_and_names_its_claim():
    decision = decide([rule(income_below(), "a"), rule(adult(), "b")], {"annual_income_inr": 900000})
    assert decision.outcome == DOES_NOT_MEET
    assert decision.failed == ["a"]
    assert decision.unknown == ["b"]


def test_all_true_meets():
    decision = decide([rule(adult())], {"age": 30})
    assert decision.outcome == MEETS
    assert decision.met == ["c1"]


def test_missing_answer_needs_info():
    assert decide([rule(adult())], {}).outcome == NEEDS_INFO


def test_only_unevaluable_cannot_be_determined():
    rules = [rule(Unevaluable(type="unevaluable", source_text="x"))]
    assert decide(rules, {}).outcome == CANNOT_DETERMINE


def test_declined_field_cannot_be_determined():
    assert decide([rule(adult())], {"age": DECLINED}).outcome == CANNOT_DETERMINE


def test_no_rules_never_reads_as_passing():
    assert decide([], {}).outcome == CANNOT_DETERMINE


def test_empty_group_is_rejected():
    with pytest.raises(ValidationError):
        EXPR.validate_python({"type": "and", "items": []})


def test_ast_round_trips_through_json():
    expr = And(type="and", items=[adult(), Not(type="not", item=income_below())])
    assert EXPR.validate_python(expr.model_dump()) == expr


def test_next_field_picks_the_most_useful():
    rules = [rule(adult()), rule(And(type="and", items=[adult(), income_below()]))]
    assert next_field(rules, {}) == "age"


def test_next_field_skips_decided_rules_and_declined_fields():
    either = Or(type="or", items=[adult(), income_below()])
    assert next_field([rule(either)], {"age": 30}) is None
    assert next_field([rule(either)], {"age": DECLINED}) == "annual_income_inr"
    assert next_field([rule(adult())], {"age": DECLINED}) is None


def test_next_field_counts_a_field_once_per_rule():
    twice = Or(type="or", items=[adult(), Cmp(type="cmp", field="age", op="lt", value=5)])
    assert next_field([rule(twice), rule(income_below()), rule(income_below())], {}) == "annual_income_inr"


def test_next_field_stops_at_the_question_limit():
    answered = {f"f{n}": 1 for n in range(MAX_QUESTIONS)}
    assert next_field([rule(adult())], answered) is None


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("age", 45, 45),
        ("age", "45", 45),
        ("age", 45.0, 45),
        ("annual_income_inr", 250000.5, 250000.5),
        ("is_bpl", True, True),
        ("gender", " Female ", "female"),
        ("state", "uttar pradesh", "Uttar Pradesh"),
    ],
)
def test_valid_answers(name, value, expected):
    assert validate_answer(name, value) == expected


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("age", 300),
        ("age", -1),
        ("age", 4.5),
        ("age", "old"),
        ("age", True),
        ("age", None),
        ("age", float("nan")),
        ("annual_income_inr", float("inf")),
        ("is_bpl", "yes"),
        ("gender", "unknown"),
        ("gender", ""),
        ("state", 5),
    ],
)
def test_invalid_answers(name, value):
    with pytest.raises(InvalidAnswer):
        validate_answer(name, value)


def test_invalid_answer_message_does_not_repeat_the_value():
    with pytest.raises(InvalidAnswer) as caught:
        validate_answer("age", 987)
    assert "987" not in str(caught.value)


def test_registry_numbers_all_have_ranges():
    for field in FIELDS.values():
        if field.type in ("int", "float"):
            assert field.min is not None and field.max is not None


@pytest.mark.parametrize(
    ("expr", "claim", "problem"),
    [
        (income_below(), "Income must be below Rs. 2,50,000.", None),
        (income_below(), "Income must be below 2.5 lakh.", None),
        (income_below(), "आय 2.5 लाख से कम होनी चाहिए", None),
        (adult(), "Applicants must be at least 18 years old.", None),
        (income_below(300000), "Income must be below Rs. 2,50,000.", "NUMBER_NOT_IN_CLAIM"),
        (adult(), "Applicants must be adults.", "NUMBER_NOT_IN_CLAIM"),
        (Cmp(type="cmp", field="caste_code", op="eq", value="x"), "x", "UNKNOWN_FIELD"),
        (Cmp(type="cmp", field="district", op="eq", value="Pune"), "Pune", "FREE_TEXT_FIELD"),
        (Cmp(type="cmp", field="is_bpl", op="eq", value=True), "BPL families.", None),
        (Cmp(type="cmp", field="is_bpl", op="lt", value=True), "BPL families.", "BAD_VALUE"),
        (Cmp(type="cmp", field="is_bpl", op="eq", value="yes"), "BPL families.", "BAD_VALUE"),
        (Cmp(type="cmp", field="social_category", op="in", value=["sc", "st"]), "SC and ST.", None),
        (Cmp(type="cmp", field="social_category", op="in", value="sc"), "SC.", "BAD_VALUE"),
        (Cmp(type="cmp", field="social_category", op="eq", value=["sc"]), "SC.", "BAD_VALUE"),
        (Cmp(type="cmp", field="social_category", op="in", value=[]), "SC.", "BAD_VALUE"),
        (Cmp(type="cmp", field="social_category", op="eq", value="dalit"), "x", "BAD_VALUE"),
        (Cmp(type="cmp", field="gender", op="lt", value="female"), "Women.", "BAD_VALUE"),
        (Cmp(type="cmp", field="age", op="in", value=["18"]), "18", "BAD_VALUE"),
        (Cmp(type="cmp", field="age", op="gte", value=True), "18", "BAD_VALUE"),
        (Cmp(type="cmp", field="age", op="gte", value="18"), "18", "BAD_VALUE"),
        (Unevaluable(type="unevaluable", source_text="x"), "x", None),
    ],
)
def test_rule_problem(expr, claim, problem):
    assert rule_problem(expr, claim) == problem


def test_rule_problem_looks_inside_groups():
    nested = Not(type="not", item=And(type="and", items=[adult(), income_below(5)]))
    assert rule_problem(nested, "At least 18 years.") == "NUMBER_NOT_IN_CLAIM"


def test_profile_merge_get_and_copy():
    store = ProfileStore(60)
    store.merge("r", {"age": 30})
    store.merge("r", {"is_bpl": True})
    profile = store.get("r")
    assert profile == {"age": 30, "is_bpl": True}
    profile["age"] = 99
    assert store.get("r")["age"] == 30
    assert store.get("other") == {}


def test_profile_expires_and_merge_refreshes(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(store_module.time, "monotonic", lambda: now[0])
    store = ProfileStore(60)
    store.merge("r", {"age": 30})
    now[0] = 150.0
    store.merge("r", {"is_bpl": True})
    now[0] = 200.0
    assert store.get("r") == {"age": 30, "is_bpl": True}
    now[0] = 210.0
    assert store.get("r") == {}
    store.purge_expired()
    assert store._entries == {}


def test_exclusion_is_inverted_by_code():
    # From a real run on the PM-Kisan FAQ, where a farmer with 1 hectare was told they didn't qualify.
    from app.eligibility.ast import Not
    from app.eligibility.interpreter import DOES_NOT_MEET, MEETS, CompiledRule, decide
    from app.graph.nodes.compile_rules import parse_rule

    raw = '{"type": "cmp", "field": "land_holding_hectares", "op": "gt", "value": 2}'
    text = "Any family owning more than 2 hectare of land will not receive any benefit."
    expr = parse_rule(raw, text, excludes=True)
    assert isinstance(expr, Not)
    rules = [CompiledRule("c", expr)]
    assert decide(rules, {"land_holding_hectares": 1}).outcome == MEETS
    assert decide(rules, {"land_holding_hectares": 2}).outcome == MEETS
    assert decide(rules, {"land_holding_hectares": 3}).outcome == DOES_NOT_MEET


def test_a_rule_that_does_not_parse_stays_unevaluable_when_excluding():
    from app.eligibility.ast import Unevaluable
    from app.graph.nodes.compile_rules import parse_rule

    assert isinstance(parse_rule("not json", "Some claim.", excludes=True), Unevaluable)


def test_one_long_quote_does_not_lose_the_whole_reply():
    # From the same run: a 752 character quote failed all 21 claims.
    from app.claims.schemas import ExtractionResult

    claim = {"field": "benefit", "text": "A fact.", "clause_ordinals": [1], "quote": "q" * 752}
    assert len(ExtractionResult.model_validate({"claims": [claim]}).claims) == 1
