import re
from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Any

from app.documents.normalize import normalize

MAX_CLAUSE_CHARS = 1200
FURNITURE_MIN_PAGES = 3
FURNITURE_MIN_SHARE = 0.25
FURNITURE_MAX_CHARS = 120
FURNITURE_FUZZY_CHARS = 40
MARGIN_SHARE = 0.12
HEADING_MAX_WORDS = 14
HEADING_SIZE_RATIO = 1.15
MERGE_GAP_LINES = 1.5

_NUMBERED = re.compile(
    r"^\s*(?:"
    r"[\d०-९০-৯]{1,3}[.)]\s"  # 1.  २)
    r"|\d{1,3}(?:\.\d{1,3})+\.?\s+(?!lakh|crore|lac|%|percent|लाख|करोड़)"  # 3.2  but not 2.5 lakh
    r"|\(?[a-zA-Z]\)\s"  # (a)  a)
    r"|\([ivxIVX]{1,5}\)\s"  # (iv)
    r"|\(?[क-ह]\)\s"  # (क)
    r"|\([\d०-९০-৯]{1,3}\)\s"  # (1)
    r"|[•●▪◦·*–-]\s"  # bullets
    r")"
)
_TERMINAL = re.compile(r"[.।॥:;?!]['\")\]]?\s*$")
_SENTENCE_END = re.compile(r"(?<!\bRs)(?<!\bNo)(?<!\bSh)(?<!\bDr)(?<!\bSmt)(?<=[.।?!])\s+")
_PAGE_NUMBER = re.compile(r"^\W*(?:page\s*)?[\d०-९]+(?:\s*(?:of|/)\s*[\d०-९]+)?\W*$", re.IGNORECASE)
_HAS_CONTENT = re.compile(r"\w")
_DIGITS = re.compile(r"[\d०-९০-৯]+")


@dataclass
class ClauseDraft:
    page: int
    bbox: list[float] | None
    text: str
    kind: str
    extraction: str


def _furniture_key(text: str) -> str:
    # Page numbers change on every page, but a longer line differing by a number can be a rule.
    normal = normalize(text)
    return _DIGITS.sub("#", normal) if len(normal) <= FURNITURE_FUZZY_CHARS else normal


def _ocr_edges(items: list[dict[str, str]]) -> list[str]:
    edge = [items[0], items[-1]] if items else []
    return [item["text"] for item in edge if item["kind"] != "table_row"]


def _in_margin(line: dict[str, Any], height: float) -> bool:
    return line["bbox"][1] < height * MARGIN_SHARE or line["bbox"][3] > height * (1 - MARGIN_SHARE)


def _edge_texts(record: dict[str, Any]) -> list[str]:
    if "items" in record:
        return _ocr_edges(record["items"])
    return [line["text"] for line in record["lines"] if _in_margin(line, record["height"])]


def find_furniture(records: list[dict[str, Any]]) -> set[str]:
    """Headers and footers: short text at the top or bottom edge of many pages."""
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(
            {_furniture_key(text) for text in _edge_texts(record) if len(text) <= FURNITURE_MAX_CHARS}
        )
    needed = max(FURNITURE_MIN_PAGES, FURNITURE_MIN_SHARE * len(records))
    return {key for key, count in counts.items() if key and count >= needed}


def segment_page(
    page: int, record: dict[str, Any], furniture: set[str], extraction: str
) -> list[ClauseDraft]:
    if extraction == "ocr":
        drafts = [
            ClauseDraft(page, None, " ".join(item["text"].split()), item["kind"], "ocr")
            for item in record["items"]
            if item["kind"] == "table_row" or not _is_furniture(item["text"], furniture)
        ]
    else:
        drafts = _native_clauses(page, record, furniture)
    return [
        part
        for draft in drafts
        if _HAS_CONTENT.search(draft.text)
        for part in _split_long(draft)
    ]


def _is_furniture(text: str, furniture: set[str]) -> bool:
    return bool(_PAGE_NUMBER.match(text.strip())) or _furniture_key(text) in furniture


def _native_clauses(page: int, record: dict[str, Any], furniture: set[str]) -> list[ClauseDraft]:
    lines = [
        line
        for line in record["lines"]
        if not (_in_margin(line, record["height"]) and _is_furniture(line["text"], furniture))
    ]
    typical_size = median(line["size"] for line in lines) if lines else 0
    units: list[dict[str, Any]] = []
    for line in lines:
        previous = units[-1] if units else None
        if previous and _continues(previous, line):
            _append_line(previous, line)
        else:
            units.append({**line, "numbered": bool(_NUMBERED.match(line["text"]))})

    drafts = [
        (
            unit["bbox"][1],
            ClauseDraft(page, unit["bbox"], unit["text"], _unit_kind(unit, typical_size), "native"),
        )
        for unit in units
    ]
    drafts += [
        (row["bbox"][1], ClauseDraft(page, row["bbox"], row["text"], "table_row", "native"))
        for row in record["rows"]
    ]
    return [draft for _, draft in sorted(drafts, key=lambda pair: pair[0])]


def _continues(unit: dict[str, Any], line: dict[str, Any]) -> bool:
    if _NUMBERED.match(line["text"]):
        return False
    if line["block"] == unit["block"]:
        return True
    if _TERMINAL.search(unit["text"]) or unit["text"].isupper() or unit["bold"] != line["bold"]:
        return False
    gap =line["bbox"][1] - unit["bbox"][3]
    return 0 <= gap < line["size"] * MERGE_GAP_LINES and line["size"] == unit["size"]


def _append_line(unit: dict[str, Any], line: dict[str, Any]) -> None:
    head = unit["text"]
    # Rejoin a word hyphenated across lines, but only in Latin text.
    if re.search(r"[a-z]-$", head) and re.match(r"[a-z]", line["text"]):
        unit["text"] = head[:-1] + line["text"]
    else:
        unit["text"] = f"{head} {line['text']}"
    box = unit["bbox"]
    other = line["bbox"]
    unit["bbox"] = [min(box[0], other[0]), min(box[1], other[1]),
                    max(box[2], other[2]), max(box[3], other[3])]
    unit["bold"] = unit["bold"] and line["bold"]


def _unit_kind(unit: dict[str, Any], typical_size: float) -> str:
    text = unit["text"]
    is_short = len(text.split()) <= HEADING_MAX_WORDS and not _TERMINAL.search(text)
    looks_like_one = (
        unit["bold"] or unit["size"] > typical_size * HEADING_SIZE_RATIO or text.isupper()
    )
    return "heading" if is_short and looks_like_one else "para"


def _split_long(draft: ClauseDraft) -> list[ClauseDraft]:
    if len(draft.text) <= MAX_CLAUSE_CHARS:
        return [draft]
    parts: list[str] = []
    current = ""
    for piece in _pieces(draft.text):
        if current and len(current) + len(piece) + 1 > MAX_CLAUSE_CHARS:
            parts.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    parts.append(current)
    return [ClauseDraft(draft.page, draft.bbox, p, draft.kind, draft.extraction) for p in parts]


def _pieces(text: str) -> list[str]:
    """Sentences, with any single sentence that is still too long split between words."""
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > MAX_CLAUSE_CHARS:
            cut = sentence.rfind(" ", 0, MAX_CLAUSE_CHARS)
            cut = cut if cut > 0 else MAX_CLAUSE_CHARS
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        pieces.append(sentence)
    return pieces
