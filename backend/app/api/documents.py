import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from sqlalchemy import select

from app.api.deps import DB, User, UserCase
from app.models import Case, CaseDocument
from app.schemas import BriefOut, DocumentOut, DocumentSummaryOut, EvidenceOut, LibraryDocumentOut
from app.services import brief, documents, evidence, glossary, understanding

router = APIRouter(prefix="/cases/{case_id}", tags=["documents"])

ERROR_STATUS = {"too_large": 413, "not_pdf": 415}


def _summary(doc: CaseDocument) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "error": doc.error,
        "document_type": doc.facts.get("document_type") if doc.facts else None,
        "page_count": len(doc.pages or []),
        "ocr_pages": sum(1 for p in doc.page_info or [] if p.get("source") == "ocr"),
        "understood": (doc.understanding or {}).get("en", {}).get("status") == "complete",
        "language": glossary.detect_language(" ".join(doc.pages or [])) if doc.pages else None,
        "created_at": doc.created_at,
    }


def _detail(doc: CaseDocument) -> dict:
    return {**_summary(doc), "pages": doc.pages or [], "page_info": doc.page_info or [], "facts": doc.facts or {}}


def _get_document(case: Case, document_id: uuid.UUID) -> CaseDocument:
    for doc in case.documents:
        if doc.id == document_id:
            return doc
    raise HTTPException(404, "Document not found")


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile, case: UserCase, db: DB, background: BackgroundTasks):
    """Upload a PDF, or a JPG/PNG photo. Selectable text is read page by page straight away; scanned
    pages are OCR'd and candidate facts with page references extracted in the background (status
    `processing` until done; poll the document).

    Unusable PDFs (scanned, encrypted, damaged) are stored with status `failed` and the reason, so they
    appear in the brief. Non-PDFs and oversized files are rejected and not stored.
    """
    data = await file.read(documents.MAX_UPLOAD_BYTES + 1)
    try:
        pdf = documents.prepare_upload(data)  # photos become a one-page PDF
        doc = documents.add_document(case, file.filename or "document.pdf", pdf)
    except documents.DocumentError as e:
        raise HTTPException(ERROR_STATUS.get(e.code, 422), e.message)
    db.commit()
    if doc.status == "processing":
        # The PDF goes to the background task in memory only (for OCR); it is never stored.
        background.add_task(documents.extract_in_background, doc.id, pdf if documents.needs_ocr(doc) else None)
    return _detail(doc)


@router.get("/documents", response_model=list[DocumentSummaryOut])
def list_documents(case: UserCase):
    return [_summary(d) for d in case.documents]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, case: UserCase):
    return _detail(_get_document(case, document_id))


@router.post("/documents/{document_id}/extract", response_model=DocumentOut)
def retry_extraction(document_id: uuid.UUID, case: UserCase, db: DB, background: BackgroundTasks):
    """Re-run fact extraction in the background, e.g. after it failed because the AI service was busy."""
    doc = documents.mark_for_retry(_get_document(case, document_id))
    db.commit()
    if doc.status == "processing":
        background.add_task(documents.extract_in_background, doc.id)
    return _detail(doc)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, case: UserCase, db: DB):
    """Delete the document and its extracted text and facts."""
    case.documents.remove(_get_document(case, document_id))
    db.commit()


@router.get("/evidence", response_model=EvidenceOut)
def get_evidence(case: UserCase):
    """Chronology and possible gaps/conflicts across the uploaded documents, each linked to its source page."""
    out = evidence.build_evidence(case.documents)
    out["flags"] = brief.conflict_flags(case) + out["flags"]  # user-vs-document conflicts first
    return out


@router.post("/brief", response_model=BriefOut)
def create_brief(case: UserCase):
    """Generate a draft case-preparation brief. It is returned for review only; nothing is sent anywhere."""
    return brief.build_brief(case)


@router.get("/documents/{document_id}/understanding")
def get_understanding(
    document_id: uuid.UUID, case: UserCase, db: DB, lang: str = Query("en", pattern="^(en|hi|hinglish)$")
):
    """Plain-language explanation of the document: summary, clauses, legal terms, things to check.
    Cached per language; generated on first request for a language (one fast-model call)."""
    doc = _get_document(case, document_id)
    if doc.status != "processed":
        raise HTTPException(409, "The document is still being read, or couldn't be processed.")
    result = understanding.ensure_understanding(doc, lang)
    db.commit()
    return result


@router.post("/documents/{document_id}/understanding/regenerate")
def regenerate_understanding(
    document_id: uuid.UUID, case: UserCase, db: DB, lang: str = Query("en", pattern="^(en|hi|hinglish)$")
):
    doc = _get_document(case, document_id)
    if doc.status != "processed":
        raise HTTPException(409, "The document is still being read, or couldn't be processed.")
    result = understanding.ensure_understanding(doc, lang, refresh=True)
    db.commit()
    return result


# ---------- Across cases ----------

library = APIRouter(tags=["documents"])


@library.get("/documents", response_model=list[LibraryDocumentOut])
def all_documents(db: DB, user: User, limit: int = Query(100, le=500), offset: int = 0):
    """All of the user's documents across cases, newest first ("All my documents")."""
    rows = db.execute(
        select(CaseDocument, Case.title)
        .join(Case, Case.id == CaseDocument.case_id)
        .where(Case.user_id == user)
        .order_by(CaseDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {**_summary(doc), "case_id": doc.case_id, "case_title": title}
        for doc, title in rows
    ]


@library.get("/glossary")
def glossary_terms():
    """The curated legal glossary (plain-language meanings of property-law terms)."""
    return list(glossary.glossary().values())


@library.get("/glossary/{term_id}")
def glossary_term(term_id: str):
    entry = glossary.glossary().get(term_id)
    if entry is None:
        raise HTTPException(404, "Unknown term")
    return entry
