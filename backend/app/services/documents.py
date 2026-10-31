"""Uploaded case documents: PDF -> page text -> candidate facts with checked page references.

Nothing is ever made up to replace a failed step: a PDF without usable text is stored as `failed`
with the reason, and a document whose fact extraction failed keeps its text as `text_only`.

Text extraction is instant and happens during the upload; the slower steps run in the background
(status `processing`), so the upload returns straight away and the app polls:
  1. OCR of scanned pages and photos (app/services/ocr.py). The PDF bytes are passed to the
     background task in memory only and are never stored, keeping "only extracted text is kept".
  2. LLM fact extraction.

`page_info` records, per page, where its text came from: "text" (selectable), "ocr" (with engine
and confidence), or why it has none: "ocr_pending", "ocr_unavailable", "ocr_unreadable",
"ocr_failed", "ocr_skipped" (over OCR_MAX_PAGES).
"""

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import openai
import pymupdf

from app.config import get_settings
from app.db import SessionLocal
from app.llm import prompts
from app.llm.client import LLMRefusal, structured
from app.llm.schemas import DocumentFacts
from app.models import Case, CaseDocument
from app.services import nlp, ocr

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 60
MIN_TEXT_CHARS = 20  # less than this in the whole PDF almost always means a scanned image
MAX_LLM_CHARS = 120_000  # ~30k tokens of document text per extraction call
ISO_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class DocumentError(Exception):
    """A PDF that can't be used. `code` is stable for the app; `message` is shown to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


NOT_SUPPORTED = "Only PDF, JPG or PNG files are supported."
NO_OCR = "No selectable text was found. This looks like a scanned document, and OCR isn't available on this server."
UNREADABLE = "The scan is too unclear to read. Try a sharper photo or scan (300 dpi, good light, flat page)."


def check_upload(data: bytes) -> None:
    """Reject uploads that shouldn't be stored at all (wrong type, too big)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("too_large", f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if b"%PDF-" not in data[:1024]:
        raise DocumentError("not_pdf", NOT_SUPPORTED)


def prepare_upload(data: bytes) -> bytes:
    """The upload as PDF bytes: PDFs pass through, JPG/PNG photos become a one-page PDF."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("too_large", f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if data[:3] == b"\xff\xd8\xff":
        kind = "jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        kind = "png"
    else:
        check_upload(data)
        return data
    try:
        with pymupdf.open(stream=data, filetype=kind) as image:
            return image.convert_to_pdf()
    except Exception as e:
        raise DocumentError("malformed", "The image could not be opened; it may be damaged.") from e


@dataclass
class PdfText:
    pages: list[str]  # selectable text per page (empty for scanned pages until OCR)
    ocr_needed: list[int]  # 0-based indexes of pages that look scanned


def read_pdf(data: bytes) -> PdfText:
    """Validate the PDF and read its selectable text; scanned pages are listed for OCR."""
    check_upload(data)
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # pymupdf raises several types for damaged files
        raise DocumentError("malformed", "The PDF could not be opened; it may be damaged.") from e
    with doc:
        if doc.needs_pass:
            raise DocumentError("encrypted", "The PDF is password-protected. Remove the password and upload it again.")
        if doc.page_count == 0:
            raise DocumentError("malformed", "The PDF has no pages.")
        if doc.page_count > MAX_PAGES:
            raise DocumentError("too_many_pages", f"The PDF has more than {MAX_PAGES} pages.")
        try:
            pages = [page.get_text() for page in doc]
            ocr_needed = [i for i, page in enumerate(doc) if ocr.page_needs_ocr(page, pages[i])]
        except Exception as e:
            raise DocumentError("malformed", "Text could not be read from the PDF; it may be damaged.") from e
    if not ocr_needed and _total_text(pages) < MIN_TEXT_CHARS:
        raise DocumentError("no_text", "No text was found in this PDF.")
    return PdfText(pages, ocr_needed)


def extract_pages(data: bytes) -> list[str]:
    """Selectable text of each page (index 0 = page 1), without OCR. Raises DocumentError if there is none."""
    scan = read_pdf(data)
    if _total_text(scan.pages) < MIN_TEXT_CHARS:
        raise DocumentError("no_text", NO_OCR)
    return scan.pages


def _total_text(pages: list[str]) -> int:
    return sum(len(p.strip()) for p in pages)


def run_ocr(doc: CaseDocument, pdf: bytes, engine: ocr.OcrEngine | None = None) -> None:
    """OCR the document's pending pages in place. Marks the document failed if no usable text results."""
    engine = engine or ocr.get_engine()
    settings = get_settings()
    pages, info = list(doc.pages), [dict(i) for i in doc.page_info]
    pending = [i for i, p in enumerate(info) if p.get("source") == "ocr_pending"]
    if engine is None:
        for i in pending:
            info[i] = {"source": "ocr_unavailable"}
    else:
        with pymupdf.open(stream=pdf, filetype="pdf") as pdf_doc:
            for count, i in enumerate(pending):
                if count >= settings.ocr_max_pages:
                    info[i] = {"source": "ocr_skipped"}
                    continue
                try:
                    result = engine.read(ocr.render_page(pdf_doc[i]))
                except Exception as e:  # engine crash or timeout on one page shouldn't lose the rest
                    log.warning("OCR failed on page %d of document %s: %s", i + 1, doc.id, type(e).__name__)
                    info[i] = {"source": "ocr_failed", "engine": engine.name}
                    continue
                confidence = round(result.confidence, 1) if result.confidence is not None else None
                if len(result.text.strip()) < ocr.MIN_PAGE_CHARS:
                    info[i] = {"source": "ocr_unreadable", "engine": result.engine, "confidence": confidence}
                    continue
                pages[i] = result.text
                info[i] = {"source": "ocr", "engine": result.engine, "confidence": confidence}
    doc.pages, doc.page_info = pages, info  # new lists so the JSONB columns are saved
    if _total_text(pages) < MIN_TEXT_CHARS:
        doc.status, doc.error = "failed", (NO_OCR if engine is None else UNREADABLE)


