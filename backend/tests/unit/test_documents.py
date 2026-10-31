import pymupdf
import pytest

from app.documents.extract import extract_pages
from app.documents.garble import (
    broken_shaping,
    has_broken_shaping,
    legacy_font_pattern,
    ocr_reason,
)
from app.documents.normalize import detect_language, normalize
from app.documents.segment import MAX_CLAUSE_CHARS, find_furniture, segment_page

CLEAN_HINDI = (
    "ग्रामीण क्षेत्रों में गरीब लोगों की जीवन-दशा में बदलाव के लिए पक्के मकानों का निर्माण करके "
    "उन्हें वे मकान उपलब्ध कराने का सम्मान प्रधान मंत्री जी की प्रतिबद्धता है। कृषि, शिक्षा और "
    "स्वास्थ्य योजनाओं की पात्रता अधिकारी द्वारा तय की जाएगी।"
)
# Copied from the text layer of the official PMAY-G Hindi booklet.
CORRUPTED_HINDI = (
    "मई, 2014 में, ग्ामीीण और शहरी क्ेत्ों में गरीब लोगों की जीीवन-दशा में बदलाव के लिए "
    "पक्े मकानों का निर्मााण करके उन्ें वे मकान उपलब्ध कराने के प्रधान मंत्री जीी के सपने"
)
CLEAN_BENGALI = "গ্রামীণ এলাকার দরিদ্র মানুষের জীবনযাত্রার উন্নতির জন্য এই প্রকল্প চালু করা হয়েছে।"
ENGLISH = (
    "The applicant shall be a resident of the State and the annual income of the family "
    "shall not exceed the limit prescribed under this scheme, as per the rules. "
) * 3
LEGACY_LATIN = (
    "Hkkjr ljdkj ds xzkeh.k fodkl ea=ky; }kjk iz/kku ea=h vkokl ;kstuk dk;kZUo;u "
    "fd;k tk jgk gS A ;kstuk ds varxZr ik= ykHkkFkhZ dks vkokl gsrq jkf'k nh tk;sxh A "
) * 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("₹२,५०,०००", "₹2,50,000"),
        ("৫০০", "500"),
        ("  Two\n  words ", "two words"),
        ("“Quoted”", '"quoted"'),
        ("‘a’", "'a'"),
        ("soft­hyphen", "softhyphen"),
        ("कि‍सान", "किसान"),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_normalize_composes_unicode():
    assert normalize("क़") == normalize("क़")


