from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, User, UserCase
from app.models import Case
from app.schemas import (
    CaseOut,
    CaseResultOut,
    CaseSummaryOut,
    ChatIn,
    ChatMessageOut,
    FactSheetIn,
    IntakeAnswerIn,
    NewCaseIn,
)
from app.services import advisor, intake, search

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_out(case: Case) -> CaseOut:
    out = CaseOut.model_validate(case)
    last = case.intake_inputs[-1] if case.intake_inputs else None
    if case.status == "intake" and last and last["role"] == "assistant":
        out.pending_questions = last["text"].split("\n")
    return out


@router.post("", response_model=CaseOut)
def create_case(body: NewCaseIn, db: DB, user: User):
    """Step 1: the user describes their problem. Returns the first fact sheet and any follow-up questions."""
    case = Case(user_id=user, intake_inputs=[{"role": "user", "text": body.description}])
    intake.run_intake(case)
    db.add(case)
    db.commit()
    return _case_out(case)


@router.get("", response_model=list[CaseSummaryOut])
def list_cases(db: DB, user: User):
    return db.scalars(select(Case).where(Case.user_id == user).order_by(Case.updated_at.desc())).all()


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case: UserCase):
    return _case_out(case)


@router.post("/{case_id}/intake", response_model=CaseOut)
def answer_questions(body: IntakeAnswerIn, case: UserCase, db: DB):
    """Step 2: the user answers follow-up questions (or adds details). The fact sheet is rebuilt."""
    case.intake_inputs = [*case.intake_inputs, {"role": "user", "text": body.text}]
    intake.run_intake(case)
    db.commit()
    return _case_out(case)


@router.put("/{case_id}/fact-sheet", response_model=CaseOut)
def edit_fact_sheet(body: FactSheetIn, case: UserCase, db: DB):
    """The user corrects the summary directly."""
    case.fact_sheet = body.fact_sheet.model_dump()
    db.commit()
    return _case_out(case)


@router.post("/{case_id}/search", response_model=list[CaseResultOut])
def run_search(case: UserCase, db: DB):
    """Step 3: the user confirms the summary; find and explain similar judgments."""
    if not case.fact_sheet:
        raise HTTPException(400, "Describe the case first")
    results = search.find_similar_cases(db, case)
    db.commit()
    return results


@router.get("/{case_id}/results", response_model=list[CaseResultOut])
def get_results(case: UserCase):
    return case.results


@router.get("/{case_id}/chat", response_model=list[ChatMessageOut])
def chat_history(case: UserCase):
    # Hidden messages (context, tool results) have no display text.
    return [m for m in case.messages if m.display_text]


@router.post("/{case_id}/chat")
def chat(body: ChatIn, case: UserCase):
    """Step 4: follow-up conversation. Streams server-sent events: text, tool, done, error."""
    return StreamingResponse(advisor.stream_reply(case.id, body.message), media_type="text/event-stream")

