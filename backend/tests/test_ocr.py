"""OCR: engine adapters, scanned-page detection, the OCR step and its honesty flags.

Most tests use a fake engine, so they run without Tesseract or PaddleOCR. The real-engine tests at
the bottom run only where the engine is installed (see docs/ocr_steps.md).
"""

import os
import shutil
import uuid

import pymupdf
import pytest

from app.config import get_settings
from app.models import Case, CaseDocument
from app.services import documents, ocr
from app.services.evidence import build_flags
from eval.samples import SAMPLES, make_pdf
from eval.scans import make_scanned_pdf

RECEIPT = SAMPLES["advance_receipt.pdf"]


class FakeEngine:
    name = "fake"

    def __init__(self, text: str = RECEIPT[0], confidence: float | None = 90.0, error: Exception | None = None):
        self.text, self.confidence, self.error = text, confidence, error

    def read(self, image):
        if self.error:
            raise self.error
        return ocr.OcrResult(self.text, self.confidence, self.name)


def _scanned_doc(pdf: bytes) -> CaseDocument:
    doc = documents.add_document(Case(id=uuid.uuid4(), user_id="u"), "scan.pdf", pdf)
    doc.id = uuid.uuid4()
    return doc


def _mixed_pdf() -> bytes:
    """Page 1 typed (selectable text), page 2 a scanned annexure."""
    out = pymupdf.open(stream=make_pdf(SAMPLES["agreement_to_sell.pdf"][:1]), filetype="pdf")
    out.insert_pdf(pymupdf.open(stream=make_scanned_pdf(RECEIPT), filetype="pdf"))
    return out.tobytes()


@pytest.fixture(autouse=True)
def engine_installed(monkeypatch):
    monkeypatch.setattr(ocr, "get_engine", lambda: FakeEngine())


# ---------- Engine adapters (no engine needed) ----------


def test_tesseract_lines_and_confidence_from_image_to_data():
    data = {
        "text": ["", "Received", "Rs.", "5,50,000/-", "", "Survey", "No.", "123/A"],
        "conf": [-1, 96, 91, 80, -1, 95, 90, 70],
        "block_num": [1, 1, 1, 1, 2, 2, 2, 2],
        "par_num": [1, 1, 1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 1, 1, 1, 1, 1],
    }
    text, confidence = ocr.tesseract_text(data)
    assert text == "Received Rs. 5,50,000/-\n\nSurvey No. 123/A"
    assert confidence == pytest.approx((96 + 91 + 80 + 95 + 90 + 70) / 6)


def test_paddle_results_in_3x_and_2x_formats():
    v3 = [{"rec_texts": ["RECEIPT", "Rs. 5,50,000/-", " "], "rec_scores": [0.99, 0.87, 0.5]}]
    v2 = [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("RECEIPT", 0.98)], [[[0, 2]], ("123/A", 0.81)]]]
    assert ocr.paddle_lines(v3) == [("RECEIPT", 0.99), ("Rs. 5,50,000/-", 0.87)]
    assert ocr.paddle_lines(v2) == [("RECEIPT", 0.98), ("123/A", 0.81)]
    assert ocr.paddle_lines([None]) == []


def test_engine_selection(monkeypatch):
    monkeypatch.undo()  # use the real get_engine
    settings = get_settings()
    monkeypatch.setattr(ocr, "_available", lambda name: name == "paddle")
    monkeypatch.setattr(settings, "ocr_engine", "auto")
    assert ocr.get_engine().name == "paddle"  # Tesseract missing, PaddleOCR installed
    monkeypatch.setattr(settings, "ocr_engine", "tesseract")
    assert ocr.get_engine() is None
    monkeypatch.setattr(settings, "ocr_enabled", False)
    monkeypatch.setattr(settings, "ocr_engine", "auto")
    assert ocr.get_engine() is None


def test_render_size_is_capped_for_large_photos():
    big = pymupdf.open()
    big.new_page(width=4000, height=3000)  # a 12 MP photo becomes a page this size
    image = ocr.render_page(big[0], dpi=300)
    assert max(image.size) <= ocr.MAX_RENDER_PX


# ---------- Detection and pipeline ----------


def test_only_scanned_pages_are_queued_for_ocr():
    assert documents.read_pdf(make_pdf(RECEIPT)).ocr_needed == []
    assert documents.read_pdf(make_scanned_pdf(RECEIPT)).ocr_needed == [0]
    mixed = documents.read_pdf(_mixed_pdf())
    assert mixed.ocr_needed == [1] and "Survey No. 123/4" in mixed.pages[0]


def test_photo_becomes_a_one_page_pdf():
    from eval.scans import make_photo

    for fmt in ("JPEG", "PNG"):
        pdf = documents.prepare_upload(make_photo("a receipt", fmt))
        assert documents.read_pdf(pdf).ocr_needed == [0]
    with pytest.raises(documents.DocumentError) as e:
        documents.prepare_upload(b"GIF89a....")
    assert e.value.code == "not_pdf"


