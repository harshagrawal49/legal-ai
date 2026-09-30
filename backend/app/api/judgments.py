from fastapi import APIRouter, HTTPException

from app.api.deps import DB
from app.models import Judgment
from app.schemas import JudgmentOut

router = APIRouter(prefix="/judgments", tags=["judgments"])


@router.get("/{judgment_id}", response_model=JudgmentOut)
def get_judgment(judgment_id: str, db: DB):
    judgment = db.get(Judgment, judgment_id)
    if judgment is None:
        raise HTTPException(404, "Judgment not found")
    return judgment