# ---------- Source checking ----------


def _normalise(text: str) -> str:
    """Lowercase letters and digits only, so line breaks and punctuation from PDF extraction don't matter."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", "", text)


def excerpt_on_page(excerpt: str, pages: list[str], page: int) -> bool:
    if not 1 <= page <= len(pages):
        return False
    needle = _normalise(excerpt)
    return len(needle) >= 3 and needle in _normalise(pages[page - 1])


def verify_sources(node, pages: list[str]):
    """Add `verified` to every source reference ({page, excerpt}) in the extracted facts, in place."""
    if isinstance(node, dict):
        if "page" in node and "excerpt" in node:
            node["verified"] = excerpt_on_page(node.get("excerpt") or "", pages, node.get("page") or 0)
        for value in node.values():
            verify_sources(value, pages)
    elif isinstance(node, list):
        for item in node:
            verify_sources(item, pages)
    return node


def _clean_dates(facts: dict) -> None:
    """Dates must be ISO; anything else is dropped (the wording is kept in `date_as_written`)."""
    if facts.get("document_date") and not ISO_DATE_RE.match(facts["document_date"]):
        facts["document_date"] = None
    for event in facts.get("events", []):
        if event.get("date") and not ISO_DATE_RE.match(event["date"]):
            event["date"] = None


# ---------- Fact extraction ----------


def _document_prompt(filename: str, pages: list[str]) -> tuple[str, int | None]:
    """The pages as tagged text, cut off at MAX_LLM_CHARS. Returns (prompt, last page included if truncated)."""
    parts, total = [], 0
    for n, text in enumerate(pages, start=1):
        if total + len(text) > MAX_LLM_CHARS and parts:
            return _wrap(filename, parts), n - 1
        parts.append(f'<page number="{n}">\n{text}\n</page>')
        total += len(text)
    return _wrap(filename, parts), None


def _wrap(filename: str, parts: list[str]) -> str:
    return f'<document filename="{filename}">\n' + "\n".join(parts) + "\n</document>"


def extract_facts(filename: str, pages: list[str]) -> dict:
    """LLM extraction validated against DocumentFacts, then checked in code: dates, page references
    (quotes must exist on the cited page), and rule-based NLP (app/services/nlp.py), which marks
    amounts/dates/identifiers it also found as `corroborated` and lists what the LLM missed."""
    user_prompt, truncated_after = _document_prompt(filename, pages)
    facts = structured(
        DocumentFacts, prompts.DOCUMENT_EXTRACTION_SYSTEM, user_prompt, model=get_settings().model_fast
    ).model_dump()
    _clean_dates(facts)
    verify_sources(facts, pages)
    nlp.cross_check(facts, pages)
    facts["truncated_after_page"] = truncated_after
    return facts


def _run_extraction(doc: CaseDocument) -> None:
    try:
        doc.facts = extract_facts(doc.filename, doc.pages)
        doc.status, doc.error = "processed", None
    except (openai.APIError, LLMRefusal, RuntimeError) as e:
        # Logged without document content.
        log.warning("fact extraction failed for document %s: %s", doc.id, type(e).__name__)
        doc.status = "text_only"
        doc.error = "Text was extracted, but fact extraction failed. Try again later."


def add_document(case: Case, filename: str, data: bytes) -> CaseDocument:
    """Process an upload and attach it to the case. Raises DocumentError for files that aren't stored."""
    check_upload(data)
    doc = CaseDocument(
        id=uuid.uuid4(),
        filename=filename[:200] or "document.pdf",
        pages=[],
        page_info=[],
        facts={},
        created_at=datetime.now(timezone.utc),
    )
    try:
        scan = read_pdf(data)
    except DocumentError as e:
        doc.status, doc.error = "failed", e.message
    else:
        doc.pages = scan.pages
        doc.page_info = [{"source": "ocr_pending" if i in scan.ocr_needed else "text"} for i in range(len(scan.pages))]
        doc.status = "processing"  # OCR (if needed) and facts are done by extract_in_background
        if scan.ocr_needed and ocr.get_engine() is None:
            doc.page_info = [{"source": "ocr_unavailable"} if i in scan.ocr_needed else p for i, p in enumerate(doc.page_info)]
            if _total_text(scan.pages) < MIN_TEXT_CHARS:
                doc.status, doc.error = "failed", NO_OCR
    case.documents.append(doc)
    return doc


