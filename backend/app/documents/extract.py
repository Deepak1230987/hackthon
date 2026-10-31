from dataclasses import dataclass
from typing import Any

import pymupdf

from app.documents.garble import ocr_reason

MIN_DRAWINGS_FOR_VISUALS = 50
MIN_DRAWINGS_FOR_TABLE = 2
MIN_FIGURE_SHARE = 0.15
OCR_DPI = 200
BOLD_FLAG = 16
RULE_TOLERANCE = 2


@dataclass
class ExtractedPage:
    page: int  # 1-based
    data: dict[str, Any] | None  # None when the page needs OCR
    ocr_reason: str | None


def extract_pages(content: bytes, pages: list[int]) -> list[ExtractedPage]:
    with pymupdf.open(stream=content, filetype="pdf") as document:
        return [_extract_page(document[number - 1], number) for number in pages]


def render_page(content: bytes, page: int) -> bytes:
    with pymupdf.open(stream=content, filetype="pdf") as document:
        return document[page - 1].get_pixmap(dpi=OCR_DPI).tobytes("png")


def _extract_page(page: pymupdf.Page, number: int) -> ExtractedPage:
    text = page.get_text()
    fonts = [font[3] for font in page.get_fonts()]
    drawings = len(page.get_cdrawings())
    visuals = bool(page.get_images()) or drawings > MIN_DRAWINGS_FOR_VISUALS
    figure = drawings > MIN_DRAWINGS_FOR_VISUALS or _image_share(page) >= MIN_FIGURE_SHARE
    reason = ocr_reason(text, fonts, visuals, figure)
    if reason:
        return ExtractedPage(number, None, reason)
    # Table detection is the slowest step by far, and a table needs ruled lines to find.
    rows, table_boxes = _table_rows(page) if drawings >= MIN_DRAWINGS_FOR_TABLE else ([], [])
    data = {"lines": _lines(page, table_boxes), "rows": rows, "height": round(page.rect.height, 1)}
    return ExtractedPage(number, data, None)


def _image_share(page: pymupdf.Page) -> float:
    """How much of the page images cover. A logo is small, and a chart or photo isn't."""
    covered = sum(
        abs(pymupdf.Rect(image["bbox"]) & page.rect) for image in page.get_image_info()
    )
    return covered / max(abs(page.rect), 1)


def _lines(page: pymupdf.Page, table_boxes: list[pymupdf.Rect]) -> list[dict[str, Any]]:
    lines = []
    blocks = page.get_text("dict", sort=True, flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
    for index, block in enumerate(blocks):
        for line in block.get("lines", []):
            spans = [span for span in line["spans"] if span["text"].strip()]
            if not spans:
                continue
            box = pymupdf.Rect(line["bbox"])
            middle = pymupdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
            if any(middle in table for table in table_boxes):
                continue
            lines.append(
                {
                    "text": "".join(span["text"] for span in line["spans"]).strip(),
                    "bbox": [round(v, 1) for v in line["bbox"]],
                    "size": round(max(span["size"] for span in spans), 1),
                    "bold": all(span["flags"] & BOLD_FLAG for span in spans),
                    "block": index,
                }
            )
    return lines


def _table_rows(page: pymupdf.Page) -> tuple[list[dict[str, Any]], list[pymupdf.Rect]]:
    rows: list[dict[str, Any]] = []
    boxes: list[pymupdf.Rect] = []
    tables = page.find_tables().tables
    verticals = _vertical_rules(page) if tables else []
    for table in tables:
        if table.col_count < 2 or len(table.rows) < 2:
            continue  # A box drawn around text, not a real table.
        if not _has_ruled_columns(table, verticals):
            continue  # Columns guessed from text. A wrong guess would label amounts wrongly.
        boxes.append(pymupdf.Rect(table.bbox))
        names = [_clean(_cell_text(page, cell)) for cell in table.rows[0].cells]
        previous: list[str | None] = [None] * len(names)
        for row in table.rows[1:]:
            # A cell merged from the row above has no box of its own.
            filled = [
                prev if cell is None else _cell_text(page, cell)
                for cell, prev in zip(row.cells, previous)
            ]
            previous = filled
            text = _row_text(names, filled)
            if text:
                rows.append({"text": text, "bbox": [round(v, 1) for v in row.bbox]})
    return rows, boxes


def _vertical_rules(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """Each vertical edge drawn on the page, as (x, top, bottom)."""
    rules = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l" and abs(item[1].x - item[2].x) <= RULE_TOLERANCE:
                rules.append((item[1].x, min(item[1].y, item[2].y), max(item[1].y, item[2].y)))
            elif item[0] == "re":
                rect = item[1]
                rules += [(rect.x0, rect.y0, rect.y1), (rect.x1, rect.y0, rect.y1)]
    return rules


def _has_ruled_columns(table, verticals: list[tuple[float, float, float]]) -> bool:
    x0, top, x1, bottom = table.bbox
    inner = {round(cell[0], 1) for cell in table.cells if cell and cell[0] > x0 + RULE_TOLERANCE}
    return bool(inner) and all(
        any(
            abs(x - rule_x) <= RULE_TOLERANCE and rule_top < bottom and rule_bottom > top
            for rule_x, rule_top, rule_bottom in verticals
        )
        for x in inner
    )


def _cell_text(page: pymupdf.Page, cell: tuple[float, ...] | None) -> str | None:
    # Read each cell from the page's own text. PyMuPDF's Table.extract() can move punctuation,
    # turning "Rs. 2,50,000" into "Rs 2 50 000 . , ,", and amounts must survive exactly.
    return None if cell is None else page.get_text("text", clip=pymupdf.Rect(cell))


def _row_text(names: list[str], values: list[str | None]) -> str:
    parts = []
    for name, value in zip(names, values):
        cleaned = _clean(value)
        if cleaned:
            parts.append(f"{name}: {cleaned}" if name else cleaned)
    return "; ".join(parts)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())
