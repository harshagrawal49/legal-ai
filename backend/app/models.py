"""Database tables.

judgments / judgment_paragraphs  -> the court data, filled by the ingestion pipeline
cases / chat_messages / case_results -> what users create in the app
"""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
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

    # Structured summary produced once at ingestion (see app/llm/schemas.py: JudgmentSummary).
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary_embedding = mapped_column(Vector(EMBED_DIM))

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
