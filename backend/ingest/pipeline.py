"""The ingestion pipeline: find new records → filter (4 stages) → store property judgments.

    partitions (SC years, HC year/court/bench)
      → skip if the metadata file's ETag is unchanged since the last complete run (incremental)
      → records not yet decided (accepted / rejected) or failed fewer than 3 times
      → stage 1 (metadata) → download PDF → text (OCR if scanned) → stage 2 (full text)
      → borderline: stage 3 (local semantic check) → still borderline: stage 4 (LLM, capped budget)
      → accepted: paragraphs + local embeddings stored (no LLM call); the summary is written later, on first open

Every decision is stored with its reasons in `ingestion_items`, so the filter is auditable and a
re-run never re-downloads what was already decided.
"""

import csv
import logging
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ingest import filters, semantic, sources
from ingest.store import DONE_STATUSES, MAX_ATTEMPTS

log = logging.getLogger("ingest")
SKIP_BENCHES = {"testcase"}  # a placeholder bench in the HC dataset
MAX_OCR_PAGES = 30
SEMANTIC_ACCEPT_MIN_SCORE = 5.5


@dataclass
class Config:
    sources: list[str] = field(default_factory=lambda: ["sc", "hc"])
    sc_years: list[int] | None = None  # None = all available
    hc_years: list[int] | None = None  # None = 2018..current
    hc_courts: list[str] = field(default_factory=lambda: ["27_1", "2_5", "9_13", "23_23"])
    limit: int | None = None  # max candidates downloaded and judged this run
    dry_run: bool = False
    full: bool = False  # ignore watermarks (re-scan unchanged partitions)
    reprocess: bool = False  # re-judge records already decided
    llm_budget: int = 0
    workers: int = 4
    sample_csv: str | None = None


@dataclass
class Partition:
    id: str  # "sc/2024" or "hc/2025/27_1/hcbgoa"
    source: str
    url: str
    load: object  # callable(etag) -> list[Record]


@dataclass
class Stats:
    partitions: int = 0
    unchanged: int = 0
    records: int = 0
    already_done: int = 0
    stage1_rejected: int = 0
    candidates: int = 0
    unavailable: int = 0
    failed: int = 0
    accepted: int = 0
    rejected: int = 0
    by_stage: Counter = field(default_factory=Counter)
    llm_calls: int = 0
    reasons: dict = field(default_factory=lambda: defaultdict(Counter))
    samples: dict = field(default_factory=lambda: defaultdict(list))
    tags: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {
            "partitions": self.partitions, "unchanged_partitions": self.unchanged, "records_seen": self.records,
            "already_decided": self.already_done, "stage1_rejected": self.stage1_rejected, "candidates": self.candidates,
            "pdf_unavailable": self.unavailable, "failed": self.failed, "accepted": self.accepted, "rejected": self.rejected,
            "decided_at_stage": dict(self.by_stage), "llm_calls": self.llm_calls, "tags": dict(self.tags),
        }


# ---------- Partitions ----------


def partitions(cfg: Config) -> list[Partition]:
    out = []
    if "sc" in cfg.sources:
        years = sources.sc_years()
        for y in [y for y in years if cfg.sc_years is None or y in cfg.sc_years]:
            out.append(Partition(f"sc/{y}", "sc", sources.sc_partition_url(y), lambda etag, y=y: sources.sc_records(y, etag)))
    if "hc" in cfg.sources:
        this_year = date.today().year
        years = cfg.hc_years or list(range(2018, this_year + 1))
        for y in years:
            available = set(sources.hc_courts(y))
            for c in [c for c in cfg.hc_courts if c in available]:
                for b in sources.hc_benches(y, c):
                    if b in SKIP_BENCHES:
                        continue
                    out.append(Partition(f"hc/{y}/{c}/{b}", "hc", sources.hc_partition_url(y, c, b),
                                         lambda etag, y=y, c=c, b=b: sources.hc_records(y, c, b, etag)))
    return out


# ---------- Text ----------


def document_text(pdf: bytes) -> str:
    """Selectable text; OCR (eng+hin) for scanned pages if an engine is installed."""
    import pymupdf

    from app.services import ocr

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = [p.get_text() for p in doc]
        engine = ocr.get_engine()
        if engine and sum(len(t.strip()) for t in pages) < 200:
            for i, page in enumerate(doc):
                if i >= MAX_OCR_PAGES:
                    break
                if ocr.page_needs_ocr(page, pages[i]):
                    pages[i] = engine.read(ocr.render_page(page)).text
    return "\n".join(pages)


