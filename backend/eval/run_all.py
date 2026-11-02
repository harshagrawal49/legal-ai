"""Scorecard: precision / recall / F1 with 95% confidence intervals for every part that can be measured.

    uv run python -m eval.run_all                       # deterministic parts (no API key), 200 cases
    uv run python -m eval.run_all --cases 200 --ocr-cases 40
    uv run python -m eval.run_all --llm --llm-cases 20  # + LLM document extraction (needs LLM_API_KEY)

Uses synthetic cases with known ground truth (eval/generate_cases.py). Sections:
1. Rule-based NLP on document text: amounts, dates, property identifiers (precision, recall, F1).
2. The same after OCR (Tesseract) on simulated scans (clean / photo / degraded), plus party names.
3. Evidence flags: are planted survey-number / amount differences flagged, and only those?
4. Provenance checking: does intake.check_sources keep correct document refs and drop bad ones?
2b. Document understanding without an LLM: glossary terms, document type, language (documents + chat).
5. (--llm) LLM document extraction: precision / recall / F1 per field against the ground truth.
6. (--llm) Plain-language explanations: dropped-statement rate, quote verification, key-value coverage.

Writes eval/results/scorecard-<timestamp>.json and .md (tables ready for docs/eval_report.md).
Intervals are Wilson score intervals (95%). With synthetic data, read the numbers as "how well the
pipeline does on documents like these", not as real-world accuracy.
"""

import argparse
import json
import math
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pymupdf

from eval.generate_cases import GenCase, GenDoc, generate

RESULTS_DIR = Path(__file__).parent / "results"


# ---------- Statistics ----------


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (well-behaved for small n and for 0% / 100%)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


class Counts:
    """True positives, false positives and false negatives for one metric."""

    def __init__(self):
        self.tp = self.fp = self.fn = 0

    def add(self, predicted: set, gold: set) -> None:
        self.tp += len(predicted & gold)
        self.fp += len(predicted - gold)
        self.fn += len(gold - predicted)

    def row(self, name: str) -> dict:
        p_n, r_n = self.tp + self.fp, self.tp + self.fn
        precision = self.tp / p_n if p_n else 1.0
        recall = self.tp / r_n if r_n else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "metric": name, "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": precision, "precision_ci": wilson(self.tp, p_n),
            "recall": recall, "recall_ci": wilson(self.tp, r_n), "f1": f1,
        }


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _ci(ci: tuple[float, float]) -> str:
    return f"{ci[0]:.1%}–{ci[1]:.1%}"


def table(rows: list[dict]) -> str:
    out = ["| Metric | Precision (95% CI) | Recall (95% CI) | F1 | TP / FP / FN |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['metric']} | {_pct(r['precision'])} ({_ci(r['precision_ci'])}) | "
                   f"{_pct(r['recall'])} ({_ci(r['recall_ci'])}) | {_pct(r['f1'])} | {r['tp']} / {r['fp']} / {r['fn']} |")
    return "\n".join(out)


# ---------- Rendering ----------


def doc_pdf(doc: GenDoc) -> bytes:
    from eval.samples import make_pdf
    from eval.scans import make_devanagari_pdf

    return make_pdf(doc.pages) if doc.language == "en" else make_devanagari_pdf(doc.pages)


def _rule_sets(pages: list[str]) -> dict[str, set[str]]:
    from app.services import nlp

    out = defaultdict(set)
    for m in nlp.extract(pages):
        out[m.kind].add(m.normalized)
    return out


def _squash(text: str) -> str:
    import re
    import unicodedata

    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


# ---------- 1. Rule-based NLP on text ----------


def score_nlp_text(cases: list[GenCase]) -> list[dict]:
    counts = {k: Counts() for k in ("amount", "date", "property_identifier", "all")}
    by_lang = defaultdict(Counts)
    for case in cases:
        for doc in case.documents:
            found = _rule_sets(doc.pages)
            gold = {"amount": doc.amounts, "date": doc.dates, "property_identifier": doc.ids}
            for kind, g in gold.items():
                counts[kind].add(found[kind], g)
                counts["all"].add({(kind, v) for v in found[kind]}, {(kind, v) for v in g})
                by_lang[doc.language].add({(kind, v) for v in found[kind]}, {(kind, v) for v in g})
    rows = [counts["amount"].row("Amounts"), counts["date"].row("Dates"),
            counts["property_identifier"].row("Property identifiers"), counts["all"].row("**All key values**")]
    rows += [by_lang[lang].row(f"All key values: {name}") for lang, name in (("en", "English"), ("hi", "Hindi")) if lang in by_lang]
    return rows


