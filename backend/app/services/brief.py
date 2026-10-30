"""Case-preparation brief: a reviewable draft that keeps document facts, the user's own account,
possible gaps and legal sources in separate sections.

Everything except the advocate questions and checklist is assembled in code from stored data, so
each item keeps its source. The questions/checklist come from the LLM; if that call fails, simple
questions derived from the flags are used instead and the brief says so.
"""

import json
import logging

import openai

from app.llm import prompts
from app.llm.client import LLMRefusal, structured
from app.llm.schemas import BriefSuggestions
from app.models import Case, CaseDocument
from app.services.evidence import build_flags, build_timeline, source_ref

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Draft for discussion with an advocate. It organises your documents and lists possibly relevant "
    "material; it does not decide ownership or liability, predict an outcome, or replace legal advice. "
    "Nothing has been filed, signed or sent. Review every item against the original documents."
)


def _document_status(docs: list[CaseDocument]) -> list[dict]:
    return [
        {
            "document_id": str(d.id),
            "filename": d.filename,
            "status": d.status,
            "document_type": d.facts.get("document_type") if d.facts else None,
            "page_count": len(d.pages or []),
            "error": d.error,
        }
        for d in docs
    ]


def _supported_facts(docs: list[CaseDocument]) -> list[dict]:
    """Facts whose quoted excerpt was found on the cited page."""
    out = []
    for doc in docs:
        if doc.status != "processed":
            continue
        f = doc.facts
        rows = (
            [("party", f"{p['name']}" + (f" ({p['stated_role']})" if p.get("stated_role") else ""), p) for p in f.get("parties", [])]
            + [("property", f"{p['kind']}: {p['value']}", p) for p in f.get("property_identifiers", [])]
            + [("amount", f"{a['description']}: {a['value']}", a) for a in f.get("amounts", [])]
            + [("clause", c["summary"], c) for c in f.get("clauses", [])]
        )
        for category, text, item in rows:
            if item.get("source", {}).get("verified"):
                out.append({"category": category, "text": text, "source": source_ref(doc, item["source"])})
    return out


def _user_account(case: Case) -> list[str]:
    fs = case.fact_sheet or {}
    lines = [
        f"{e['date']}: {e['description']}" if e.get("date") else e["description"]
        for e in fs.get("events", [])
    ]
    lines += [f"{a['description']}: {a['value']}" for a in fs.get("amounts", [])]
    if fs.get("relief_sought"):
        lines.append(f"Relief sought: {fs['relief_sought']}")
    return lines


def _legal_sources(case: Case) -> list[dict]:
    return [
        {
            "judgment_id": r.judgment.id,
            "title": r.judgment.title,
            "court": r.judgment.court,
            "decision_date": r.judgment.decision_date.isoformat() if r.judgment.decision_date else None,
            "citation": r.judgment.citation or r.judgment.neutral_citation,
            "source_url": r.judgment.source_url,
            "why_it_may_matter": r.explanation,
            "key_paragraphs": r.key_paragraphs,
        }
        for r in case.results
    ]


def _fallback_suggestions(flags: list[dict]) -> BriefSuggestions:
    questions = [f"How should this be addressed: {f['message']}" for f in flags if f["kind"] != "extraction_failure"]
    checklist = [f"Re-upload or obtain a readable copy: {f['message']}" for f in flags if f["kind"] == "extraction_failure"]
    return BriefSuggestions(advocate_questions=questions[:8], checklist=checklist[:8])


def _suggestions(case: Case, facts: list[dict], flags: list[dict]) -> tuple[BriefSuggestions, bool]:
    material = {
        "user_summary": (case.fact_sheet or {}).get("summary"),
        "user_account": _user_account(case),
        "document_facts": [f["text"] for f in facts],
        "possible_gaps_and_conflicts": [f["message"] for f in flags],
    }
    try:
        return structured(
            BriefSuggestions,
            prompts.BRIEF_SUGGESTIONS_SYSTEM,
            f"<case_material>\n{json.dumps(material, ensure_ascii=False, indent=1)}\n</case_material>",
        ), True
    except (openai.APIError, LLMRefusal, RuntimeError) as e:
        log.warning("brief suggestions failed for case %s: %s", case.id, type(e).__name__)
        return _fallback_suggestions(flags), False


def build_brief(case: Case) -> dict:
    docs = list(case.documents)
    facts = _supported_facts(docs)
    flags = build_flags(docs)
    suggestions, ai_generated = _suggestions(case, facts, flags)
    return {
        "status": "draft",
        "disclaimer": DISCLAIMER,
        "user_summary": (case.fact_sheet or {}).get("summary"),
        "documents": _document_status(docs),
        "chronology": build_timeline(docs),
        "document_supported_facts": facts,
        "user_account_not_verified": _user_account(case),
        "gaps_and_inconsistencies": flags,
        "legal_sources": _legal_sources(case),
        "advocate_questions": suggestions.advocate_questions,
        "checklist": suggestions.checklist,
        "suggestions_ai_generated": ai_generated,
    }
