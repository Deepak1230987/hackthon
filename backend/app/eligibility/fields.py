from typing import Any, Literal

from pydantic import BaseModel

from app.claims import numbers
from app.eligibility.ast import Cmp, Expr, comparisons

STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
    "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]  # fmt: skip


class FieldDef(BaseModel):
    name: str
    type: Literal["int", "float", "bool", "enum", "str"]
    options: list[str] | None = None
    min: float | None = None
    max: float | None = None
    question_en: str
    unit: str | None = None


class InvalidAnswer(Exception):
    """The message names the rule that was broken. It never repeats the citizen's value."""


_REGISTRY = [
    FieldDef(name="age", type="int", min=0, max=120, unit="years", question_en="How old are you?"),
    FieldDef(
        name="gender",
        type="enum",
        options=["female", "male", "other"],
        question_en="What is your gender?",
    ),
    FieldDef(name="state", type="enum", options=STATES, question_en="Which state do you live in?"),
    FieldDef(name="district", type="str", question_en="Which district do you live in?"),
    FieldDef(
        name="annual_income_inr",
        type="float",
        min=0,
        max=1e12,
        unit="INR",
        question_en="What is your family's total income in a year, in rupees?",
    ),
    FieldDef(
        name="occupation",
        type="enum",
        options=[
            "farmer", "student", "government_employee", "salaried", "self_employed", "daily_wage",
            "homemaker", "retired", "unemployed", "other",
        ],  # fmt: skip
        question_en="What is your main occupation?",
    ),
    FieldDef(
        name="social_category",
        type="enum",
        options=["general", "obc", "sc", "st", "ews"],
        question_en="Which social category do you belong to?",
    ),
    FieldDef(
        name="land_holding_hectares",
        type="float",
        min=0,
        max=100_000,
        unit="hectares",
        question_en="How much land do you hold, in hectares?",
    ),
    FieldDef(
        name="business_turnover_inr",
        type="float",
        min=0,
        max=1e13,
        unit="INR",
        question_en="What is your business's turnover in a year, in rupees?",
    ),
    FieldDef(
        name="employee_count",
        type="int",
        min=0,
        max=10_000_000,
        question_en="How many people does your business employ?",
    ),
    FieldDef(name="is_bpl", type="bool", question_en="Is your family below the poverty line?"),
    FieldDef(name="is_student", type="bool", question_en="Are you currently a student?"),
    FieldDef(name="has_disability", type="bool", question_en="Do you have a disability?"),
]
FIELDS: dict[str, FieldDef] = {field.name: field for field in _REGISTRY}

_NUMERIC_OPS = {"eq", "ne", "lt", "lte", "gt", "gte"}
_TEXT_OPS = {"eq", "ne", "in", "not_in"}


def validate_answer(name: str, value: Any) -> int | float | bool | str:
    """The answer in the field's own type, or InvalidAnswer."""
    field = FIELDS[name]
    if field.type == "bool":
        if not isinstance(value, bool):
            raise InvalidAnswer("Answer yes or no.")
        return value
    if field.type in ("int", "float"):
        return _number(field, value)
    if not isinstance(value, str) or not value.strip():
        raise InvalidAnswer("Enter an answer.")
    if field.type == "enum":
        for option in field.options or []:
            if option.casefold() == value.strip().casefold():
                return option
        raise InvalidAnswer("Choose one of the options.")
    return value.strip()[:200]


def _number(field: FieldDef, value: Any) -> int | float:
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidAnswer("Enter a number.") from exc
    # Written this way round so that NaN fails too.
    if not (field.min <= number <= field.max):
        raise InvalidAnswer(f"Enter a number from {field.min:g} to {field.max:g}.")
    if field.type == "int":
        if number != int(number):
            raise InvalidAnswer("Enter a whole number.")
        return int(number)
    return number


def rule_problem(expr: Expr, claim_text: str) -> str | None:
    """Why a compiled rule can't be trusted, or None. The model's output is never taken on faith."""
    for cmp in comparisons(expr):
        problem = _comparison_problem(cmp, claim_text)
        if problem:
            return problem
    return None


def _comparison_problem(cmp: Cmp, claim_text: str) -> str | None:
    field = FIELDS.get(cmp.field)
    if field is None:
        return "UNKNOWN_FIELD"
    if field.type == "str":
        # Free text can't be matched reliably: a spelling difference would wrongly fail someone.
        return "FREE_TEXT_FIELD"
    if field.type == "bool":
        ok = cmp.op in ("eq", "ne") and isinstance(cmp.value, bool)
        return None if ok else "BAD_VALUE"
    if field.type == "enum":
        listed = isinstance(cmp.value, list)
        if (cmp.op in ("in", "not_in")) != listed or cmp.op not in _TEXT_OPS:
            return "BAD_VALUE"
        values = cmp.value if listed else [cmp.value]
        known = {option.casefold() for option in field.options or []}
        ok = values and all(isinstance(v, str) and v.casefold() in known for v in values)
        return None if ok else "BAD_VALUE"
    if cmp.op not in _NUMERIC_OPS or isinstance(cmp.value, bool | str | list):
        return "BAD_VALUE"
    # A threshold must be one the verified claim states, as with claims and their quotes.
    if not numbers.is_subset(numbers.parse(str(cmp.value)), numbers.parse(claim_text)):
        return "NUMBER_NOT_IN_CLAIM"
    return None