# ---------- 2. After OCR ----------


def score_ocr(cases: list[GenCase], qualities: list[str]) -> tuple[list[dict], dict]:
    from app.services import ocr
    from eval.scans import scan_pdf

    engine = ocr.get_engine()
    if engine is None:
        return [], {"skipped": "no OCR engine installed"}
    rows, timing = [], {}
    for quality in qualities:
        values, names = Counts(), Counts()
        started, pages_read = time.monotonic(), 0
        for case in cases:
            for doc in case.documents:
                pdf = pymupdf.open(stream=scan_pdf(doc_pdf(doc), quality), filetype="pdf")
                text = [engine.read(ocr.render_page(p)).text for p in pdf]
                pages_read += len(text)
                pdf.close()
                found = _rule_sets(text)
                gold = {"amount": doc.amounts, "date": doc.dates, "property_identifier": doc.ids}
                values.add({(k, v) for k in gold for v in found[k]}, {(k, v) for k, g in gold.items() for v in g})
                joined = _squash("\n".join(text))
                hit = {n for n in doc.names if _squash(n) in joined}
                names.add(hit, set(doc.names))
        timing[quality] = (time.monotonic() - started) / max(pages_read, 1)
        rows.append(values.row(f"Key values after OCR: {quality}"))
        rows.append(names.row(f"Party names after OCR: {quality}"))
    return rows, {"engine": engine.name, "seconds_per_page": timing}


# ---------- 2b. Document understanding: terms, type, language ----------


def score_understanding(cases: list[GenCase]) -> tuple[list[dict], dict]:
    from app.services import glossary
    from eval.chat_language_cases import CHAT_LANGUAGE_CASES

    terms = Counts()
    type_right = type_total = lang_right = lang_total = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for case in cases:
        for doc in case.documents:
            found = {h.term_id for h in glossary.find_terms(doc.pages)}
            terms.add(found, doc.terms)
            predicted, _ = glossary.classify(doc.pages)
            confusion[doc.doc_type][predicted] += 1
            type_right += predicted == doc.doc_type
            type_total += 1
            lang_right += glossary.detect_language(" ".join(doc.pages)) == doc.language
            lang_total += 1
    chat_right = sum(glossary.detect_language(t) == lang for t, lang in CHAT_LANGUAGE_CASES)
    chat_errors = [(t, lang, glossary.detect_language(t)) for t, lang in CHAT_LANGUAGE_CASES if glossary.detect_language(t) != lang]

    def acc(name, right, total):
        return {"metric": name, "tp": right, "fp": total - right, "fn": total - right, "precision": right / total,
                "precision_ci": wilson(right, total), "recall": right / total, "recall_ci": wilson(right, total), "f1": right / total}

    rows = [terms.row("Glossary terms spotted"), acc("Document type (rule-based classifier), accuracy", type_right, type_total),
            acc("Document language, accuracy", lang_right, lang_total),
            acc(f"Chat message language (en / hi / Hinglish, {len(CHAT_LANGUAGE_CASES)} labelled), accuracy", chat_right, len(CHAT_LANGUAGE_CASES))]
    return rows, {"type_confusion": {k: dict(v) for k, v in confusion.items()}, "chat_language_errors": chat_errors}


# ---------- 3. Evidence flags ----------


def _case_docs(case: GenCase, facts_from: str = "gold") -> list:
    from app.models import CaseDocument

    docs = []
    for d in case.documents:
        docs.append(CaseDocument(id=uuid.uuid4(), filename=d.filename, status="processed", pages=d.pages,
                                 page_info=[{"source": "text"}] * len(d.pages), facts=json.loads(json.dumps(d.facts))))
    return docs


def score_flags(cases: list[GenCase]) -> list[dict]:
    """Flags computed from perfectly extracted facts (with the documents' varied wording), so this
    measures the flag logic itself: normalisation, Indian number formats, no false alarms."""
    from app.services.evidence import build_flags

    kinds = ("property_identifier_difference", "amount_difference")
    counts = {k: Counts() for k in kinds}
    total = Counts()
    for case in cases:
        raised = {f["kind"] for f in build_flags(_case_docs(case))} & set(kinds)
        for k in kinds:
            counts[k].add({case.case_id} if k in raised else set(), {case.case_id} if k in case.planted else set())
        total.add({(case.case_id, k) for k in raised}, {(case.case_id, k) for k in case.planted})
    return [counts["property_identifier_difference"].row("Survey-number difference flagged"),
            counts["amount_difference"].row("Advance-amount difference flagged"),
            total.row("**All planted discrepancies**")]