def _fetch(rec) -> tuple[object, str | None, str | None]:
    """(record, text or None, error) — runs in a worker thread."""
    try:
        pdf = sources.fetch(rec.pdf_url)
        if pdf is None:
            return rec, None, "pdf not found (404)"
        text = document_text(pdf)
        if len(text.strip()) < 300:
            return rec, None, "no readable text (scanned and no OCR, or empty)"
        return rec, text, None
    except Exception as e:  # network / damaged PDF: retried on a later run
        return rec, None, f"error: {type(e).__name__}: {str(e)[:200]}"


# ---------- Building the judgment row ----------


def build_judgment(rec, text: str, decision: filters.Decision, extra: dict) -> tuple[dict, list]:
    from app.config import get_settings
    from app.services import glossary
    from app.services.embeddings import embed_documents
    from ingest.pdf_text import split_paragraphs

    paras = split_paragraphs(text)
    opening = " ".join(filter(None, [rec.title, rec.description, text[:2000]]))
    vectors = embed_documents([opening] + [t for _, t in paras])
    judgment = {
        "id": rec.key, "title": rec.title, "petitioner": rec.petitioner, "respondent": rec.respondent,
        "court": rec.court, "decision_date": rec.decision_date, "citation": rec.citation,
        "neutral_citation": rec.neutral_citation, "judges": rec.judges, "disposal": rec.disposal,
        "source_url": rec.pdf_url, "summary": {}, "summary_embedding": vectors[0],
        "source": rec.source, "court_code": rec.court_code, "bench": rec.bench, "cnr": rec.cnr,
        "case_type": rec.case_type, "headnote": rec.description or None, "acts": rec.acts,
        "topic_tags": extra.get("tags") or decision.tags, "property_score": filters.property_score(decision.score),
        "filter_evidence": {"stage": extra.get("stage", decision.stage), "score": decision.score,
                            "reasons": decision.reasons + extra.get("reasons", []), "statutes": decision.statutes},
        "language": glossary.detect_language(text[:4000]), "pdf_key": rec.pdf_key, "summary_status": "none",
        "embedding_model": get_settings().embedding_model, "pipeline_version": filters.PIPELINE_VERSION,
        "ingested_at": datetime.now(timezone.utc),
    }
    return judgment, [(n, t, v) for (n, t), v in zip(paras, vectors[1:], strict=True)]


# ---------- Deciding one candidate ----------


def decide(rec, text: str, cfg: Config, stats: Stats) -> tuple[str, filters.Decision, dict]:
    """('accept' | 'reject', stage-2 decision, extra info from later stages)."""
    d = filters.stage2(rec, text)
    if d.verdict != "borderline":
        return d.verdict, d, {"stage": "fulltext"}
    v3, margin, reasons3 = semantic.stage3(rec, text)
    # A semantic accept also needs some textual evidence (seen in real data: accepts at score 4.5 were wrong).
    if v3 == "reject" or (v3 == "accept" and d.score >= SEMANTIC_ACCEPT_MIN_SCORE):
        return v3, d, {"stage": "semantic", "reasons": reasons3 + [f"semantic margin {margin:+.3f}"]}
    if stats.llm_calls < cfg.llm_budget:
        stats.llm_calls += 1
        try:
            in_scope, tags, why = semantic.stage4(rec, text)
            return ("accept" if in_scope else "reject"), d, {"stage": "llm", "tags": tags, "reasons": reasons3 + [f"LLM: {why}"]}
        except Exception as e:
            log.warning("LLM check failed for %s: %s", rec.key, type(e).__name__)
    # Still undecided: accept only if the full-text score is in the upper half of the borderline band and
    # nothing was excluded (seen in real data: money-laundering and SEBI cases slipped through here).
    excluded = any(r.startswith("- excluded") for r in d.reasons)
    upper = d.score >= (filters.ACCEPT_AT + filters.REJECT_BELOW) / 2 and not excluded
    return ("accept" if upper else "reject"), d, {"stage": "undecided", "reasons": reasons3 + ["undecided: kept by score" if upper else "undecided: dropped by score"]}


# ---------- Run ----------


