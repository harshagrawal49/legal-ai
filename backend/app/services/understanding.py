"""Document understanding: a plain-language explanation of one uploaded document.

For each processed document this builds (and caches per language: English, Hindi, Hinglish):
- a one-line description and a 5-8 point plain-language summary;
- explanations of the important clauses;
- the legal terms found in it, with curated meanings from the glossary (not generated);
- neutral "things to check", from the LLM plus the rule-based flags for this document.

The LLM writes the explanation; code then checks it, in the same spirit as the rest of the app:
- every point must cite a real page, and its quote must appear on that page (else `verified: false`);
- every amount, date or survey number in a point must exist in the document (else the point is dropped);
- advice or outcome language ("you will win", "this is illegal") is dropped;
- term ids must be ones the glossary actually found in the document.
If the LLM call fails, the deterministic parts (document type, terms, checks) are still returned.
"""

import logging
import re
from datetime import datetime, timezone

import openai

from app.config import get_settings
from app.llm import prompts
from app.llm.client import LLMRefusal, structured
from app.llm.schemas import DocumentUnderstanding
from app.models import CaseDocument
from app.services import glossary, nlp
from app.services.documents import _document_prompt, excerpt_on_page
from app.services.evidence import build_flags, page_source

log = logging.getLogger(__name__)

LANGUAGES = ("en", "hi", "hinglish")
# Advice or outcome claims that a document explanation must never make (it explains; it doesn't judge).
ADVICE_RE = re.compile(
    r"\b(you will (win|lose)|you should (sue|file|go to court)|guarantee[ds]?|definitely (win|lose)|"
    r"(is|are) (illegal|invalid|void|unenforceable)|(this|it) is (fraud|a fraud|cheating)|"
    r"aap (jeet|haar) jaoge|case jeet)\b|आप जीत|आप हार|अवैध है|धोखाधड़ी है",
    re.IGNORECASE,
)
# Rule-based flags that describe a single document (cross-document ones belong to the evidence pack).
DOCUMENT_FLAG_KINDS = {"possibly_missed", "uncertainty", "unverified_reference", "ocr_used", "ocr_low_confidence",
                       "ocr_page_not_read", "partially_processed"}


def _values(text_pages: list[str]) -> set[tuple[str, str]]:
    return {(m.kind, m.normalized) for m in nlp.extract(text_pages)}


def _check_point(point: dict, doc: CaseDocument, doc_values: set) -> tuple[dict | None, str | None]:
    """The point with `pages` cleaned and `verified` set, or (None, reason) if it must be dropped."""
    text = point.get("text") or point.get("meaning") or ""
    if ADVICE_RE.search(text):
        return None, "advice"
    invented = _values([text]) - doc_values
    if invented:
        return None, f"values not in the document: {sorted(v for _, v in invented)}"
    pages = [p for p in point.get("pages") or [] if 1 <= p <= len(doc.pages or [])]
    quote = point.get("quote")
    point["pages"] = pages
    point["verified"] = bool(quote) and any(excerpt_on_page(quote, doc.pages, p) for p in pages)
    point["from_ocr"] = any(page_source(doc, p).get("source") == "ocr" for p in pages)
    return point, None


def _terms(doc: CaseDocument, in_context: dict[str, str]) -> list[dict]:
    """Every glossary term found in the document, with its curated meaning and the LLM's 'why here'."""
    entries = glossary.glossary()
    out = []
    for hit in glossary.find_terms(doc.pages or []):
        e = entries[hit.term_id]
        out.append({
            "id": hit.term_id, "term": e["term"], "hindi": e["names"].get("hi"), "meaning": e["meaning"],
            "why_it_matters": e["why"], "law": e.get("law"), "page": hit.page, "excerpt": hit.excerpt,
            "in_this_document": in_context.get(hit.term_id),
        })
    return out


def _rule_checks(doc: CaseDocument) -> list[dict]:
    return [
        {"text": f["message"], "pages": sorted({s["page"] for s in f["sources"] if s.get("page")}), "kind": f["kind"]}
        for f in build_flags([doc]) if f["kind"] in DOCUMENT_FLAG_KINDS
    ]


