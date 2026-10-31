"""PDF validation, page extraction and source checking (no database or API key needed)."""

import pymupdf
import pytest

from app.services import documents
from app.services.documents import DocumentError, excerpt_on_page, extract_pages, verify_sources
from eval.samples import SAMPLES, make_pdf


def _error_code(data: bytes) -> str:
    with pytest.raises(DocumentError) as e:
        extract_pages(data)
    return e.value.code


def test_extracts_text_page_by_page():
    pages = extract_pages(make_pdf(SAMPLES["agreement_to_sell.pdf"]))
    assert len(pages) == 2
    assert "Survey No. 123/4" in pages[0]
    assert "15 September 2023" in pages[1]


def test_rejects_non_pdf():
    assert _error_code(b"hello, not a pdf") == "not_pdf"


def test_rejects_oversized(monkeypatch):
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 100)
    assert _error_code(make_pdf(["x" * 50])) == "too_large"


def test_malformed_pdf():
    assert _error_code(b"%PDF-1.7\nthis is not really a pdf") == "malformed"


def test_scanned_or_blank_pdf_has_no_text():
    doc = pymupdf.open()
    doc.new_page()
    assert _error_code(doc.tobytes()) == "no_text"


def test_encrypted_pdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret agreement text")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    assert _error_code(data) == "encrypted"


def test_excerpt_matching_ignores_line_breaks_and_punctuation():
    pages = ["The total sale consideration is Rs. 45,00,000/-\n(Rupees Forty Five Lakh only)."]
    assert excerpt_on_page("consideration is Rs 45,00,000 (Rupees Forty", pages, 1)
    assert not excerpt_on_page("consideration is Rs 50,00,000", pages, 1)
    assert not excerpt_on_page("total sale consideration", pages, 2)  # page out of range
    assert not excerpt_on_page("", pages, 1)


def test_verify_sources_marks_every_reference():
    pages = ["Seller: Ravi Kulkarni", "Advance Rs. 5,00,000"]
    facts = {
        "parties": [{"name": "Ravi Kulkarni", "source": {"page": 1, "excerpt": "Seller: Ravi Kulkarni"}}],
        "amounts": [{"value": "Rs. 5,00,000", "source": {"page": 1, "excerpt": "Advance Rs. 5,00,000"}}],
        "document_date_source": None,
    }
    verify_sources(facts, pages)
    assert facts["parties"][0]["source"]["verified"] is True
    assert facts["amounts"][0]["source"]["verified"] is False  # quoted from the wrong page


def test_failed_pdf_is_stored_with_reason_and_no_fabricated_text():
    from app.models import Case

    case = Case(user_id="u", fact_sheet={})
    blank = pymupdf.open()
    blank.new_page()
    doc = documents.add_document(case, "blank.pdf", blank.tobytes())
    assert doc.status == "failed" and "No text" in doc.error
    assert doc.pages == [] and doc.facts == {}


def test_scan_without_ocr_engine_fails_clearly(monkeypatch):
    from app.models import Case
    from eval.scans import make_scanned_pdf

    monkeypatch.setattr(documents.ocr, "get_engine", lambda: None)
    doc = documents.add_document(Case(user_id="u"), "scan.pdf", make_scanned_pdf(SAMPLES["advance_receipt.pdf"]))
    assert doc.status == "failed" and "OCR isn't available" in doc.error
    assert doc.page_info == [{"source": "ocr_unavailable"}] and doc.facts == {}


def test_llm_failure_keeps_text(monkeypatch):
    from app.models import Case

    def boom(*args, **kwargs):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(documents, "structured", boom)
    doc = documents.add_document(Case(user_id="u"), "a.pdf", make_pdf(SAMPLES["advance_receipt.pdf"]))
    assert doc.status == "processing" and "123/A" in doc.pages[0]  # text is ready before facts
    documents._run_extraction(doc)
    assert doc.status == "text_only"
    assert "123/A" in doc.pages[0]


def test_invalid_dates_are_dropped_but_wording_kept():
    facts = {"document_date": "15th March", "events": [{"date": "March 2023", "date_as_written": "March 2023"}]}
    documents._clean_dates(facts)
    assert facts["document_date"] is None
    assert facts["events"][0] == {"date": None, "date_as_written": "March 2023"}
