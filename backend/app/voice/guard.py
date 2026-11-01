import re
from typing import Literal

from pydantic import BaseModel

from app.claims import numbers
from app.prompts import as_data, load

MeaningLabel = Literal["SAME", "MINOR_DIFF", "CHANGED"]

# No word boundary, because PDFs lose spaces: "1stApril".
_ORDINAL = re.compile(r"(\d)(?:st|nd|rd|th)", re.IGNORECASE)
_NUMBER_WORDS = {
    **dict(zip("one two three four five six seven eight nine ten".split(), range(1, 11))),
    **dict(zip("एक दो तीन चार पांच छह सात आठ नौ दस".split(), range(1, 11))),
    "पाँच": 5,
    "छः": 6,
}
_WORD = re.compile(r"[^\W\d_]+(?:[\u0900-\u0963\u0966-\u097F]*)")


class MeaningVerdict(BaseModel):
    index: int
    label: MeaningLabel


class MeaningResult(BaseModel):
    verdicts: list[MeaningVerdict] = []


def _found_in(text: str) -> tuple[set[str], set[str]]:
    """The numbers written in digits, and the same numbers once small ones spelled out are added."""
    digits = numbers.parse(_ORDINAL.sub(r"\1 ", text))
    spelled = {f"NUM:{_NUMBER_WORDS[word]}" for word in _WORD.findall(text.lower()) if word in _NUMBER_WORDS}
    return digits, digits | spelled


def numbers_match(source: str, translated: str) -> bool:
    """Free, and it catches the mistake that costs a citizen most, so it runs first.

    A translator may write "one year" as "1 साल", or "31st" as "31". A spelled-out number only
    excuses a matching digit, so "one year" as "2 साल" still fails.
    """
    source_digits, source_all = _found_in(source)
    translated_digits, translated_all = _found_in(translated)
    return numbers.is_subset(source_digits, translated_all) and numbers.is_subset(
        translated_digits, source_all
    )


def meaning_prompt(pairs: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f'<pair index="{index}">\n<english>{as_data(source)}</english>\n'
        f"<translation>{as_data(translated)}</translation>\n</pair>"
        for index, (source, translated) in enumerate(pairs)
    )
    return load("meaning").replace("{pairs}", items)