# ---------- 4. Provenance checking ----------


def score_provenance(cases: list[GenCase]) -> list[dict]:
    """For each receipt, offer intake.check_sources a mix of correct and bad document refs and count
    how many correct refs survive (recall) and how many kept refs are correct (precision)."""
    from app.services import intake

    kept_correct = Counts()
    for case in cases:
        docs = _case_docs(case)
        receipt, gen = docs[1], case.documents[1]
        good = f"D:{receipt.id}:p1"
        amount_text = gen.facts["amounts"][0]["value"]
        wrong_amount = f"Rs {case.advance + 1_234_000}"
        sheet = {
            "parties": [
                {"name": case.buyer, "role": "buyer", "sources": [good]},  # correct
                {"name": "Zubin Mehta" if case.language == "en" else "ज़ुबिन मेहता", "role": "x", "sources": [good]},  # not on the page
            ],
            "amounts": [
                {"description": "advance", "value": amount_text, "sources": [good]},  # correct (same wording)
                {"description": "advance", "value": wrong_amount, "sources": [good]},  # wrong value
                {"description": "advance", "value": amount_text, "sources": [f"D:{receipt.id}:p2"]},  # page doesn't exist
                {"description": "advance", "value": amount_text, "sources": [f"D:{uuid.uuid4()}:p1"]},  # unknown document
            ],
            "events": [{"date": next(iter(gen.dates)), "description": "advance paid", "sources": [good]}],  # correct
        }
        expected_kept = {("parties", 0), ("amounts", 0), ("events", 0)}
        out = intake.check_sources(sheet, docs, user_spoke=False)
        kept = {(key, i) for key in ("parties", "amounts", "events") for i, item in enumerate(out[key]) if item["sources"] != ["unverified"]}
        kept_correct.add(kept, expected_kept)
    return [kept_correct.row("Document refs kept only when the page supports the value")]


# ---------- 5. LLM extraction ----------


def score_llm(cases: list[GenCase]) -> list[dict]:
    from app.services import documents, nlp
    from app.services.evidence import _norm_id

    counts = {k: Counts() for k in ("amount", "date", "property_identifier", "party")}
    for case in cases:
        for doc in case.documents:
            facts = documents.extract_facts(doc.filename, doc.pages)
            pred = {
                "amount": {nlp.rupees(v) for a in facts["amounts"] if (v := nlp.amount_value(a["value"])) is not None},
                "date": {e["date"] for e in facts["events"] if e.get("date")} | ({facts["document_date"]} if facts.get("document_date") else set()),
                "property_identifier": {_norm_id(p["value"]) for p in facts["property_identifiers"]},
                "party": {_squash(p["name"]) for p in facts["parties"]},
            }
            gold = {"amount": doc.amounts, "date": doc.dates, "property_identifier": doc.ids, "party": {_squash(n) for n in doc.names}}
            for k in counts:
                counts[k].add(pred[k], gold[k])
    return [counts["amount"].row("LLM: amounts"), counts["date"].row("LLM: dates"),
            counts["property_identifier"].row("LLM: property identifiers"), counts["party"].row("LLM: parties")]