def _fallback_line(doc: CaseDocument, doc_type: str) -> str:
    f = doc.facts or {}
    parts = [doc_type.replace("_", " ").capitalize()]
    if f.get("document_date"):
        parts.append(f"dated {f['document_date']}")
    names = [p["name"] for p in f.get("parties", [])][:3]
    if names:
        parts.append("involving " + ", ".join(names))
    return " ".join(parts) + "."


def build_understanding(doc: CaseDocument, language: str = "en") -> dict:
    """Generate and check the explanation. Never raises for LLM failures: returns status 'partial'."""
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}")
    rule_type, rule_confidence = glossary.classify(doc.pages or [])
    llm_type = (doc.facts or {}).get("document_type")
    doc_type = llm_type or rule_type
    hits = glossary.find_terms(doc.pages or [])
    result = {
        "language": language,
        "document_type": doc_type,
        "type_check": {"rule_based": rule_type, "confidence": rule_confidence, "agrees": rule_type in (llm_type, "other") or llm_type is None},
        "document_language": glossary.detect_language(" ".join(doc.pages or [])),
        "one_line": _fallback_line(doc, doc_type),
        "summary": [], "clauses": [],
        "things_to_check": _rule_checks(doc),
        "dropped": [],
        "status": "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    in_context: dict[str, str] = {}
    try:
        pages_prompt, truncated_after = _document_prompt(doc.filename, doc.pages or [])
        from app.services.intake import document_facts_block

        terms_block = "\n".join(f"- {h.term_id}: {glossary.glossary()[h.term_id]['term']} (page {h.page})" for h in hits)
        user = (
            f"{pages_prompt}\n\n<extracted_facts>\n{document_facts_block([doc]) or 'None.'}\n</extracted_facts>\n\n"
            f"<glossary_terms>\n{terms_block or 'None found.'}\n</glossary_terms>"
        )
        system = prompts.DOCUMENT_UNDERSTANDING_SYSTEM.replace("{language}", prompts.LANGUAGE_NAMES[language])
        u = structured(DocumentUnderstanding, system, user, model=get_settings().model_fast, max_tokens=4000).model_dump()
    except (openai.APIError, LLMRefusal, RuntimeError) as e:
        log.warning("document understanding failed for %s: %s", doc.id, type(e).__name__)
        result["terms"] = _terms(doc, in_context)
        return result

    doc_values = _values(doc.pages or [])
    for key, out_key in (("summary", "summary"), ("clause_explanations", "clauses"), ("things_to_check", "things_to_check")):
        kept = []
        for point in u[key]:
            checked, reason = _check_point(point, doc, doc_values)
            if checked is None:
                result["dropped"].append({"section": out_key, "text": point.get("text") or point.get("meaning"), "reason": reason})
                log.info("dropped understanding point for %s: %s", doc.id, reason)
            else:
                kept.append(checked)
        result[out_key] = kept + (result[out_key] if out_key == "things_to_check" else [])
    found_ids = {h.term_id for h in hits}
    in_context = {t["term_id"]: t["why_here"] for t in u["terms_in_context"] if t["term_id"] in found_ids}
    one_line_ok, _ = _check_point({"text": u["one_line"], "pages": []}, doc, doc_values)
    if one_line_ok:
        result["one_line"] = u["one_line"]
    result["terms"] = _terms(doc, in_context)
    result["truncated_after_page"] = truncated_after
    result["status"] = "complete"
    return result


def ensure_understanding(doc: CaseDocument, language: str = "en", refresh: bool = False) -> dict:
    """Cached explanation for this language, generating it if needed (stored on the document)."""
    cache = dict(doc.understanding or {})
    if refresh or language not in cache or cache[language].get("status") != "complete":
        cache[language] = build_understanding(doc, language)
        doc.understanding = cache  # new dict so the JSONB column is saved
    return cache[language]
