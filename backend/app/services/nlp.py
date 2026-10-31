"""Rule-based NLP for Indian property documents: amounts, dates and property identifiers.

Deterministic, no LLM, so it can't invent anything. It is used to cross-check the LLM's document
extraction: values found by both are `corroborated`, and values these rules find on a page but the
LLM didn't extract are reported as `possibly_missed`, so nothing important silently disappears.

Covers English and Hindi wording, ASCII and Devanagari digits, and Indian number formats
(5,00,000 · 4.5 lakh · ₹ · Rs. · रुपये).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.evidence import DEVANAGARI_DIGITS, _norm_id, parse_amount

D = r"[0-9०-९]"  # an ASCII or Devanagari digit


@dataclass
class Mention:
    kind: str  # amount | date | property_identifier
    text: str  # exactly as written
    normalized: str  # comparable value: amount in rupees, ISO date, or normalised identifier
    page: int  # 1-based
    excerpt: str  # surrounding words, for review


# ---------- Amounts ----------

CURRENCY = r"(?:₹|rs\.?|inr|rupees|रु\.?|रुपये|रुपए|रुपया)"
MULTIPLIER = r"(?:lakhs?|lacs?|crores?|लाख|करोड़|करोड)"
AMOUNT_RE = re.compile(
    rf"{CURRENCY}\s*({D}[{D[1:-1]},.]*{D}|{D})(?:\s*({MULTIPLIER}))?(?:\s*/-)?",
    re.IGNORECASE,
)


def rupees(value: Decimal) -> str:
    """Plain decimal string: 4500000, 5.5 (never 4.5E+6)."""
    return format(value.normalize(), "f")


def amount_value(text: str) -> Decimal | None:
    """'Rs. 5,00,000/-' -> 500000; 'रुपये ५ लाख' -> 500000 (one parser for the whole app: evidence.parse_amount)."""
    return parse_amount(text)


# ---------- Dates ----------

MONTHS = {
    # English
    **{m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
         "november", "december"], start=1)},
    **{m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)},
    "sept": 9,
    # Hindi
    "जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8,
    "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
MONTH_NAMES = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))
NUMERIC_DATE_RE = re.compile(rf"(?<![{D[1:-1]}])({D}{{1,2}})[/.\-]({D}{{1,2}})[/.\-]({D}{{4}})(?![{D[1:-1]}])")
WORD_DATE_RE = re.compile(rf"(?<![{D[1:-1]}])({D}{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_NAMES})\.?,?\s+({D}{{4}})", re.IGNORECASE)
WORD_DATE_US_RE = re.compile(rf"\b({MONTH_NAMES})\.?\s+({D}{{1,2}})(?:st|nd|rd|th)?,?\s+({D}{{4}})", re.IGNORECASE)


def _iso(day: str, month: int | str, year: str) -> str | None:
    """Day-first (Indian convention). None for impossible dates."""
    try:
        d = int(day.translate(DEVANAGARI_DIGITS))
        m = month if isinstance(month, int) else int(month.translate(DEVANAGARI_DIGITS))
        return date(int(year.translate(DEVANAGARI_DIGITS)), m, d).isoformat()
    except ValueError:
        return None


# ---------- Property identifiers ----------

ID_LABELS = (
    r"survey\s*(?:no\.?|number|nos\.?)|s\.\s*no\.?|gat\s*(?:no\.?|number)|plot\s*(?:no\.?|number)|"
    r"khata\s*(?:no\.?|number)|cts\s*(?:no\.?|number)|city\s*survey\s*(?:no\.?|number)|flat\s*(?:no\.?|number)|"
    r"सर्वे\s*(?:क्रमांक|क्र\.?|नंबर|नं\.?|संख्या)|खसरा\s*(?:क्रमांक|क्र\.?|नंबर|नं\.?|संख्या)|"
    r"प्लॉट\s*(?:क्रमांक|क्र\.?|नंबर|नं\.?|संख्या)|खाता\s*(?:क्रमांक|क्र\.?|नंबर|नं\.?|संख्या)|भूखंड\s*(?:क्रमांक|क्र\.?|संख्या)"
)
ID_RE = re.compile(rf"({ID_LABELS})\s*:?\s*({D}[{D[1:-1]}]*(?:\s*/\s*[{D[1:-1]}A-Za-zअ-ह]+)*)", re.IGNORECASE)


def _excerpt(text: str, start: int, end: int, width: int = 60) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - width): end + width]).strip()


def extract(pages: list[str]) -> list[Mention]:
    """All amount, date and property-identifier mentions in the pages, in reading order."""
    mentions: list[Mention] = []
    for n, text in enumerate(pages, start=1):
        for m in AMOUNT_RE.finditer(text):
            value = amount_value(m.group(0))
            if value is not None and value > 0:
                mentions.append(Mention("amount", m.group(0).strip(), rupees(value), n, _excerpt(text, *m.span())))
        for m in NUMERIC_DATE_RE.finditer(text):
            iso = _iso(m.group(1), m.group(2), m.group(3))
            if iso:
                mentions.append(Mention("date", m.group(0), iso, n, _excerpt(text, *m.span())))
        for m in WORD_DATE_RE.finditer(text):
            iso = _iso(m.group(1), MONTHS[m.group(2).lower()], m.group(3))
            if iso:
                mentions.append(Mention("date", m.group(0), iso, n, _excerpt(text, *m.span())))
        for m in WORD_DATE_US_RE.finditer(text):
            iso = _iso(m.group(2), MONTHS[m.group(1).lower()], m.group(3))
            if iso:
                mentions.append(Mention("date", m.group(0), iso, n, _excerpt(text, *m.span())))
        for m in ID_RE.finditer(text):
            mentions.append(Mention("property_identifier", m.group(0).strip(), _norm_id(m.group(2)), n, _excerpt(text, *m.span())))
    return _dedupe(mentions)


def _dedupe(mentions: list[Mention]) -> list[Mention]:
    seen, out = set(), []
    for m in mentions:
        key = (m.kind, m.normalized, m.page)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


# ---------- Cross-checking the LLM's extraction ----------


def _llm_values(facts: dict) -> dict[str, set[str]]:
    """Normalised values the LLM extracted, by kind."""
    amounts = {rupees(v) for a in facts.get("amounts", []) if (v := amount_value(a.get("value", ""))) is not None}
    dates = {e["date"] for e in facts.get("events", []) if e.get("date")}
    if facts.get("document_date"):
        dates.add(facts["document_date"])
    ids = {_norm_id(p.get("value", "")) for p in facts.get("property_identifiers", [])}
    return {"amount": amounts, "date": dates, "property_identifier": ids}


def cross_check(facts: dict, pages: list[str]) -> None:
    """Mark LLM amounts/dates/identifiers `corroborated` when the rules found the same value, and list
    rule-found values the LLM didn't extract as `possibly_missed`. Modifies `facts` in place."""
    mentions = extract(pages)
    found = {(m.kind, m.normalized) for m in mentions}
    for a in facts.get("amounts", []):
        v = amount_value(a.get("value", ""))
        a["corroborated"] = v is not None and ("amount", rupees(v)) in found
    for e in facts.get("events", []):
        e["corroborated"] = bool(e.get("date")) and ("date", e["date"]) in found
    rule_ids = {m.normalized for m in mentions if m.kind == "property_identifier"}
    for p in facts.get("property_identifiers", []):
        p["corroborated"] = _id_matches(_norm_id(p.get("value", "")), rule_ids)
    llm = _llm_values(facts)
    facts["possibly_missed"] = [
        {"kind": m.kind, "value": m.text, "source": {"page": m.page, "excerpt": m.excerpt, "verified": True}}
        for m in mentions
        if not (_id_matches(m.normalized, llm[m.kind], reverse=True) if m.kind == "property_identifier"
                else m.normalized in llm[m.kind])
    ]


def _id_matches(value: str, others: set[str], reverse: bool = False) -> bool:
    """Identifiers match if equal, or if the LLM's value ends with the rule's number ("surveyno1234" vs
    "1234"): the LLM sometimes keeps the label, the rule captures just the number."""
    if not value:
        return False
    if reverse:  # value is the rule's number; others are the LLM's values
        return any(o == value or o.endswith(value) for o in others)
    return any(o == value or value.endswith(o) for o in others if o)
