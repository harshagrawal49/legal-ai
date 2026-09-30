"""Request/response bodies of the REST API (what the Android app sends and receives)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schemas import FactSheet


class NewCaseIn(BaseModel):
    description: str = Field(min_length=20, max_length=20000)


class IntakeAnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class FactSheetIn(BaseModel):
    fact_sheet: FactSheet


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=10000)


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
