"""Uploaded case documents: PDF -> page text -> candidate facts with checked page references.

Nothing is ever made up to replace a failed step: a PDF without usable text is stored as `failed`
with the reason, and a document whose fact extraction failed keeps its text as `text_only`.

Text extraction is instant and happens during the upload; the slower LLM fact extraction runs in
the background (status `processing`), so the upload returns straight away and the app polls.
"""

import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import openai
import pymupdf

from app.config import get_settings
from app.db import SessionLocal
from app.llm import prompts
from app.llm.client import LLMRefusal, structured
from app.llm.schemas import DocumentFacts
from app.models import Case, CaseDocument

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


def check_upload(data: bytes) -> None:
    """Reject uploads that shouldn't be stored at all (wrong type, too big)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("too_large", f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if b"%PDF-" not in data[:1024]:
        raise DocumentError("not_pdf", "Only PDF files are supported.")


def extract_pages(data: bytes) -> list[str]:
    """Text of each page (index 0 = page 1). Raises DocumentError if the PDF has no usable text."""
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
        except Exception as e:
            raise DocumentError("malformed", "Text could not be read from the PDF; it may be damaged.") from e
    if sum(len(p.strip()) for p in pages) < MIN_TEXT_CHARS:
        raise DocumentError(
            "no_text",
            "No selectable text was found. This looks like a scanned document; OCR is not supported yet.",
        )
    return pages


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
    """LLM extraction validated against DocumentFacts, then dates and page references checked in code."""
    user_prompt, truncated_after = _document_prompt(filename, pages)
    facts = structured(
        DocumentFacts, prompts.DOCUMENT_EXTRACTION_SYSTEM, user_prompt, model=get_settings().model_fast
    ).model_dump()
    _clean_dates(facts)
    verify_sources(facts, pages)
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
        facts={},
        created_at=datetime.now(timezone.utc),
    )
    try:
        doc.pages = extract_pages(data)
    except DocumentError as e:
        doc.status, doc.error = "failed", e.message
    else:
        doc.status = "processing"  # facts are extracted by extract_in_background
    case.documents.append(doc)
    return doc


def mark_for_retry(doc: CaseDocument) -> CaseDocument:
    if doc.pages:
        doc.status, doc.error = "processing", None
    return doc


def extract_in_background(document_id: uuid.UUID) -> None:
    """Run fact extraction for an uploaded document in its own database session."""
    with SessionLocal() as db:
        doc = db.get(CaseDocument, document_id)
        if doc is None or doc.status != "processing":
            return
        try:
            _run_extraction(doc)
        except Exception:  # never leave a document stuck in `processing`
            log.exception("fact extraction crashed for document %s", document_id)
            doc.status, doc.error = "text_only", "Fact extraction failed. Try again."
        db.commit()


def recover_interrupted(db) -> None:
    """At startup: documents left `processing` by a restart can be retried by the user."""
    for doc in db.query(CaseDocument).filter(CaseDocument.status == "processing"):
        doc.status, doc.error = "text_only", "Processing was interrupted. Try extraction again."
    db.commit()
