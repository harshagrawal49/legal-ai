"""Compare the OCR engines (Tesseract, PaddleOCR) on the same synthetic scans.

    uv run python -m eval.run_ocr_eval                    # every installed engine
    uv run python -m eval.run_ocr_eval --engines tesseract paddle-mobile
    uv run python -m eval.run_ocr_eval --qualities clean photo

For each dataset x engine x quality level (eval/scans.py: clean, photo, degraded), every page is
scanned synthetically, OCR'd, and compared with the original text. Datasets: `english` (the 3 sample
documents, 4 pages) and `hindi` (a Hindi receipt with Devanagari numerals and a Hindi agreement
extract; needs a Devanagari font, which macOS ships). Metrics:
- CER / WER: character / word error rate (edit distance / reference length; lower is better);
- key values: share of the names, survey numbers and amounts from eval/samples.py EXPECTED that
  survive OCR exactly, which matters most, because these feed the evidence flags;
- seconds per page and mean engine confidence;
- low-confidence rate: share of pages below OCR_MIN_CONFIDENCE (these would be flagged in the app).

No LLM and no API key are needed. Results go to eval/results/ocr-<timestamp>.json.
Benchmark size is small (3 documents, 4 pages); use it to compare engines, not as an accuracy claim.
"""

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pymupdf

from app.config import get_settings
from app.services import ocr
from eval.samples import BENCHMARK_VERSION, EXPECTED, SAMPLES
from eval.samples import make_pdf
from eval.scans import (
    DEVANAGARI_KEY_VALUES, DEVANAGARI_SAMPLES, QUALITIES, devanagari_font, make_devanagari_pdf, scan_pdf,
)

RESULTS_DIR = Path(__file__).parent / "results"


