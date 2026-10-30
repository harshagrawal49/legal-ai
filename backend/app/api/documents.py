import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app.api.deps import DB, UserCase
from app.models import Case, CaseDocument
from app.schemas import BriefOut, DocumentOut, DocumentSummaryOut, EvidenceOut
from app.services import brief, documents, evidence

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
        "created_at": doc.created_at,
    }


def _detail(doc: CaseDocument) -> dict:
    return {**_summary(doc), "pages": doc.pages or [], "facts": doc.facts or {}}


def _get_document(case: Case, document_id: uuid.UUID) -> CaseDocument:
    for doc in case.documents:
        if doc.id == document_id:
            return doc
    raise HTTPException(404, "Document not found")


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile, case: UserCase, db: DB, background: BackgroundTasks):
    """Upload a PDF. Text is extracted page by page straight away; candidate facts with page references
    are extracted in the background (status `processing` until done; poll the document).

    Unusable PDFs (scanned, encrypted, damaged) are stored with status `failed` and the reason, so they
    appear in the brief. Non-PDFs and oversized files are rejected and not stored.
    """
    data = await file.read(documents.MAX_UPLOAD_BYTES + 1)
    try:
        doc = documents.add_document(case, file.filename or "document.pdf", data)
    except documents.DocumentError as e:
        raise HTTPException(ERROR_STATUS.get(e.code, 422), e.message)
    db.commit()
    if doc.status == "processing":
        background.add_task(documents.extract_in_background, doc.id)
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
    return evidence.build_evidence(case.documents)


@router.post("/brief", response_model=BriefOut)
def create_brief(case: UserCase):
    """Generate a draft case-preparation brief. It is returned for review only; nothing is sent anywhere."""
    return brief.build_brief(case)
