"""Database tables.

judgments / judgment_paragraphs  -> the court data, filled by the ingestion pipeline
cases / case_documents / chat_messages / case_results -> what users create in the app
"""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base

EMBED_DIM = get_settings().embedding_dim


class Judgment(Base):
    __tablename__ = "judgments"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # dataset path, e.g. "2023_16_872_887"
    title: Mapped[str] = mapped_column(Text)
    petitioner: Mapped[str | None] = mapped_column(Text)
    respondent: Mapped[str | None] = mapped_column(Text)
    court: Mapped[str] = mapped_column(String)
    decision_date: Mapped[date | None] = mapped_column(Date)
    citation: Mapped[str | None] = mapped_column(String)
    neutral_citation: Mapped[str | None] = mapped_column(String)
    judges: Mapped[str | None] = mapped_column(Text)
    disposal: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str] = mapped_column(Text)

    # Structured summary (app/llm/schemas.py: JudgmentSummary). Written lazily, the first time the
    # judgment is opened, so ingestion needs no LLM call; empty until then (summary_status = "none").
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Embedding of the headnote / opening text (or the summary), used by the summary-level search list.
    summary_embedding = mapped_column(Vector(EMBED_DIM))

    # Provenance and filtering (ingest/): where it came from and why it was judged a property dispute.
    source: Mapped[str | None] = mapped_column(String)  # sc | hc
    court_code: Mapped[str | None] = mapped_column(String)  # HC, e.g. 27_1
    bench: Mapped[str | None] = mapped_column(String)  # HC, e.g. hcbgoa
    cnr: Mapped[str | None] = mapped_column(String, index=True)
    case_type: Mapped[str | None] = mapped_column(String)  # e.g. SA, FA, CA
    headnote: Mapped[str | None] = mapped_column(Text)  # SC headnote / HC opening lines from the dataset
    acts: Mapped[list] = mapped_column(JSONB, default=list)  # [{"act": ..., "section": ...}]
    topic_tags: Mapped[list] = mapped_column(JSONB, default=list)  # e.g. ["sale_contract"]
    property_score: Mapped[float | None] = mapped_column(Float)
    filter_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    language: Mapped[str | None] = mapped_column(String)
    pdf_key: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str] = mapped_column(String, default="none")  # none | done
    embedding_model: Mapped[str | None] = mapped_column(String)
    pipeline_version: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paragraphs: Mapped[list["JudgmentParagraph"]] = relationship(
        back_populates="judgment", order_by="JudgmentParagraph.para_no", cascade="all, delete-orphan"
    )


class JudgmentParagraph(Base):
    __tablename__ = "judgment_paragraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[str] = mapped_column(ForeignKey("judgments.id", ondelete="CASCADE"), index=True)
    para_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))

    judgment: Mapped[Judgment] = relationship(back_populates="paragraphs")

    __table_args__ = (
        Index("ix_paragraphs_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_paragraphs_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Case(Base):
    """A user's matter. `fact_sheet` is the single source of truth everything else is grounded on."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(Text, default="New case")
    status: Mapped[str] = mapped_column(String, default="intake")  # intake -> confirmed -> searched
    fact_sheet: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Everything the user has told us during intake (description + answers), in order.
    intake_inputs: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    results: Mapped[list["CaseResult"]] = relationship(order_by="CaseResult.rank", cascade="all, delete-orphan")
    messages: Mapped[list["ChatMessage"]] = relationship(order_by="ChatMessage.id", cascade="all, delete-orphan")
    documents: Mapped[list["CaseDocument"]] = relationship(
        order_by="CaseDocument.created_at", cascade="all, delete-orphan"
    )


class CaseDocument(Base):
    """A PDF the user uploaded for a case. Only the extracted page text is kept, not the file itself.

    status: processed (text + facts) | text_only (text extracted, fact extraction failed) | failed (no usable text)
    `facts` follows app/llm/schemas.py: DocumentFacts, with a `verified` flag added to every source reference.
    """

    __tablename__ = "case_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSONB, default=list)  # page text, index 0 = page 1
    page_info: Mapped[list] = mapped_column(JSONB, default=list)  # per page: text source, OCR engine/confidence
    # Plain-language explanation per language (app/services/understanding.py): {"en": {...}, "hinglish": {...}}
    understanding: Mapped[dict] = mapped_column(JSONB, default=dict)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseResult(Base):
    """A judgment found for a case, with the LLM's explanation of how it relates."""

    __tablename__ = "case_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    judgment_id: Mapped[str] = mapped_column(ForeignKey("judgments.id"))
    rank: Mapped[int] = mapped_column(Integer)
    relevance: Mapped[int] = mapped_column(Integer)  # 0-100
    stance: Mapped[str] = mapped_column(String)  # supports | opposes | mixed
    explanation: Mapped[str] = mapped_column(Text)
    similarities: Mapped[list] = mapped_column(JSONB, default=list)
    differences: Mapped[list] = mapped_column(JSONB, default=list)
    key_paragraphs: Mapped[list] = mapped_column(JSONB, default=list)

    judgment: Mapped[Judgment] = relationship()


class ChatMessage(Base):
    """One message of the advisor conversation, in OpenAI chat format.

    `message` holds the exact dict sent to / returned by the model (including tool calls and any
    provider-specific fields), so the history can be replayed unchanged. `display_text` is what the
    app shows; hidden messages (context, tool results) have none.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant | tool
    message: Mapped[dict] = mapped_column(JSONB)
    display_text: Mapped[str | None] = mapped_column(Text)
    # Assistant replies: the verified sources (documents/pages, judgments). User messages: @-mentioned document ids.
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    mentions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- Ingestion bookkeeping (ingest/) ----------


class IngestionItem(Base):
    """Every source record the ingester has seen, with its outcome: the queue for retries and the audit trail.

    status: rejected (filtered out, reasons kept) | accepted (stored as a Judgment) | failed (will be retried)
    """

    __tablename__ = "ingestion_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # sc | hc
    key: Mapped[str] = mapped_column(String)  # the Judgment id it becomes
    partition: Mapped[str] = mapped_column(String)  # "2024" or "2025/27_1/hcbgoa"
    status: Mapped[str] = mapped_column(String)
    stage: Mapped[str | None] = mapped_column(String)  # metadata | fulltext | semantic | llm
    score: Mapped[float | None] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    pipeline_version: Mapped[str | None] = mapped_column(String)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("source", "key", name="uq_ingestion_items_source_key"),)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)  # partitions, seen, new, accepted, rejected, failed, llm_calls
    status: Mapped[str] = mapped_column(String, default="running")  # running | done | interrupted | error


class SourcePartition(Base):
    """Watermark per source partition: if the metadata file's ETag hasn't changed, there is nothing new."""

    __tablename__ = "source_partitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "sc/2024", "hc/2025/27_1/hcbgoa"
    etag: Mapped[str | None] = mapped_column(String)
    last_modified: Mapped[str | None] = mapped_column(String)
    rows: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
