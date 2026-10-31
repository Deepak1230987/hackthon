import re

_REPLACEMENT = re.compile("[�-]")
_INDIC = re.compile(r"[ऀ-৿]")

# Text that a real font would never have shaped. A vowel sign can't repeat, follow a virama
# or stand without a consonant, so these sequences mean the text layer is corrupted, even
# though every character is valid Unicode.
_BROKEN_SHAPING = re.compile(
    r"([ा-ौ])\1"
    r"|्[ा-ौ]"
    r"|(?:^|[^क-हक़-य़ॸ-ॿ़‌‍])[ा-ौ]"
    r"|([া-ৌ])\2"
    r"|্[া-ৌ]"
    r"|(?:^|[^ক-হড়-য়়‌‍])[া-ৌ]",
    re.MULTILINE,
)

_LEGACY_FONT = re.compile(r"kruti|devlys|chanakya|shusha|mangal.?legacy", re.IGNORECASE)
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_COMMON_ENGLISH = frozenset(
    "the of and to in for is be by or on as at an are shall with this that from will any "
    "under which may not has have per all if it its such".split()
)

MIN_TEXT_CHARS = 40
MAX_REPLACEMENT_RATIO = 0.02
MIN_BROKEN_SEQUENCES = 3
MAX_BROKEN_RATIO = 0.002
MIN_BROKEN_IN_SHORT_TEXT = 2
MIN_BROKEN_RATIO_IN_SHORT_TEXT = 0.02
MAX_CAPTION_CHARS = 300
MIN_LATIN_WORDS = 30
MIN_COMMON_WORD_RATIO = 0.04
MIN_SYMBOL_RATIO = 0.04


def replacement_ratio(text: str) -> float:
    return len(_REPLACEMENT.findall(text)) / max(len(text), 1)


def broken_shaping(text: str) -> tuple[int, float]:
    """How many impossible sequences the text has, and as a share of its Indic characters."""
    broken = len(_BROKEN_SHAPING.findall(text))
    return broken, broken / max(len(_INDIC.findall(text)), 1)


def has_broken_shaping(text: str) -> bool:
    broken, ratio = broken_shaping(text)
    if broken >= MIN_BROKEN_SEQUENCES and ratio > MAX_BROKEN_RATIO:
        return True
    # A caption is too short to reach the count above, but two in a few words can't be chance.
    return broken >= MIN_BROKEN_IN_SHORT_TEXT and ratio >= MIN_BROKEN_RATIO_IN_SHORT_TEXT


def legacy_font_pattern(text: str, fonts: list[str]) -> bool:
    """Hindi typed in an old font extracts as Latin nonsense, such as "Hkkjr ljdkj"."""
    if any(_LEGACY_FONT.search(font) for font in fonts):
        return True
    words = _LATIN_WORD.findall(text)
    if len(words) < MIN_LATIN_WORDS:
        return False
    common = sum(word.lower() in _COMMON_ENGLISH for word in words) / len(words)
    symbols = sum(not (c.isalnum() or c.isspace()) for c in text) / max(len(text), 1)
    return common < MIN_COMMON_WORD_RATIO and symbols > MIN_SYMBOL_RATIO


def ocr_reason(
    text: str, fonts: list[str], has_visuals: bool, has_figure: bool = False
) -> str | None:
    """Why this page can't trust its text layer, or None if it can."""
    if len(text.strip()) < MIN_TEXT_CHARS:
        # With nothing else on the page, a short text layer is simply all there is to read.
        return "no_text" if has_visuals else None
    if replacement_ratio(text) > MAX_REPLACEMENT_RATIO:
        return "replacement_characters"
    if has_broken_shaping(text):
        return "broken_shaping"
    if legacy_font_pattern(text, fonts):
        return "legacy_font"
    # A chart with a caption: the text layer has the caption, and the amounts are in the image.
    if has_figure and len(text.strip()) < MAX_CAPTION_CHARS:
        return "figure_with_little_text"
    return None
