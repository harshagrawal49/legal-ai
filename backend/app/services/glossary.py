"""Legal term spotting, language identification and rule-based document classification.

All deterministic (no LLM):
- `find_terms`: dictionary matching against the curated glossary (app/data/legal_glossary.json),
  with English and Hindi variants. Explanations come from the glossary, not from a model, so a
  term means the same thing every time and can be reviewed.
- `detect_language`: English, Hindi (Devanagari) or Hinglish (Roman-script Hindi mixed with English).
- `classify`: document type from weighted keyword cues; a cross-check on the LLM's label.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "data" / "legal_glossary.json"


@dataclass
class TermHit:
    term_id: str
    term: str
    matched: str  # the variant found, as it appears in the glossary
    page: int  # 1-based
    excerpt: str


@lru_cache
def glossary() -> dict:
    data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {t["id"]: t for t in data["terms"]}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _is_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


@lru_cache
def _patterns() -> list[tuple[str, str, re.Pattern]]:
    """(term_id, variant, compiled pattern), longest variants first so 'agreement to sell' wins over 'sell'."""
    out = []
    for term_id, t in glossary().items():
        for variant in t["variants"]:
            v = _nfc(variant.lower())
            words = [re.escape(w) for w in v.split()]
            body = r"\s+".join(words)
            if _is_devanagari(v):
                # \b doesn't work reliably next to Devanagari vowel signs: require a non-letter boundary.
                pattern = rf"(?<![ऀ-ॿ]){body}(?![ऀ-ॿ])"
            else:
                pattern = rf"(?<![a-z0-9]){body}(?![a-z0-9])"
            out.append((term_id, variant, re.compile(pattern, re.IGNORECASE)))
    return sorted(out, key=lambda x: len(x[1]), reverse=True)


def find_terms(pages: list[str]) -> list[TermHit]:
    """Glossary terms found in the pages: one hit per term (its first occurrence), in reading order."""
    hits: dict[str, TermHit] = {}
    for n, text in enumerate(pages, start=1):
        low = _nfc(text.lower())
        taken: list[tuple[int, int]] = []  # spans already matched by a longer variant
        for term_id, variant, pattern in _patterns():
            for m in pattern.finditer(low):
                if any(s < m.end() and m.start() < e for s, e in taken):
                    continue
                taken.append(m.span())
                if term_id not in hits:
                    start, end = m.span()
                    excerpt = re.sub(r"\s+", " ", text[max(0, start - 50): end + 50]).strip()
                    hits[term_id] = TermHit(term_id, glossary()[term_id]["term"], variant, n, excerpt)
    return sorted(hits.values(), key=lambda h: h.page)


# ---------- Language identification ----------

# Common Hindi words written in Roman script, rare in English text.
HINGLISH_MARKERS = {
    "hai", "hain", "ka", "ki", "ke", "ko", "mein", "mai", "maine", "mera", "meri", "mere", "humne", "hum",
    "aap", "aapka", "aapke", "kya", "kyu", "kyun", "kaise", "nahi", "nahin", "tha", "thi", "diya",
    "diye", "liya", "kar", "karna", "karo", "kiya", "gaya", "gayi", "abhi", "bhi", "aur", "lekin", "par",
    "wala", "wali", "paisa", "paise", "bech", "becha", "bechna", "kaha", "batao", "chahiye", "sakta", "sakte",
    "isme", "usme", "iska", "uska", "kitna", "kitni", "kitne", "likha", "likhi", "mila", "mili", "mile", "raha",
    "rahi", "rahe", "wapas", "kisi", "ye", "yeh", "woh", "kuch", "sirf", "hua", "hui", "hue", "karu", "karun",
    "samjhao", "samajh", "bataye", "bataiye", "matlab", "kab", "kahan", "kyunki", "agar", "toh", "jab", "ab",
    "mujhe", "humein", "unhone", "usne", "apna", "apni", "karwana", "karayi", "milega", "milegi", "dena", "lena",
}
ENGLISH_HOMOGRAPHS = {"par", "mai", "hum", "kar"}  # also English words / abbreviations: weigh less
# ("the", Hindi for "were", is left out entirely: far too common in English.)


def detect_language(text: str) -> str:
    """'en', 'hi' (Devanagari) or 'hinglish' (Roman-script Hindi mixed with English)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
    devanagari = sum("ऀ" <= ch <= "ॿ" for ch in letters) / len(letters)
    if devanagari >= 0.3:
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return "en"
    score = sum(0.4 if w in ENGLISH_HOMOGRAPHS else 1.0 for w in words if w in HINGLISH_MARKERS)
    return "hinglish" if score >= 2 and score / len(words) >= 0.12 else "en"


# ---------- Document classification ----------

# Cue phrases per document type (lowercase). Phrases in the first lines (the title) count three times.
TYPE_CUES = {
    "agreement_to_sell": ["agreement to sell", "agreement for sale", "sale agreement", "the purchaser", "the vendor",
                          "विक्रय अनुबंध", "बिक्री अनुबंध", "करारनामा", "क्रेता"],
    "sale_deed": ["sale deed", "deed of sale", "conveyance deed", "hereby sell", "hereby convey", "विक्रय पत्र", "बैनामा"],
    "receipt": ["receipt", "received from", "received a sum", "received with thanks", "रसीद", "प्राप्त हुई", "प्राप्तकर्ता"],
    "legal_notice": ["legal notice", "under instructions from my client", "calls upon you", "my client", "कानूनी नोटिस", "मेरे मुवक्किल"],
    "property_record": ["7/12", "record of rights", "property card", "mutation entry", "khasra", "khatauni", "jamabandi",
                        "खसरा", "खतौनी", "जमाबंदी", "दाखिल खारिज"],
    "court_filing": ["in the court of", "plaintiff", "defendant", "petitioner", "respondent", "suit no", "वादी", "प्रतिवादी", "न्यायालय"],
    "payment_proof": ["transaction id", "utr", "neft", "rtgs", "imps", "account statement", "debited", "credited"],
    "correspondence": ["dear sir", "dear madam", "yours faithfully", "yours sincerely", "subject:"],
}


def classify(pages: list[str]) -> tuple[str, float]:
    """(document type, confidence 0-1). 'other' when no cue matches. Confidence is the winner's share of
    all cue weight, so two equally likely types give 0.5."""
    text = _nfc(" ".join(pages).lower())
    title = _nfc("\n".join(" ".join(pages).splitlines()[:6]).lower())
    scores = {}
    for doc_type, cues in TYPE_CUES.items():
        score = 0.0
        for cue in cues:
            count = len(re.findall(re.escape(cue), text))
            if count:
                score += min(count, 3) + (2 if cue in title else 0)
        if score:
            scores[doc_type] = score
    if not scores:
        return "other", 0.0
    best = max(scores, key=scores.get)
    return best, round(scores[best] / sum(scores.values()), 2)
