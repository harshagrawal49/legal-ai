import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import DB
from app.models import Judgment
from app.schemas import JudgmentOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/judgments", tags=["judgments"])


@router.get("/{judgment_id}", response_model=JudgmentOut)
def get_judgment(judgment_id: str, db: DB):
    """Judgment with its paragraphs. Judgments are ingested without an LLM summary; the summary is
    written the first time one is opened and then kept (if the LLM is unavailable, the headnote is shown)."""
    judgment = db.get(Judgment, judgment_id)
    if judgment is None:
        raise HTTPException(404, "Judgment not found")
    if not judgment.summary and judgment.paragraphs:
        try:
            from ingest.supreme_court import summarise

            s = summarise(judgment.title, [(p.para_no, p.text) for p in judgment.paragraphs])
            judgment.summary, judgment.summary_status = s.model_dump(), "done"
            db.commit()
        except Exception as e:  # LLM busy or refused: show the judgment without a summary
            log.warning("lazy summary failed for %s: %s", judgment_id, type(e).__name__)
            db.rollback()
    return judgment


corpus = APIRouter(prefix="/corpus", tags=["judgments"])


@corpus.get("/stats")
def corpus_stats(db: DB):
    """What the legal memory holds: counts by source, court and topic, and the last ingestion run."""
    from ingest.store import corpus_stats as stats

    return stats(db)