@pytest.mark.parametrize(
    ("text", "language"),
    [
        (CLEAN_HINDI, "hi"),
        (CLEAN_BENGALI, "bn"),
        (ENGLISH, "en"),
        ("योजनेचा लाभ देण्यात येतो आणि अर्ज करावे लागतील आहे", "mr"),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text) == language


@pytest.mark.parametrize("text", [CLEAN_HINDI, CLEAN_BENGALI, ENGLISH])
def test_clean_text_has_no_broken_shaping(text):
    assert broken_shaping(text)[0] == 0
    assert ocr_reason(text, [], False) is None


def test_finds_corruption_with_valid_unicode_and_no_legacy_font():
    assert broken_shaping(CORRUPTED_HINDI)[0] >= 5
    assert ocr_reason(CORRUPTED_HINDI, ["Mangal"], False) == "broken_shaping"


@pytest.mark.parametrize(
    "sequence",
    ["जीीवन", "सम्ान", "प्रस्तावनाा", "ি কিছু কিছু"],
)
def test_each_impossible_sequence_is_counted(sequence):
    assert broken_shaping(sequence)[0] >= 1


def test_a_single_odd_sequence_does_not_send_a_page_to_ocr():
    assert not has_broken_shaping(CLEAN_HINDI + " जीीवन")


def test_legacy_font_name_is_detected():
    assert legacy_font_pattern(ENGLISH, ["ABCDEE+Kruti Dev 010"])


def test_legacy_text_is_detected_without_the_font_name():
    assert ocr_reason(LEGACY_LATIN, ["Unknown"], False) == "legacy_font"


def test_english_is_not_mistaken_for_a_legacy_font():
    assert not legacy_font_pattern(ENGLISH, ["Arial"])


def test_replacement_characters_go_to_ocr():
    assert ocr_reason("�" * 10 + ENGLISH[:200], [], False) == "replacement_characters"


def test_scanned_page_goes_to_ocr_but_a_nearly_empty_page_does_not():
    assert ocr_reason("", [], True) == "no_text"
    assert ocr_reason("3", [], False) is None


def _line(text, y, block=0, size=11.0, bold=False):
    return {"text": text, "bbox": [72, y, 500, y + 12], "size": size, "bold": bold, "block": block}


def _native(*lines, rows=()):
    return {"lines": list(lines), "rows": list(rows), "height": 842}


def test_lines_in_a_block_merge_and_numbered_items_split():
    record = _native(
        _line("1. The applicant must live in", 100),
        _line("the State.", 112),
        _line("2. Income must be below the limit.", 124),
        _line("(a) Salaried people are excluded.", 136),
    )
    clauses = segment_page(4, record, set(), "native")
    assert [c.text for c in clauses] == [
        "1. The applicant must live in the State.",
        "2. Income must be below the limit.",
        "(a) Salaried people are excluded.",
    ]
    assert clauses[0].page == 4
    assert clauses[0].bbox == [72, 100, 500, 124]


def test_amount_at_line_start_does_not_split_a_clause():
    record = _native(_line("Income must not exceed", 100), _line("2.5 lakh per year.", 112))
    assert [c.text for c in segment_page(1, record, set(), "native")] == [
        "Income must not exceed 2.5 lakh per year."
    ]


def test_paragraph_broken_across_blocks_is_rejoined_only_when_unfinished():
    unfinished = _native(_line("The grant is paid", 100, block=0), _line("every year.", 113, block=1))
    finished = _native(_line("The grant is paid.", 100, block=0), _line("Apply online.", 113, block=1))
    assert len(segment_page(1, unfinished, set(), "native")) == 1
    assert len(segment_page(1, finished, set(), "native")) == 2


def test_hyphenated_word_is_rejoined():
    record = _native(_line("The bene-", 100), _line("ficiary gets it.", 112))
    assert segment_page(1, record, set(), "native")[0].text == "The beneficiary gets it."


def test_heading_detection():
    record = _native(
        _line("ELIGIBILITY", 90, block=0),
        _line("Who can apply", 110, block=1, bold=True),
        _line("Every resident of the State can apply for this scheme.", 130, block=2),
        _line("And more text here.", 150, block=3),
    )
    assert [c.kind for c in segment_page(1, record, set(), "native")] == [
        "heading", "heading", "para", "para",
    ]


def test_long_clause_splits_at_sentence_boundaries_including_danda():
    sentence = "यह योजना सभी पात्र नागरिकों के लिए है। "
    record = _native(_line(sentence * 80, 100))
    clauses = segment_page(1, record, set(), "native")
    assert len(clauses) > 1
    assert all(len(c.text) <= MAX_CLAUSE_CHARS for c in clauses)
    assert all(c.text.endswith("।") for c in clauses)
    assert "".join(c.text for c in clauses).count("योजना") == 80


def test_long_text_without_punctuation_still_splits():
    record = _native(_line("word " * 600, 100))
    clauses = segment_page(1, record, set(), "native")
    assert all(len(c.text) <= MAX_CLAUSE_CHARS for c in clauses)
    assert sum(c.text.count("word") for c in clauses) == 600


def test_repeated_headers_and_page_numbers_are_dropped():
    records = [
        _native(
            _line("Ministry of Rural Development", 20),
            _line(f"Body text of page {n} is unique to it, number {n * 7}.", 300, block=1),
            _line(f"Page {n} of 5", 780, block=2),
        )
        for n in range(1, 6)
    ]
    furniture = find_furniture(records)
    clauses = segment_page(2, records[1], furniture, "native")
    assert [c.text for c in clauses] == ["Body text of page 2 is unique to it, number 14."]


def test_text_on_only_two_pages_is_kept():
    records = [_native(_line("Same line", 20)) for _ in range(2)]
    assert find_furniture(records) == set()


def test_ocr_clauses_have_no_box():
    record = {"items": [{"kind": "para", "text": "वार्षिक  आय\n2.5 लाख"}, {"kind": "para", "text": "..."}]}
    clauses = segment_page(3, record, set(), "ocr")
    assert len(clauses) == 1
    assert clauses[0].text == "वार्षिक आय 2.5 लाख"
    assert clauses[0].bbox is None
    assert clauses[0].extraction == "ocr"


def _pdf_with_table() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 60), "Annual income limits for applicants are set out below:")
    grid = [
        ["Category", "Income limit"],
        ["General", "Rs. 2,50,000"],
        ["Scheduled Caste", "Rs. 8,00,000"],
    ]
    x = [72, 250, 450]
    y = [100, 130, 160, 190]
    for yy in y:
        page.draw_line((x[0], yy), (x[-1], yy))
    for xx in x:
        page.draw_line((xx, y[0]), (xx, y[-1]))
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            page.insert_text((x[c] + 5, y[r] + 20), value)
    return document.tobytes()


