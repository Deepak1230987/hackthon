import pytest

from app.acquisition.validate import PdfRejected, validate_pdf
from tests.conftest import make_pdf


def test_accepts_real_pdf():
    assert validate_pdf(make_pdf()).page_count == 1


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"not a pdf at all", "PDF_INVALID"),
        (b"%PDF-1.7 but the rest is garbage", "PDF_INVALID"),
        (make_pdf(password="secret"), "PDF_ENCRYPTED"),
    ],
)
def test_rejects_bad_files(content, code):
    with pytest.raises(PdfRejected) as caught:
        validate_pdf(content)
    assert caught.value.code == code