def needs_ocr(doc: CaseDocument) -> bool:
    return any(p.get("source") == "ocr_pending" for p in doc.page_info or [])


def mark_for_retry(doc: CaseDocument) -> CaseDocument:
    if doc.pages:
        doc.status, doc.error = "processing", None
    return doc


def extract_in_background(document_id: uuid.UUID, pdf: bytes | None = None) -> None:
    """OCR (when `pdf` is given) and fact extraction for an uploaded document, in its own DB session."""
    with SessionLocal() as db:
        doc = db.get(CaseDocument, document_id)
        if doc is None or doc.status != "processing":
            return
        processed = False
        try:
            if pdf is not None and needs_ocr(doc):
                run_ocr(doc, pdf)
            if doc.status == "processing":
                _run_extraction(doc)
            processed = doc.status == "processed"
            if processed:
                from app.services import understanding  # imported here: understanding imports this module

                try:  # the explanation is extra: a failure here must not fail the document
                    understanding.ensure_understanding(doc, "en")
                except Exception:
                    log.exception("document understanding crashed for %s", document_id)
        except Exception:  # never leave a document stuck in `processing`
            log.exception("fact extraction crashed for document %s", document_id)
            doc.status, doc.error = "text_only", "Fact extraction failed. Try again."
        db.commit()
        if processed:  # fold the new facts into the case's fact sheet
            from app.services import intake  # imported here: intake imports this module's helpers

            intake.refresh_after_document(db, doc.case_id)


def recover_interrupted(db) -> None:
    """At startup: documents left `processing` by a restart can be retried by the user."""
    for doc in db.query(CaseDocument).filter(CaseDocument.status == "processing"):
        if needs_ocr(doc):  # the file isn't stored, so OCR can't resume
            doc.status, doc.error = "failed", "Processing was interrupted. Please upload the document again."
        else:
            doc.status, doc.error = "text_only", "Processing was interrupted. Try extraction again."
    db.commit()
