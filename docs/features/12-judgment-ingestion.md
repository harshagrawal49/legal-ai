# 12 · Judgment corpus and ingestion

## What it does
It builds the legal memory that search ([08](08-legal-search.md)) and chat use: Indian court judgments,
split into numbered paragraphs, summarised, and embedded. The target scope is **all property and land
dispute judgments from the Supreme Court and High Courts, kept up to date automatically**.

## One command

```bash
cd backend && uv run python -m ingest            # incremental; --dry-run needs no database
```
Details, options and real-data findings: [`../../ingest_plan.md`](../../ingest_plan.md) §13.

## How it was first implemented (older Supreme Court loader, still available)
1. **Source:** the public *Indian Supreme Court Judgments* dataset on AWS Open Data (metadata as yearly
   Parquet files, plus PDFs), read over HTTPS with a local download cache.
2. **Selection:** by year, with an optional keyword match on title and description, and a limit per run.
3. **Text:** PDF text extraction, then **paragraph segmentation** that follows the judgment's own
   numbering (`1.`, `2.`…), so ¶N in our app matches the judgment. Header text goes into ¶0. If no
   numbering is found, it falls back to fixed-size chunks.
4. **Summary:** one bulk-model call per judgment into a validated `JudgmentSummary`: case type, facts,
   issues, holding, outcome, prevailing party, acts cited, legal areas, key principles, key paragraphs.
5. **Embeddings:** a local model (bge-small) for every paragraph and the summary; stored in PostgreSQL /
   pgvector, with a GIN full-text index on paragraphs.
6. **Re-runs are safe:** judgments already ingested are skipped.

## Now implemented: property-only, Supreme Court + High Courts, self-updating
Full design: [`../../ingest_plan.md`](../../ingest_plan.md). Key points, checked against the live datasets:
- **Both datasets are public and updated regularly.** They cover 1950–2026; the 2026 Supreme Court file
  was last modified on 2026-10-17. The High Court dataset is organised by year → court → bench across 25
  court codes.
- **Cheap filtering signals before downloading anything:**
  - Supreme Court headnotes ("Issue for Consideration…");
  - High Court case-type codes in the title (SA, FA, AO = civil appeals);
  - for some High Courts, **the acts and sections of each case** (e.g. Transfer of Property Act, Specific
    Relief Act).
- **Staged filter:**
  - metadata;
  - full text (statutes, glossary terms, cue phrases, exclusions);
  - similarity to ~30 hand-picked seed judgments;
  - an LLM check only for borderline cases, capped per run.

  Real-data checks showed why: simple keywords catch criminal "possession" (of contraband) and procedural
  "Limitation Act s.5" cases.
- **Lazy summaries:** no LLM call at ingestion; a judgment is summarised when it first appears in a search.
- **Incremental updates:**
  - High Court archives gain timestamped `part-*.tar` files and an index with `updated_at`;
  - Supreme Court yearly files change their ETag;
  - a weekly, idempotent job ingests only what's new, with a retry queue, run reports and a corpus-stats
    endpoint.

## Why this approach
| Alternative | Why not |
|---|---|
| Scraping eCourts / court websites | CAPTCHAs, no bulk API, terms of use; the open datasets come from the same sources |
| Indian Kanoon API / commercial databases | Paid per request or licensed; redistribution limits |
| Fixed-size chunks only | Lose the judgment's own paragraph numbers, so citations like ¶12 wouldn't match the original |
| Summarising every judgment at ingestion | Thousands of LLM calls; not feasible on a free tier, and most judgments are never retrieved |

## Results (dry runs on live data)
- **Supreme Court 2024:** 782 judgments → 651 downloaded → **154 accepted (19.7%)**.
- **Bombay High Court at Goa, 2025:** 1,466 orders → 109 downloaded → **16 accepted**, mostly second
  appeals and appeals from orders.
- **Fixed:** the old loader skipped rows whose language flag was empty, which in 2026 was **242 of 245**
  judgments even though their PDFs exist.
- **Finding:** Supreme Court metadata has **no headnote before 2024**, so those judgments are judged on
  full text.
- Several false positives found in the dry runs were fixed (see `ingest_plan.md` §13).
- **Filter precision/recall is not yet measured.** Tooling is ready: `--sample-csv` plus
  `python -m ingest.evaluate`. Retrieval recall@10 also needs a labelled question set.