def test_table_rows_become_whole_clauses():
    extracted = extract_pages(_pdf_with_table(), [1])[0]
    assert extracted.ocr_reason is None
    clauses = segment_page(1, extracted.data, set(), "native")
    texts = [c.text for c in clauses]
    assert "Category: General; Income limit: Rs. 2,50,000" in texts
    assert "Category: Scheduled Caste; Income limit: Rs. 8,00,000" in texts
    assert sum("General" in text for text in texts) == 1  # Not repeated as plain text too.
    row = next(c for c in clauses if "General" in c.text)
    assert row.kind == "table_row"
    assert row.bbox is not None


def test_columns_without_ruled_lines_do_not_get_guessed_headers():
    document = pymupdf.open()
    page = document.new_page()
    # Horizontal rules only, like a real scheme table whose amounts were mislabelled.
    for y in (100, 130, 160, 190):
        page.draw_line((72, y), (450, y))
    grid = [["Groups", "Hostellers", "Day Scholars"], ["Group 1", "13500", "7000"]]
    for r, row in enumerate(grid):
        for x, value in zip((77, 250, 370), row):
            page.insert_text((x, 120 + r * 30), value)
    extracted = extract_pages(document.tobytes(), [1])[0]
    clauses = segment_page(1, extracted.data, set(), "native")
    assert all(c.kind != "table_row" for c in clauses)
    assert not any(":" in c.text for c in clauses)
    assert "7000" in " ".join(c.text for c in clauses)


def test_list_label_alone_on_its_line_starts_the_next_clause():
    lines = [
        _line("The value includes the following:-", 100, block=0),
        _line("i.", 120, block=1),
        _line("Maintenance allowance,", 120, block=1),
        _line("ii.", 140, block=2),
        _line("Study tour charges,", 140, block=2),
    ]
    texts = [c.text for c in segment_page(1, _native(*lines), set(), "native")]
    assert texts == [
        "The value includes the following:-",
        "i. Maintenance allowance,",
        "ii. Study tour charges,",
    ]


def _page_with_image(share: float, caption: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    side = (abs(page.rect) * share) ** 0.5
    page.insert_image(pymupdf.Rect(50, 300, 50 + side, 300 + side), pixmap=pixmap)
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 280), caption)
    return document.tobytes()


CAPTION = "Additional assistance under the scheme, shown in the chart below."


def test_chart_with_a_caption_is_routed_to_ocr():
    # Found on a real scheme booklet: the amounts were in the image, under a one-line heading.
    extracted = extract_pages(_page_with_image(0.26, CAPTION), [1])[0]
    assert extracted.ocr_reason == "figure_with_little_text"


def test_small_logo_above_a_short_notice_keeps_its_text():
    extracted = extract_pages(_page_with_image(0.02, CAPTION), [1])[0]
    assert extracted.ocr_reason is None


def test_image_beside_plenty_of_text_keeps_its_text():
    extracted = extract_pages(_page_with_image(0.26, ENGLISH), [1])[0]
    assert extracted.ocr_reason is None


def test_short_caption_with_broken_shaping_is_routed_to_ocr():
    # A footer from the same booklet, for "पीएमएवाई-जी : सम्मान का द्वार".
    caption = "पीएमएवाई-जी : सम्ान का द्ार पीएमएवाई-जी में अतिरिक्त सुविधा"
    assert ocr_reason(caption, [], False) == "broken_shaping"


def test_scanned_page_is_routed_to_ocr():
    document = pymupdf.open()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    document.new_page().insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=pixmap)
    extracted = extract_pages(document.tobytes(), [1])[0]
    assert extracted.data is None
    assert extracted.ocr_reason == "no_text"
