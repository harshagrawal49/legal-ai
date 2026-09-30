"""Finding similar judgments: hybrid retrieval (keywords + vectors), then LLM relevance analysis."""

import json
import re
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import prompts
from app.llm.client import structured
from app.llm.schemas import SearchAnalysis
from app.models import Case, CaseResult, Judgment, JudgmentParagraph
from app.services.embeddings import embed_query

RRF_K = 60  # standard reciprocal-rank-fusion constant
PER_LIST = 40  # rows fetched from each retrieval list


@dataclass
class Candidate:
    judgment_id: str
    score: float = 0.0
    para_nos: list[int] = field(default_factory=list)


def _keyword_tsquery(query: str) -> str:
    """'builder delayed possession' -> 'builder | delayed | possession' (OR-match, ranked by ts_rank)."""
    words = re.findall(r"[A-Za-z0-9]{3,}", query)
    return " | ".join(words)


def _paragraph_hits_by_keyword(db: Session, query: str) -> list[tuple[str, int]]:
    tsq = _keyword_tsquery(query)
    if not tsq:
        return []
    rows = db.execute(
        text(
            """
            SELECT judgment_id, para_no
            FROM judgment_paragraphs, to_tsquery('english', :q) q
            WHERE tsv @@ q
            ORDER BY ts_rank_cd(tsv, q) DESC
            LIMIT :n
            """
        ),
        {"q": tsq, "n": PER_LIST},
    )
    return [(r.judgment_id, r.para_no) for r in rows]


def _paragraph_hits_by_vector(db: Session, vector: list[float]) -> list[tuple[str, int]]:
    rows = db.execute(
        select(JudgmentParagraph.judgment_id, JudgmentParagraph.para_no)
        .order_by(JudgmentParagraph.embedding.cosine_distance(vector))
        .limit(PER_LIST)
    )
    return [(r.judgment_id, r.para_no) for r in rows]


def _judgment_hits_by_summary(db: Session, vector: list[float]) -> list[tuple[str, int | None]]:
    rows = db.execute(
        select(Judgment.id).order_by(Judgment.summary_embedding.cosine_distance(vector)).limit(PER_LIST // 2)
    )
    return [(r.id, None) for r in rows]


def hybrid_search(db: Session, queries: list[str], limit: int) -> list[Candidate]:
    """Run keyword + vector search for each query and fuse the ranked lists with RRF at judgment level."""
    candidates: dict[str, Candidate] = {}

    ranked_lists: list[list[tuple[str, int | None]]] = []
    for q in queries:
        vector = embed_query(q)
        ranked_lists += [
            _paragraph_hits_by_keyword(db, q),
            _paragraph_hits_by_vector(db, vector),
            _judgment_hits_by_summary(db, vector),
        ]

    for hits in ranked_lists:
        seen: set[str] = set()
        rank = 0
        for judgment_id, para_no in hits:
            cand = candidates.setdefault(judgment_id, Candidate(judgment_id))
            if para_no is not None and para_no not in cand.para_nos:
                cand.para_nos.append(para_no)
            if judgment_id in seen:  # a long judgment shouldn't win just by having many matching paragraphs
                continue
            seen.add(judgment_id)
            rank += 1
            cand.score += 1 / (RRF_K + rank)

    return sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:limit]


def _candidate_block(db: Session, cand: Candidate) -> str:
    j = db.get(Judgment, cand.judgment_id)
    paras = db.scalars(
        select(JudgmentParagraph).where(
            JudgmentParagraph.judgment_id == j.id, JudgmentParagraph.para_no.in_(cand.para_nos[:4])
        )
    ).all()
    matched = "\n".join(f"[¶{p.para_no}] {p.text[:1200]}" for p in paras)
    return (
        f'<judgment judgment_id="{j.id}">\n'
        f"Title: {j.title}\nCourt: {j.court}\nDate: {j.decision_date}\nDisposal: {j.disposal}\n"
        f"Summary: {json.dumps(j.summary, ensure_ascii=False)}\n"
        f"Matching paragraphs:\n{matched}\n</judgment>"
    )


def find_similar_cases(db: Session, case: Case) -> list[CaseResult]:
    """Search, analyse and store the results for a confirmed case."""
    settings = get_settings()
    fs = case.fact_sheet
    queries = [fs["summary"], *fs.get("search_queries", [])]
    candidates = hybrid_search(db, queries, settings.search_candidates)
    if not candidates:
        return []

    blocks = "\n\n".join(_candidate_block(db, c) for c in candidates)
    user_prompt = (
        f"<user_case>\n{json.dumps(fs, ensure_ascii=False, indent=1)}\n</user_case>\n\n"
        f"<candidates>\n{blocks}\n</candidates>"
    )
    analysis = structured(SearchAnalysis, prompts.SEARCH_ANALYSIS_SYSTEM, user_prompt)

    # Keep only IDs we actually sent (guards against invented citations), best first.
    valid_ids = {c.judgment_id for c in candidates}
    matches = sorted(
        (m for m in analysis.matches if m.judgment_id in valid_ids and m.relevance >= 30),
        key=lambda m: m.relevance,
        reverse=True,
    )[: settings.search_results]

    case.results = [
        CaseResult(
            judgment_id=m.judgment_id,
            rank=i + 1,
            relevance=m.relevance,
            stance=m.stance,
            explanation=m.explanation,
            similarities=m.similarities,
            differences=m.differences,
            key_paragraphs=m.key_paragraphs,
        )
        for i, m in enumerate(matches)
    ]
    case.status = "searched"
    return case.results