def run(cfg: Config, store) -> Stats:
    stats = Stats()
    run_id = store.start_run({k: v for k, v in cfg.__dict__.items()})
    status = "done"
    budget_left = cfg.limit if cfg.limit is not None else float("inf")
    sample_rows = []
    t0 = time.monotonic()
    try:
        parts = partitions(cfg)
        log.info("%d partitions in scope", len(parts))
        for p in parts:
            if budget_left <= 0:
                break
            etag, last_modified = sources.head(p.url)
            if etag is None:
                continue
            stats.partitions += 1
            if not cfg.full and not cfg.dry_run and store.watermark(p.id) == etag:
                stats.unchanged += 1
                continue
            records = p.load(etag)
            stats.records += len(records)
            known = store.known(p.source, [r.key for r in records])
            todo = []
            for r in records:
                k = known.get(r.key)
                if k and not cfg.reprocess and (k["status"] in DONE_STATUSES or k.get("attempts", 0) >= MAX_ATTEMPTS):
                    stats.already_done += 1
                    continue
                d1 = filters.stage1(r)
                if d1.verdict == "reject":
                    stats.stage1_rejected += 1
                    stats.reasons["stage1_reject"].update(d1.reasons[:2])
                    store.record_item(r, "rejected", "metadata", d1.score, d1.reasons, version=filters.PIPELINE_VERSION)
                    if cfg.sample_csv:
                        sample_rows.append([r.key, r.partition, "rejected", "metadata", d1.score, r.title, "; ".join(d1.reasons)])
                else:
                    todo.append(r)
            store.commit()
            partition_complete = True
            if len(todo) > budget_left:
                todo, partition_complete = todo[: int(budget_left)], False
            stats.candidates += len(todo)
            budget_left -= len(todo)
            log.info("%s: %d records, %d candidates", p.id, len(records), len(todo))
            with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
                for rec, text, error in pool.map(_fetch, todo):
                    if text is None:
                        if error and error.startswith("pdf not found"):
                            stats.unavailable += 1
                            store.record_item(rec, "unavailable", "download", None, [error], version=filters.PIPELINE_VERSION)
                        else:
                            stats.failed += 1
                            store.record_item(rec, "failed", "download", None, [], error=error, version=filters.PIPELINE_VERSION)
                        store.commit()
                        continue
                    verdict, d, extra = decide(rec, text, cfg, stats)
                    stage = extra.get("stage", "fulltext")
                    stats.by_stage[f"{verdict}@{stage}"] += 1
                    reasons = d.reasons + extra.get("reasons", [])
                    if verdict == "accept":
                        stats.accepted += 1
                        tags = extra.get("tags") or d.tags
                        stats.tags.update(tags)
                        if not cfg.dry_run:
                            judgment, paras = build_judgment(rec, text, d, extra)
                            store.save_judgment(judgment, paras)
                        store.record_item(rec, "accepted", stage, d.score, reasons, version=filters.PIPELINE_VERSION)
                    else:
                        stats.rejected += 1
                        store.record_item(rec, "rejected", stage, d.score, reasons, version=filters.PIPELINE_VERSION)
                    stats.reasons[f"{verdict}@{stage}"].update(reasons[:2])
                    if len(stats.samples[verdict]) < 15:
                        stats.samples[verdict].append(f"[{d.score:5.1f} {stage}] {rec.title[:110]}")
                    if cfg.sample_csv:
                        sample_rows.append([rec.key, rec.partition, verdict, stage, d.score, rec.title, "; ".join(reasons)])
                    store.commit()
                    done = stats.accepted + stats.rejected
                    if done % 25 == 0:
                        log.info("  … %d judged (%d accepted), %.0fs", done, stats.accepted, time.monotonic() - t0)
            if partition_complete and not cfg.dry_run:  # a dry run must not make the next real run skip this partition
                store.set_watermark(p.id, etag, last_modified, len(records))
    except KeyboardInterrupt:
        status = "interrupted"
        log.warning("interrupted: progress so far is saved; run again to continue")
    except Exception:
        status = "error"
        raise
    finally:
        store.finish_run(run_id, stats.as_dict() | {"seconds": round(time.monotonic() - t0)}, status)
        if cfg.sample_csv and sample_rows:
            with open(cfg.sample_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["key", "partition", "decision", "stage", "score", "title", "reasons", "label (property? y/n)"])
                w.writerows(sample_rows)
    return stats


def report(stats: Stats, dry_run: bool) -> str:
    s = stats
    lines = [
        "",
        "DRY RUN: nothing was stored." if dry_run else "Ingestion run complete.",
        f"Partitions: {s.partitions} ({s.unchanged} unchanged since last run, skipped)",
        f"Records seen: {s.records} · already decided: {s.already_done} · rejected by metadata: {s.stage1_rejected}",
        f"Candidates judged: {s.candidates} → accepted {s.accepted} · rejected {s.rejected} · "
        f"PDF unavailable {s.unavailable} · failed (will retry) {s.failed}",
        f"Decided at: {dict(s.by_stage)} · LLM calls: {s.llm_calls}",
    ]
    if s.tags:
        lines.append("Topic tags: " + ", ".join(f"{t} {n}" for t, n in s.tags.most_common()))
    for key in ("accept", "reject"):
        if s.samples.get(key):
            lines.append(f"\nSample {key}ed:")
            lines += [f"  {t}" for t in s.samples[key]]
    if s.reasons.get("stage1_reject"):
        lines.append("\nTop metadata-rejection reasons: " + "; ".join(f"{r} ({n})" for r, n in s.reasons["stage1_reject"].most_common(4)))
    return "\n".join(lines)
