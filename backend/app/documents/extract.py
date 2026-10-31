from dataclasses import dataclass
from typing import Any

import pymupdf

from app.documents.garble import ocr_reason

MIN_DRAWINGS_FOR_VISUALS = 50
MIN_DRAWINGS_FOR_TABLE = 2
OCR_DPI = 200
BOLD_FLAG = 16


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
    reason = ocr_reason(text, fonts, visuals)
    if reason:
        return ExtractedPage(number, None, reason)
    # Table detection is the slowest step by far, and a table needs ruled lines to find.
    rows, table_boxes = _table_rows(page) if drawings >= MIN_DRAWINGS_FOR_TABLE else ([], [])
    data = {"lines": _lines(page, table_boxes), "rows": rows, "height": round(page.rect.height, 1)}
    return ExtractedPage(number, data, None)


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
    for table in page.find_tables().tables:
        if table.col_count < 2 or len(table.rows) < 2:
            continue  # A box drawn around text, not a real table.
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
