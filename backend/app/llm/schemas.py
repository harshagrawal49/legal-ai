"""Pydantic models for structured LLM outputs. Responses are validated against these schemas."""

from typing import Literal

from pydantic import BaseModel, Field

# ---------- Case intake ----------


class Party(BaseModel):
    name: str = Field(description="Name as given by the user, or a placeholder like 'the builder' if unnamed")
    role: str = Field(description="Role in the dispute, e.g. 'buyer (user)', 'builder', 'landlord'")


class Event(BaseModel):
    date: str | None = Field(description="ISO date (YYYY-MM-DD, YYYY-MM or YYYY) if known, else null")
    description: str


class Amount(BaseModel):
    description: str = Field(description="What the amount is, e.g. 'booking amount paid'")
    value: str = Field(description="Amount as stated, e.g. 'Rs 25,00,000'")


class FactSheet(BaseModel):
    summary: str = Field(description="3-5 sentence neutral, plain-language summary of the situation")
    parties: list[Party]
    events: list[Event] = Field(description="Chronological events")
    amounts: list[Amount]
    documents: list[str] = Field(description="Agreements, receipts, notices etc. the user has or mentioned")
    actions_taken: list[str] = Field(description="Steps already taken: complaints, notices, cases filed")
    relief_sought: str | None = Field(description="What the user wants (refund, possession, compensation...)")
    location: str | None = Field(description="City / state, relevant for jurisdiction")
    issues: list[str] = Field(description="The legal questions raised, phrased as questions")
    legal_areas: list[str] = Field(
        description="Likely applicable Indian laws / forums, e.g. 'Consumer Protection Act, 2019', 'RERA, 2016'"
    )
    search_queries: list[str] = Field(
        description="3-5 short keyword queries a lawyer would use to find similar Indian judgments"
    )
    missing_info: list[str] = Field(description="Important facts still unknown")


class IntakeResult(BaseModel):
    case_title: str = Field(description="Short title, e.g. 'Builder delayed possession - refund claim'")
    fact_sheet: FactSheet
    questions: list[str] = Field(description="Up to 4 follow-up questions for the user; empty if nothing important is missing")
    ready_to_confirm: bool = Field(description="True if the facts are complete enough to search for similar cases")


# ---------- Uploaded case documents ----------


class SourceRef(BaseModel):
    page: int = Field(description="1-based page number of the document where this appears")
    excerpt: str = Field(description="Short quote (under 200 characters) copied exactly from that page")


class DocParty(BaseModel):
    name: str = Field(description="Name exactly as written in the document")
    stated_role: str | None = Field(description="Role the document gives them, e.g. 'seller', 'purchaser', 'witness'")
    source: SourceRef


class PropertyIdentifier(BaseModel):
    kind: str = Field(description="e.g. 'survey number', 'plot number', 'khata number', 'flat number', 'address'")
    value: str = Field(description="Exactly as written")
    source: SourceRef


class DocAmount(BaseModel):
    kind: Literal["total_consideration", "advance_or_earnest_money", "installment", "refund", "penalty_or_interest", "other"]
    description: str
    value: str = Field(description="Exactly as written, e.g. 'Rs. 5,00,000/-'")
    currency: str | None = Field(description="e.g. 'INR' if stated or clearly implied by 'Rs', else null")
    source: SourceRef


class DocEvent(BaseModel):
    kind: Literal["agreement_signed", "payment", "possession", "notice_sent", "registration", "deadline", "other"]
    date: str | None = Field(description="ISO date (YYYY-MM-DD, YYYY-MM or YYYY) only if written in the document, else null")
    date_as_written: str | None = Field(description="The date exactly as it appears, else null")
    description: str
    source: SourceRef


class Clause(BaseModel):
    summary: str = Field(description="Plain-language summary of the clause")
    source: SourceRef


class ReferencedDocument(BaseModel):
    description: str = Field(description="A document or attachment this document mentions, e.g. 'receipt for advance', 'Annexure A'")
    source: SourceRef


class Uncertainty(BaseModel):
    description: str = Field(description="Something ambiguous, illegible or internally inconsistent in this document")
    source: SourceRef | None


class DocumentFacts(BaseModel):
    document_type: Literal[
        "agreement_to_sell", "sale_deed", "receipt", "payment_proof", "legal_notice",
        "correspondence", "court_filing", "property_record", "other",
    ]
    document_date: str | None = Field(description="ISO date of the document itself if written, else null")
    document_date_source: SourceRef | None
    parties: list[DocParty]
    property_identifiers: list[PropertyIdentifier]
    amounts: list[DocAmount]
    events: list[DocEvent]
    clauses: list[Clause] = Field(description="Clauses relevant to a dispute: payment terms, deadlines, possession, cancellation, refund")
    referenced_documents: list[ReferencedDocument]
    uncertainties: list[Uncertainty]


class BriefSuggestions(BaseModel):
    advocate_questions: list[str] = Field(description="Up to 8 questions the user could discuss with an advocate")
    checklist: list[str] = Field(description="Up to 8 concrete preparation steps, e.g. documents to locate")


# ---------- Judgment summaries (ingestion) ----------


class JudgmentSummary(BaseModel):
    case_type: str = Field(description="e.g. 'Civil appeal - consumer dispute', 'Criminal appeal - cheque dishonour'")
    facts: str = Field(description="Key facts in 3-6 sentences")
    issues: list[str]
    holding: str = Field(description="What the court decided and why, 3-6 sentences")
    outcome: str = Field(description="One line, e.g. 'Appeal allowed; builder ordered to refund with 9% interest'")
    prevailing_party: Literal["petitioner", "respondent", "partly", "unclear"]
    acts_cited: list[str] = Field(description="Statutes and sections, e.g. 'Negotiable Instruments Act, 1881, s.138'")
    legal_areas: list[str]
    key_principles: list[str] = Field(description="Legal principles laid down or applied, one sentence each")
    key_paragraphs: list[int] = Field(description="Numbers of the paragraphs containing the core reasoning")


# ---------- Search analysis ----------


class CaseMatch(BaseModel):
    judgment_id: str
    relevance: int = Field(description="0-100: how closely the facts and issues match the user's case")
    stance: Literal["supports", "opposes", "mixed"] = Field(
        description="Whether the judgment helps or hurts the user's position"
    )
    explanation: str = Field(description="2-3 sentences on how this judgment relates to the user's case")
    similarities: list[str]
    differences: list[str]
    key_paragraphs: list[int] = Field(description="Paragraph numbers the user should read")


class SearchAnalysis(BaseModel):
    matches: list[CaseMatch]