def test_ocr_fills_scanned_pages_and_keeps_typed_ones():
    pdf = _mixed_pdf()
    doc = _scanned_doc(pdf)
    assert doc.status == "processing" and documents.needs_ocr(doc)
    documents.run_ocr(doc, pdf, engine=FakeEngine())
    assert [p["source"] for p in doc.page_info] == ["text", "ocr"]
    assert doc.page_info[1] == {"source": "ocr", "engine": "fake", "confidence": 90.0}
    assert "123/A" in doc.pages[1] and "123/4" in doc.pages[0]
    assert doc.status == "processing"  # ready for fact extraction


def test_low_confidence_and_unread_pages_are_flagged():
    pdf = make_scanned_pdf(RECEIPT + RECEIPT)  # two scanned pages
    doc = _scanned_doc(pdf)

    class OneGoodOneBroken(FakeEngine):
        calls = 0

        def read(self, image):
            OneGoodOneBroken.calls += 1
            if OneGoodOneBroken.calls == 2:
                raise RuntimeError("tesseract timeout")
            return ocr.OcrResult(RECEIPT[0], 41.0, "fake")

    documents.run_ocr(doc, pdf, engine=OneGoodOneBroken())
    doc.status, doc.facts = "processed", {"document_type": "receipt"}
    flags = {f["kind"]: f for f in build_flags([doc])}
    assert "page 1" in flags["ocr_low_confidence"]["message"] and "41%" in flags["ocr_low_confidence"]["message"]
    assert flags["ocr_page_not_read"]["sources"][0]["page"] == 2
    assert flags["ocr_used"]["sources"][0]["from_ocr"] is True


def test_unreadable_scan_fails_without_inventing_text():
    pdf = make_scanned_pdf(RECEIPT)
    doc = _scanned_doc(pdf)
    documents.run_ocr(doc, pdf, engine=FakeEngine(text="  ~ .", confidence=12.0))
    assert doc.status == "failed" and doc.error == documents.UNREADABLE
    assert doc.pages == [""] and doc.page_info[0]["source"] == "ocr_unreadable"


def test_pages_beyond_the_ocr_limit_are_skipped(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_max_pages", 1)
    pdf = make_scanned_pdf(RECEIPT + RECEIPT)
    doc = _scanned_doc(pdf)
    documents.run_ocr(doc, pdf, engine=FakeEngine())
    assert [p["source"] for p in doc.page_info] == ["ocr", "ocr_skipped"]


# ---------- Real engines (only where installed) ----------

# Values a clean scan must get exactly right. Names are scored by eval/run_ocr_eval.py instead:
# real engines make classic slips there (PaddleOCR read "Iyer" as "lyer" on 2026-10-31).
KEY_VALUES = ["123/A", "5,50,000", "15/03/2023", "Kulkarni"]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed (brew install tesseract tesseract-lang)")
def test_tesseract_reads_a_clean_scan():
    engine = ocr.TesseractEngine()
    if not engine.available():
        pytest.skip("Tesseract language packs missing")
    page = pymupdf.open(stream=make_scanned_pdf(RECEIPT), filetype="pdf")[0]
    result = engine.read(ocr.render_page(page))
    assert all(v in result.text for v in KEY_VALUES), result.text
    assert result.confidence and result.confidence > 60


@pytest.mark.skipif(os.environ.get("RUN_PADDLE_TESTS") != "1", reason="set RUN_PADDLE_TESTS=1 (downloads models on first run)")
def test_paddle_reads_a_clean_scan():
    engine = ocr.PaddleEngine()
    if not engine.available():
        pytest.skip("PaddleOCR not installed (uv sync --extra paddle)")
    page = pymupdf.open(stream=make_scanned_pdf(RECEIPT), filetype="pdf")[0]
    result = engine.read(ocr.render_page(page))
    assert all(v.replace(" ", "") in result.text.replace(" ", "") for v in KEY_VALUES), result.text


# ---------- Benchmark scoring ----------


def test_error_rates_and_recommendation():
    from eval.run_ocr_eval import edit_distance, error_rates, recommend

    assert edit_distance("kitten", "sitting") == 3
    cer, wer = error_rates("Survey No. 123/A", "Survey No. 123/4")
    assert cer == pytest.approx(1 / 16) and wer == pytest.approx(1 / 3)
    rows = [
        {"engine": "tesseract", "dataset": "english", "quality": "photo", "key_value_recall": 0.7, "cer": 0.08, "seconds_per_page": 1.0},
        {"engine": "paddle", "dataset": "english", "quality": "photo", "key_value_recall": 0.9, "cer": 0.03, "seconds_per_page": 2.0},
    ]
    assert "recommended paddle" in recommend(rows)
    rows[1]["seconds_per_page"] = 9.0
    assert "slower" in recommend(rows)
    rows[1]["key_value_recall"] = 0.7  # same key values: the lower CER wins
    rows[1]["seconds_per_page"] = 2.0
    assert "recommended paddle" in recommend(rows)
