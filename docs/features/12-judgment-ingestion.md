# 12 · Judgment corpus and ingestion

## What it does
It builds the legal memory that search ([08](08-legal-search.md)) and chat use: Indian court judgments,
split into numbered paragraphs, summarised, and embedded. The target scope is **all property and land
dispute judgments from the Supreme Court and High Courts, kept up to date automatically**.

## How it is implemented today (Supreme Court)
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

## Planned: property-only, Supreme Court + High Courts, self-updating
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

## Results
- **Bug found by checking the live data:** the current loader keeps only rows whose language field says
  "ENG". For 2026 that field is empty for **242 of 245** judgments, yet the English PDFs exist. The fix
  (check the file, not the flag) is step 1 of the plan.
- A sample of filter selectivity: about 5–10% of judgments are property disputes (Supreme Court 2024:
  5.6% by keywords; a High Court bench: 4.8% by acts, before exclusions).
- **Filter precision/recall and retrieval recall@10 are not yet measured**; the plan includes a
  300-judgment labelled sample and ~30 labelled questions.