def score_llm_understanding(cases: list[GenCase]) -> list[dict]:
    """Plain-language explanations: how often the model's statements had to be dropped (values not in
    the document, advice), how often quotes were confirmed on the page, and how many of the document's
    key values the summary mentions."""
    from app.services import nlp, understanding

    kept = dropped = verified = 0
    coverage = Counts()
    for case in cases:
        for doc_gen, doc in zip(case.documents, _case_docs(case)):
            u = understanding.build_understanding(doc, "en")
            points = u["summary"] + u["clauses"]
            kept += len(points)
            dropped += sum(d["section"] in ("summary", "clauses") for d in u["dropped"])
            verified += sum(p.get("verified", False) for p in points)
            mentioned = {(m.kind, m.normalized) for p in u["summary"] for m in nlp.extract([p["text"]])}
            gold = {("amount", v) for v in doc_gen.amounts} | {("date", v) for v in doc_gen.dates} | {("property_identifier", v) for v in doc_gen.ids}
            coverage.add(mentioned & gold, gold)

    def rate(name, k, n):
        return {"metric": name, "tp": k, "fp": n - k, "fn": n - k, "precision": k / n if n else 1.0,
                "precision_ci": wilson(k, n), "recall": k / n if n else 1.0, "recall_ci": wilson(k, n), "f1": k / n if n else 1.0}

    total = kept + dropped
    return [rate("Explanation statements kept (not dropped for invented values / advice)", kept, total),
            rate("Kept statements whose quote was found on the cited page", verified, kept),
            coverage.row("Key values mentioned in the summary (recall = coverage)")]


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=int, default=200)
    parser.add_argument("--ocr-cases", type=int, default=40, help="cases to run through OCR (slower)")
    parser.add_argument("--qualities", nargs="+", default=["clean", "photo", "degraded"])
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--llm-cases", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    cases = generate(args.cases, args.seed)
    docs = sum(len(c.documents) for c in cases)
    langs = {l: sum(c.language == l for c in cases) for l in ("en", "hi")}
    print(f"{len(cases)} synthetic cases, {docs} documents ({langs}); planted discrepancies in "
          f"{sum(bool(c.planted) for c in cases)} cases\n", flush=True)

    report = {"run_at": datetime.now().isoformat(timespec="seconds"), "seed": args.seed, "cases": len(cases),
              "documents": docs, "languages": langs, "sections": {}}
    md = [f"Scorecard run {report['run_at']} · seed {args.seed} · {len(cases)} cases · {docs} documents · languages {langs}\n"]

    def section(key: str, title: str, rows: list[dict], note: str = ""):
        report["sections"][key] = {"title": title, "rows": rows, "note": note}
        text = f"### {title}\n\n{note + chr(10) + chr(10) if note else ''}{table(rows)}\n"
        md.append(text)
        print(text, flush=True)

    section("nlp_text", "1. Rule-based NLP on document text", score_nlp_text(cases))
    ocr_cases = cases[: args.ocr_cases]
    ocr_rows, ocr_info = score_ocr(ocr_cases, args.qualities) if ocr_cases else ([], {"skipped": "--ocr-cases 0"})
    if ocr_rows:
        speed = ", ".join(f"{q} {s:.1f} s/page" for q, s in ocr_info["seconds_per_page"].items())
        section("ocr", f"2. After OCR ({ocr_info['engine']}, {len(ocr_cases)} cases)", ocr_rows, f"Speed: {speed}.")
        report["sections"]["ocr"]["info"] = ocr_info
    else:
        section("ocr", "2. After OCR", [], f"Skipped: {ocr_info.get('skipped')}")
    und_rows, und_info = score_understanding(cases)
    section("understanding", "2b. Document understanding: legal terms, document type, language", und_rows,
            "For accuracy rows, precision = recall = accuracy and FP/FN both count the wrong answers.")
    report["sections"]["understanding"]["info"] = und_info
    if und_info["chat_language_errors"]:
        md.append("Chat language errors: " + "; ".join(f"“{t}” expected {e}, got {g}" for t, e, g in und_info["chat_language_errors"]) + "\n")
    section("flags", "3. Evidence flags (cross-document discrepancies)", score_flags(cases),
            f"Planted: {sum('property_identifier_difference' in c.planted for c in cases)} survey-number and "
            f"{sum('amount_difference' in c.planted for c in cases)} amount differences; the rest must raise no flag.")
    section("provenance", "4. Provenance checking of the fact sheet", score_provenance(cases),
            "Per case: 3 correct refs and 4 bad ones (name not on the page, wrong amount, page that doesn't exist, unknown document).")
    if args.llm:
        from app.config import get_settings

        if not get_settings().llm_api_key:
            print("--llm needs LLM_API_KEY in backend/.env", file=sys.stderr)
        else:
            section("llm", f"5. LLM document extraction ({args.llm_cases} cases)", score_llm(cases[: args.llm_cases]))
            section("llm_understanding", f"6. Plain-language explanations ({args.llm_cases} cases)",
                    score_llm_understanding(cases[: args.llm_cases]))

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"scorecard-{stamp}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=list))
    (RESULTS_DIR / f"scorecard-{stamp}.md").write_text("\n".join(md))
    print(f"Saved eval/results/scorecard-{stamp}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
