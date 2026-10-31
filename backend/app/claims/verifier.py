import re
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio

from app.claims import numbers
from app.documents.normalize import normalize

OCR_MATCH_THRESHOLD = 92
MIN_QUOTE_CHARS = 8
_DASHES = re.compile(r"[‐-―−]")


@dataclass
class CitedClause:
    norm_text: str
    extraction: str  # native | ocr


def _comparable(text: str) -> str:
    # Models and PDFs differ on which dash they use, which says nothing about the wording.
    return _DASHES.sub("-", text)


def check_claim(claim_text: str, quote: str | None, cited: list[CitedClause]) -> str | None:
    """The reason code checks reject this claim, or None if only entailment is left to judge.

    A failure here can't be overruled by any LLM.
    """
    if not cited:
        return "CLAUSE_NOT_FOUND"
    normal_quote = _comparable(normalize(quote or ""))
    if len(normal_quote) < MIN_QUOTE_CHARS:
        return "QUOTE_TOO_SHORT"

    source = _comparable(" ".join(clause.norm_text for clause in cited))
    if any(clause.extraction == "ocr" for clause in cited):
        if partial_ratio(normal_quote, source) < OCR_MATCH_THRESHOLD:
            return "QUOTE_NOT_IN_SOURCE"
        # A fuzzy match would accept "3.5 lakh" for "2.5 lakh", so numbers must match exactly.
        if not numbers.is_subset(numbers.parse(quote or ""), numbers.parse(source)):
            return "QUOTE_NOT_IN_SOURCE"
    elif normal_quote not in source:
        return "QUOTE_NOT_IN_SOURCE"

    if not numbers.is_subset(numbers.parse(claim_text), numbers.parse(quote or "")):
        return "NUMBER_NOT_IN_QUOTE"
    return None