def edit_distance(a: list | str, b: list | str) -> int:
    """Levenshtein distance (works on strings or word lists)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def error_rates(reference: str, hypothesis: str) -> tuple[float, float]:
    ref, hyp = _clean(reference), _clean(hypothesis)
    cer = edit_distance(ref, hyp) / max(len(ref), 1)
    wer = edit_distance(ref.split(), hyp.split()) / max(len(ref.split()), 1)
    return cer, wer


def _english() -> list[tuple[str, list[str], bytes, list[str]]]:
    """(filename, page texts, text PDF, key values) for the English benchmark documents."""
    out = []
    for filename, texts in SAMPLES.items():
        e = EXPECTED[filename]
        out.append((filename, texts, make_pdf(texts), e["parties"] + e["property_identifiers"] + e["amounts"]))
    return out


def _hindi() -> list[tuple[str, list[str], bytes, list[str]]]:
    if devanagari_font() is None:
        print("skip hindi set: no Devanagari font found (install Noto Sans Devanagari)")
        return []
    return [(f, texts, make_devanagari_pdf(texts), DEVANAGARI_KEY_VALUES[f]) for f, texts in DEVANAGARI_SAMPLES.items()]


DATASETS = {"english": _english, "hindi": _hindi}


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def evaluate(engine: ocr.OcrEngine, quality: str, dataset: str, documents: list) -> dict:
    min_conf = get_settings().ocr_min_confidence
    pages, found, total_keys, missed = [], 0, 0, []
    for filename, texts, source_pdf, keys in documents:
        pdf = pymupdf.open(stream=scan_pdf(source_pdf, quality), filetype="pdf")
        doc_text = []
        for n, (page, reference) in enumerate(zip(pdf, texts), start=1):
            started = time.monotonic()
            result = engine.read(ocr.render_page(page))
            seconds = time.monotonic() - started
            cer, wer = error_rates(reference, result.text)
            pages.append({"document": filename, "page": n, "cer": cer, "wer": wer, "seconds": seconds,
                          "confidence": result.confidence, "text": result.text})
            doc_text.append(result.text)
        joined = _squash("\n".join(doc_text))
        hits = [k for k in keys if _squash(k) in joined]
        found += len(hits)
        total_keys += len(keys)
        missed += [k for k in keys if k not in hits]
        pdf.close()
    confidences = [p["confidence"] for p in pages if p["confidence"] is not None]
    return {
        "engine": engine.name,
        "dataset": dataset,
        "quality": quality,
        "pages": len(pages),
        "cer": statistics.fmean(p["cer"] for p in pages),
        "wer": statistics.fmean(p["wer"] for p in pages),
        "key_value_recall": found / total_keys,
        "seconds_per_page": statistics.fmean(p["seconds"] for p in pages),
        "mean_confidence": statistics.fmean(confidences) if confidences else None,
        "low_confidence_rate": sum(c < min_conf for c in confidences) / len(pages),
        "missed_key_values": sorted(set(missed)),
        "page_results": pages,
    }


def recommend(rows: list[dict]) -> str:
    """Per dataset: the engine with the most key values read exactly on photo/degraded scans (CER breaks
    ties), unless it is more than 3x slower than the fastest; then the trade-off is reported."""
    lines = []
    for dataset in dict.fromkeys(r.get("dataset", "english") for r in rows):
        subset = [r for r in rows if r.get("dataset", "english") == dataset]
        realistic = [r for r in subset if r["quality"] in ("photo", "degraded")] or subset
        by_engine: dict[str, list[dict]] = {}
        for r in realistic:
            by_engine.setdefault(r["engine"], []).append(r)
        if len(by_engine) < 2:
            lines.append(f"{dataset}: only {next(iter(by_engine), 'no engine')} was tested; install more engines to compare.")
            continue
        score = {
            e: (statistics.fmean(r.get("key_value_recall", 0) for r in rs), statistics.fmean(r["cer"] for r in rs),
                statistics.fmean(r["seconds_per_page"] for r in rs))
            for e, rs in by_engine.items()
        }
        best = max(score, key=lambda e: (score[e][0], -score[e][1]))
        fastest = min(score, key=lambda e: score[e][2])
        k, c, t = score[best]
        if best != fastest and t > 3 * score[fastest][2]:
            lines.append(f"{dataset}: {best} is most accurate (key values {k:.0%}, CER {c:.1%}) but "
                         f"{t / score[fastest][2]:.1f}x slower than {fastest}; choose by priority (accuracy vs speed).")
        else:
            lines.append(f"{dataset}: recommended {best} (key values {k:.0%}, CER {c:.1%}, {t:.1f} s/page on photo/degraded scans).")
    return "\n".join(lines)


def _machine() -> dict:
    import platform

    info = {"platform": platform.platform(), "processor": platform.processor(), "python": platform.python_version()}
    try:
        import pytesseract

        info["tesseract"] = str(pytesseract.get_tesseract_version())
    except Exception:
        pass
    for package in ("paddleocr", "paddle"):
        try:
            info[package] = __import__(package).__version__
        except Exception:
            pass
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engines", nargs="+", default=list(ocr.BENCHMARK_ENGINES), choices=list(ocr.BENCHMARK_ENGINES))
    parser.add_argument("--qualities", nargs="+", default=list(QUALITIES), choices=list(QUALITIES))
    parser.add_argument("--sets", nargs="+", default=list(DATASETS), choices=list(DATASETS))
    args = parser.parse_args()

    engines = []
    for name in args.engines:
        engine = ocr.BENCHMARK_ENGINES[name]
        if engine.available():
            engines.append(engine)
        else:
            print(f"skip {name}: not installed (see docs/ocr_steps.md)")
    if not engines:
        print("No OCR engine installed.", file=sys.stderr)
        return 2

    rows = []
    print(f"\n{'set':<11} {'engine':<18} {'quality':<9} {'CER':>7} {'WER':>7} {'key values':>11} {'s/page':>7} {'conf':>6}")
    for dataset in args.sets:
        documents = DATASETS[dataset]()
        if not documents:
            continue
        for engine in engines:
            for quality in args.qualities:
                r = evaluate(engine, quality, dataset, documents)
                rows.append(r)
                conf = f"{r['mean_confidence']:.0f}" if r["mean_confidence"] is not None else "-"
                print(f"{dataset:<11} {r['engine']:<18} {r['quality']:<9} {r['cer']:>7.1%} {r['wer']:>7.1%} "
                      f"{r['key_value_recall']:>11.0%} {r['seconds_per_page']:>7.1f} {conf:>6}", flush=True)
                if r["missed_key_values"]:
                    print(f"{'':<39}missed: {', '.join(r['missed_key_values'])}", flush=True)

    advice = recommend(rows)
    print(f"\n{advice}")
    s = get_settings()
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"ocr-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({
        "benchmark_version": BENCHMARK_VERSION,
        "settings": {"ocr_languages": s.ocr_languages, "ocr_paddle_lang": s.ocr_paddle_lang, "ocr_dpi": s.ocr_dpi},
        "machine": _machine(),
        "recommendation": advice,
        "results": rows,
    }, indent=2, ensure_ascii=False))
    print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
