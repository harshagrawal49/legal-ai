"""Request/response bodies of the REST API (what the Android app sends and receives)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schemas import FactSheet


class NewCaseIn(BaseModel):
    # Optional: a case can start from documents alone; its fact sheet is then built from them.
    description: str = Field(default="", max_length=20000)


class IntakeAnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class FactSheetIn(BaseModel):
    fact_sheet: FactSheet


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    mentions: list[uuid.UUID] = Field(default_factory=list, max_length=5)  # documents referenced with @


class JudgmentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    court: str
    decision_date: date | None
    citation: str | None
    neutral_citation: str | None
    disposal: str | None
    source_url: str
    summary: dict


class CaseResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    relevance: int
    stance: str
    explanation: str
    similarities: list[str]
    differences: list[str]
    key_paragraphs: list[int]
    judgment: JudgmentBrief


class CaseSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    updated_at: datetime


class CaseOut(CaseSummaryOut):
    fact_sheet: dict
    pending_questions: list[str] = []
    results: list[CaseResultOut] = []


class ParagraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    para_no: int
    text: str


class JudgmentOut(JudgmentBrief):
    petitioner: str | None
    respondent: str | None
    judges: str | None
    paragraphs: list[ParagraphOut]


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    display_text: str
    created_at: datetime
    sources: list[dict] = []  # assistant replies: verified documents/pages and judgments cited
    mentions: list[str] = []  # user messages: document ids referenced with @


# ---------- Uploaded documents, evidence pack and brief ----------


class DocumentSummaryOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str  # processing | processed | text_only | failed
    error: str | None
    document_type: str | None
    page_count: int
    ocr_pages: int = 0  # pages whose text was read by OCR
    understood: bool = False  # a plain-language explanation is ready (GET .../understanding)
    language: str | None = None  # en | hi (detected from the text)
    created_at: datetime | None


class DocumentOut(DocumentSummaryOut):
    pages: list[str]
    page_info: list[dict] = []  # per page: {"source": "text" | "ocr" | ..., "engine", "confidence"}
    facts: dict


class LibraryDocumentOut(BaseModel):
    """One document in the user's library across all cases."""
    id: uuid.UUID
    case_id: uuid.UUID
    case_title: str
    filename: str
    status: str
    document_type: str | None
    page_count: int
    understood: bool
    created_at: datetime | None


class SourceRefOut(BaseModel):
    document_id: str
    filename: str
    page: int | None
    excerpt: str | None
    verified: bool
    from_ocr: bool = False  # the cited page was read by OCR, so check digits and names against the original
    value: str | None = None


class TimelineItemOut(BaseModel):
    date: str | None
    date_as_written: str | None
    kind: str
    description: str
    source: SourceRefOut


class FlagOut(BaseModel):
    kind: str
    message: str
    sources: list[SourceRefOut]


class EvidenceOut(BaseModel):
    timeline: list[TimelineItemOut]
    flags: list[FlagOut]


class SupportedFactOut(BaseModel):
    category: str
    text: str
    source: SourceRefOut


class LegalSourceOut(BaseModel):
    judgment_id: str
    title: str
    court: str
    decision_date: str | None
    citation: str | None
    source_url: str
    why_it_may_matter: str
    key_paragraphs: list[int]


class BriefDocumentOut(BaseModel):
    document_id: str
    filename: str
    status: str
    document_type: str | None
    page_count: int
    error: str | None
    ocr_pages: int = 0
    ocr_confidence: float | None = None  # mean over OCR'd pages


class BriefOut(BaseModel):
    status: str
    disclaimer: str
    user_summary: str | None
    documents: list[BriefDocumentOut]
    chronology: list[TimelineItemOut]
    document_supported_facts: list[SupportedFactOut]
    user_account_not_verified: list[str]
    gaps_and_inconsistencies: list[FlagOut]
    legal_sources: list[LegalSourceOut]
    advocate_questions: list[str]
    checklist: list[str]
    suggestions_ai_generated: bool
