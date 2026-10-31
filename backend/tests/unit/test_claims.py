import pytest

from app.claims.numbers import is_subset, parse
from app.claims.verifier import CitedClause, check_claim
from app.documents.normalize import normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("₹2,50,000", "INR:250000"),
        ("Rs. 250000", "INR:250000"),
        ("Rs.20000/-", "INR:20000"),
        ("2.5 lakh", "INR:250000"),
        ("2.5 लाख", "INR:250000"),
        ("२.५ लाख", "INR:250000"),
        ("ढाई लाख", "INR:250000"),
        ("डेढ़ लाख", "INR:150000"),
        ("₹2.5 lakh", "INR:250000"),
        ("1,20,000 रुपए", "INR:120000"),
        ("1 crore", "INR:10000000"),
        ("1 करोड़", "INR:10000000"),
        ("2.95 करोड़", "INR:29500000"),
        ("5%", "PCT:5"),
        ("5 percent", "PCT:5"),
        ("5 per cent", "PCT:5"),
        ("5 प्रतिशत", "PCT:5"),
        ("269%", "PCT:269"),
        ("12.5 %", "PCT:12.5"),
        ("31 March 2027", "DATE:2027-03-31"),
        ("31st March, 2027", "DATE:2027-03-31"),
        ("March 31, 2027", "DATE:2027-03-31"),
        ("31-03-2027", "DATE:2027-03-31"),
        ("31/03/2027", "DATE:2027-03-31"),
        ("27.05.2026", "DATE:2026-05-27"),
        ("31 मार्च 2027", "DATE:2027-03-31"),
        ("01 जुलाई, 2026", "DATE:2026-07-01"),
        ("३१ मार्च २०२७", "DATE:2027-03-31"),
        ("29 अक्टूबर, 2026", "DATE:2026-10-29"),
        ("60 days", "NUM:60"),
        ("60 दिवस", "NUM:60"),
        ("२५ वर्ग मीटर", "NUM:25"),
        ("19432/2022", "NUM:19432/2022"),
    ],
)
def test_parse_finds_canonical_form(text, expected):
    assert expected in parse(text)


def test_parse_does_not_also_count_the_parts_of_a_date_or_amount():
    assert parse("31 March 2027") == {"DATE:2027-03-31"}
    assert parse("₹2,50,000") == {"INR:250000"}
    assert parse("2.5 लाख") == {"INR:250000"}


def test_parse_finds_several_values():
    assert parse("The rate rises from 262% to 269% from 01 जुलाई, 2026.") == {
        "PCT:262",
        "PCT:269",
        "DATE:2026-07-01",
    }


def test_list_of_legal_sections_stays_separate_numbers():
    expected = {"NUM:64", "NUM:65", "NUM:2", "NUM:66", "NUM:67"}
    assert parse("धारा 64,65(2),66,67") == expected
    assert parse("Sections 64, 65(2), 66, 67") == expected
    assert parse("धारा 4,6,8,10") == {"NUM:4", "NUM:6", "NUM:8", "NUM:10"}


@pytest.mark.parametrize(
    ("text", "value"),
    [("2,50,000", "NUM:250000"), ("250,000", "NUM:250000"), ("1,20,50,000", "NUM:12050000"), ("1,000", "NUM:1000")],
)
def test_real_digit_grouping_is_one_number(text, value):
    assert parse(text) == {value}


def test_text_without_numbers_is_empty():
    assert parse("सभी पात्र किसान आवेदन कर सकते हैं") == set()


def test_impossible_date_never_matches():
    claim = parse("32-13-2027")
    assert is_subset(claim, claim) is False


@pytest.mark.parametrize(
    ("claim", "source", "ok"),
    [
        ("Limit is ₹2.5 lakh", "आय 2,50,000 रुपए से कम", True),
        ("Limit is 1,20,000", "₹1,20,000 की सहायता", True),
        ("Apply by 31 March 2027", "अंतिम तिथि 31-03-2027", True),
        ("Limit is ₹3.5 lakh", "आय 2.5 लाख से कम", False),
        ("Rate is 5%", "दर 5 है", False),
        ("Apply by 31 March 2027", "अंतिम तिथि 31-03-2026", False),
        ("Anyone may apply", "1 जनवरी 2026 की सूचना", True),
    ],
)
def test_is_subset(claim, source, ok):
    assert is_subset(parse(claim), parse(source)) is ok


def _native(text):
    return CitedClause(normalize(text), "native")


def _ocr(text):
    return CitedClause(normalize(text), "ocr")


SOURCE = "वार्षिक आय 2.5 लाख रुपये से कम होनी चाहिए और आवेदन 31 मार्च 2027 तक करें।"


def test_real_quote_passes():
    assert check_claim("Income must be under ₹2.5 lakh.", "वार्षिक आय 2.5 लाख रुपये से कम", [_native(SOURCE)]) is None


def test_quote_may_span_the_cited_clauses():
    cited = [_native("आय सीमा 2.5 लाख है"), _native("और आवेदन निःशुल्क है")]
    assert check_claim("Applying is free.", "2.5 लाख है और आवेदन निःशुल्क", cited) is None


def test_fabricated_quote_is_rejected():
    assert check_claim("Income limit.", "वार्षिक आय 9 लाख रुपये तक मान्य", [_native(SOURCE)]) == "QUOTE_NOT_IN_SOURCE"


def test_unknown_clause_is_rejected():
    assert check_claim("Income limit.", "वार्षिक आय 2.5 लाख", []) == "CLAUSE_NOT_FOUND"


@pytest.mark.parametrize("quote", ["", None, "2.5", "आय"])
def test_empty_or_tiny_quote_is_rejected(quote):
    assert check_claim("Income limit.", quote, [_native(SOURCE)]) == "QUOTE_TOO_SHORT"


def test_real_quote_with_a_different_number_in_the_claim_is_rejected():
    assert (
        check_claim("Income must be under ₹3 lakh.", "वार्षिक आय 2.5 लाख रुपये से कम", [_native(SOURCE)])
        == "NUMBER_NOT_IN_QUOTE"
    )


def test_native_quote_must_match_exactly():
    assert check_claim("Income limit.", "वार्षिक आय 2.5 लाख रुपयों से कम", [_native(SOURCE)]) == "QUOTE_NOT_IN_SOURCE"


def test_ocr_quote_tolerates_a_small_misread():
    assert check_claim("Income limit.", "वार्षिक आय 2.5 लाख रुपए से कम होनी चाहिए", [_ocr(SOURCE)]) is None


def test_ocr_fuzzy_match_cannot_change_a_number():
    assert check_claim("Income limit.", "वार्षिक आय 3.5 लाख रुपये से कम होनी चाहिए", [_ocr(SOURCE)]) == "QUOTE_NOT_IN_SOURCE"


def test_dash_style_does_not_cause_rejection():
    assert check_claim("Circular.", "परिपत्र संख्या–31/2025", [_native("डीजी परिपत्र संख्या-31/2025 दिनांक")]) is None


def test_quote_digits_match_in_any_script():
    assert check_claim("Income under ₹2.5 lakh.", "वार्षिक आय २.५ लाख रुपये", [_native(SOURCE)]) is None
