from dataclasses import dataclass

import pymupdf


class PdfRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PdfInfo:
    page_count: int


def validate_pdf(content: bytes) -> PdfInfo:
    if not content.startswith(b"%PDF-"):
        raise PdfRejected("PDF_INVALID", "This file isn't a valid PDF.")
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise PdfRejected("PDF_INVALID", "This PDF couldn't be opened.") from exc
    with document:
        if document.needs_pass:
            raise PdfRejected("PDF_ENCRYPTED", "This PDF is password protected.")
        if document.page_count < 1:
            raise PdfRejected("PDF_INVALID", "This PDF has no pages.")
        return PdfInfo(page_count=document.page_count)
