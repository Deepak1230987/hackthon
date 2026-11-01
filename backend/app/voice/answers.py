import re
from typing import Any

from pydantic import BaseModel

from app.claims import numbers
from app.documents.normalize import normalize
from app.eligibility.fields import FieldDef, InvalidAnswer, validate_answer
from app.prompts import as_data, load

_YES = {"yes", "yeah", "हाँ", "हां", "जी हाँ", "जी हां", "हा", "जी", "ha", "haan", "hyes"}
_NO = {"no", "nope", "नहीं", "नही", "जी नहीं", "जी नही", "nahi", "nahin"}
_PUNCTUATION = re.compile(r"[।॥.,!?\"']")


class ParsedAnswer(BaseModel):
    value: str | None = None
    confidence: float = 0.0


def quick_parse(field: FieldDef, transcript: str) -> Any:
    """An answer plain code can read, so it needs no LLM call. None means it can't."""
    spoken = " ".join(_PUNCTUATION.sub(" ", normalize(transcript)).split())
    if field.type == "bool":
        if spoken in {normalize(word) for word in _YES}:
            return True
        if spoken in {normalize(word) for word in _NO}:
            return False
        return None
    if field.type in ("int", "float"):
        found = numbers.parse(transcript)
        if len(found) != 1:
            return None
        kind, _, value = next(iter(found)).partition(":")
        return value if kind in ("INR", "NUM") else None
    if field.type == "enum":
        return next((o for o in field.options or [] if normalize(o).replace("_", " ") == spoken), None)
    return None


def answer_prompt(field: FieldDef, transcript: str) -> str:
    return (
        load("answer")
        .replace("{question}", field.question_en)
        .replace("{type}", field.type)
        .replace("{options}", ", ".join(field.options or []) or "none")
        .replace("{unit}", field.unit or "none")
        .replace("{transcript}", as_data(transcript))
    )


def checked_value(field: FieldDef, raw: Any) -> Any:
    """The answer in the field's type if it is within range, or None so the citizen is asked again."""
    if raw is None:
        return None
    if field.type == "bool" and isinstance(raw, str):
        raw = {"true": True, "false": False}.get(raw.strip().lower(), raw)
    try:
        return validate_answer(field.name, raw)
    except InvalidAnswer:
        return None
