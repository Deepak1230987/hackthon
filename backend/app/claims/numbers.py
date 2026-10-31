import re
from datetime import date

from app.documents.normalize import normalize

_MONTHS = {
    **{
        name: number
        for number, names in enumerate(
            (
                ("january", "jan", "जनवरी", "জানুয়ারি"),
                ("february", "feb", "फरवरी", "फ़रवरी", "ফেব্রুয়ারি"),
                ("march", "mar", "मार्च", "মার্চ"),
                ("april", "apr", "अप्रैल", "এপ্রিল"),
                ("may", "मई", "मे", "মে"),
                ("june", "jun", "जून", "জুন"),
                ("july", "jul", "जुलाई", "जुलै", "জুলাই"),
                ("august", "aug", "अगस्त", "ऑगस्ट", "আগস্ট"),
                ("september", "sep", "sept", "सितंबर", "सितम्बर", "सप्टेंबर", "সেপ্টেম্বর"),
                ("october", "oct", "अक्टूबर", "अक्तूबर", "ऑक्टोबर", "অক্টোবর"),
                ("november", "nov", "नवंबर", "नवम्बर", "नोव्हेंबर", "নভেম্বর"),
                ("december", "dec", "दिसंबर", "दिसम्बर", "डिसेंबर", "ডিসেম্বর"),
            ),
            start=1,
        )
        for name in map(normalize, names)
    }
}
_MULTIPLIERS = {
    **dict.fromkeys(map(normalize, ("lakh", "lakhs", "lac", "lacs", "लाख", "লাখ")), 100_000),
    **dict.fromkeys(map(normalize, ("crore", "crores", "करोड़", "करोड", "কোটি")), 10_000_000),
    **dict.fromkeys(map(normalize, ("thousand", "हजार", "हज़ार", "হাজার")), 1_000),
}
_FRACTION_WORDS = {normalize("डेढ़"): 1.5, normalize("ढाई"): 2.5, normalize("सवा"): 1.25}
_CURRENCY_BEFORE = "|".join(map(re.escape, map(normalize, ("₹", "rs.", "rs", "inr", "रु.", "रु", "টাকা"))))
_CURRENCY_AFTER = "|".join(map(re.escape, map(normalize, ("रुपये", "रुपए", "रुपया", "rupees", "rupee", "টাকা", "/-"))))
_PERCENT = "|".join(map(re.escape, map(normalize, ("%", "percent", "per cent", "प्रतिशत", "শতাংশ", "टक्के"))))


def _alternatives(names) -> str:
    return "|".join(sorted(map(re.escape, names), key=len, reverse=True))


# Indian grouping (2,50,000) or western (250,000), then an optional decimal part. A group must
# end in three digits, so a list of legal sections such as "64,65,66" stays separate numbers.
_GROUPED = r"\d{1,2}(?:,\d{2})*,\d{3}(?!,?\d)|\d{1,3}(?:,\d{3})+(?!,?\d)"
_NUMBER = rf"(?:{_GROUPED}|\d+)(?:\.\d+)?"
_MONTH_NAME = _alternatives(_MONTHS)
_MULTIPLIER = _alternatives(_MULTIPLIERS)

_DAY_MONTH_YEAR = re.compile(
    rf"(?<![\d.])(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+({_MONTH_NAME})[\s,.-]+(\d{{4}})(?!\d)"
)
_MONTH_DAY_YEAR = re.compile(rf"(?<![^\W\d_])({_MONTH_NAME})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)")
_NUMERIC_DATE = re.compile(r"(?<![\d./-])(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?![\d/-])")
_PERCENTAGE = re.compile(rf"(?<![\d.,])({_NUMBER})\s*(?:{_PERCENT})")
_WORD_AMOUNT = re.compile(rf"({_alternatives(_FRACTION_WORDS)})\s+({_MULTIPLIER})")
_AMOUNT = re.compile(
    rf"(?:(?:{_CURRENCY_BEFORE})\s*)?(?<![\d.,])({_NUMBER})\s*({_MULTIPLIER})(?:\s*(?:{_CURRENCY_AFTER}))?"
)
_CURRENCY_FIRST = re.compile(rf"(?:{_CURRENCY_BEFORE})\s*({_NUMBER})")
_CURRENCY_LAST = re.compile(rf"(?<![\d.,])({_NUMBER})\s*(?:{_CURRENCY_AFTER})")
_ANY_NUMBER = re.compile(rf"(?:{_GROUPED}|\d+)(?:[./]\d+)*(?:[a-z]+)?")


def _value(text: str) -> float:
    return float(text.replace(",", ""))


def _canonical(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _date(day: str | int, month: int, year: str | int) -> str:
    try:
        return f"DATE:{date(int(year), int(month), int(day)).isoformat()}"
    except ValueError:
        # Looks like a date but can't be one. This can never match, so the claim is rejected.
        return f"BAD:{day}-{month}-{year}"


def parse(text: str) -> set[str]:
    """Every number in the text in canonical form, whatever script or format it was written in."""
    remaining = normalize(text)
    found: set[str] = set()

    def take(pattern: re.Pattern, convert) -> None:
        nonlocal remaining

        def replace(match: re.Match) -> str:
            found.add(convert(match))
            return " "

        remaining = pattern.sub(replace, remaining)

    take(_DAY_MONTH_YEAR, lambda m: _date(m[1], _MONTHS[m[2]], m[3]))
    take(_MONTH_DAY_YEAR, lambda m: _date(m[2], _MONTHS[m[1]], m[3]))
    take(_NUMERIC_DATE, lambda m: _date(m[1], m[2], m[3]))
    take(_PERCENTAGE, lambda m: f"PCT:{_canonical(_value(m[1]))}")
    take(_WORD_AMOUNT, lambda m: f"INR:{_canonical(_FRACTION_WORDS[m[1]] * _MULTIPLIERS[m[2]])}")
    take(_AMOUNT, lambda m: f"INR:{_canonical(_value(m[1]) * _MULTIPLIERS[m[2]])}")
    take(_CURRENCY_FIRST, lambda m: f"INR:{_canonical(_value(m[1]))}")
    take(_CURRENCY_LAST, lambda m: f"INR:{_canonical(_value(m[1]))}")

    for token in _ANY_NUMBER.findall(remaining):
        plain = token.replace(",", "")
        grouped = re.fullmatch(_NUMBER, token)
        found.add(f"NUM:{_canonical(_value(token))}" if grouped else f"NUM:{plain}")
    return found


def _comparable(item: str) -> str:
    # "1,20,000" in a claim is the same figure as "₹1,20,000" in its quote.
    return item.split(":", 1)[1] if item.startswith(("INR:", "NUM:")) else item


def is_subset(claim: set[str], source: set[str]) -> bool:
    """Whether every number in the claim also appears in the source."""
    if any(item.startswith("BAD:") for item in claim):
        return False
    return {_comparable(item) for item in claim} <= {_comparable(item) for item in source}
