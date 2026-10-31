# Judgment ingestion plan: property and land disputes (Supreme Court + High Courts)

> Goal: a searchable corpus of **all property and land dispute judgments** from the Supreme Court
> of India and the High Courts, **kept up to date automatically** as new judgments are published.
> Status: **implemented** (2026-11-01). One command: `cd backend && uv run python -m ingest`.
> Facts marked ✅ were checked against the live datasets on 2026-10-31. Implementation notes and the
> real-data findings that changed the design are in §13.

---

## 1. What counts as a "property / land dispute"

We need an explicit definition, both to filter and to evaluate the filter. A judgment is **in scope**
if its main subject is one of these (one judgment can have several tags):

| Tag | Typical matters | Typical laws / signals |
|---|---|---|
| `sale_contract` | Agreement to sell, refund of advance, **specific performance**, double sale | Specific Relief Act 1963; Transfer of Property Act (TPA) s.54, 53A |
| `title_ownership` | Declaration of title, cancellation of a sale deed, void or forged deeds | Specific Relief Act s.31, 34; TPA; Registration Act |
| `possession_injunction` | Recovery of possession, encroachment, trespass, injunctions | CPC Order 39; Specific Relief Act s.5, 6, 38 |
| `partition_inheritance` | Partition of joint/ancestral property, shares of heirs, wills affecting property | Hindu Succession Act; Indian Succession Act; Partition Act |
| `land_records` | Mutation, 7/12, khasra/khatauni/jamabandi entries, revenue-court orders | State Land Revenue Codes |
| `land_acquisition` | Acquisition, compensation, rehabilitation | Land Acquisition Act 1894; RFCTLARR Act 2013 |
| `tenancy_rent` | Eviction, rent control, agricultural tenancy | State Rent Control Acts; Tenancy Acts |
| `builder_rera` | Flat buyers vs builders, possession delay, refund | RERA 2016; Consumer Protection Act |
| `easement` | Right of way, light and air | Indian Easements Act 1882 |
| `adverse_possession` | Title claims by long possession | Limitation Act Art. 65 |
| `property_fraud` | Forged sale deeds, impersonation, cheating in property deals | IPC 420, 467, 468, 471 / BNS equivalents, **only together with a property context** |
| `benami_mortgage` | Benami property, mortgages, redemption | Benami Act 1988; TPA s.58–60 |

**Out of scope**, even though they use the same words:
- "possession" of drugs or arms (NDPS / Arms Act);
- "Limitation Act s.5" condonation of delay on its own (procedural, any subject);
- income-tax cases about property income;
- service matters;
- company or arbitration matters with no property dispute.

Real-data checks showed these are the main false positives (§3).

---

## 2. Sources

### 2.1 Used

| Source | What it is | Access | Use |
|---|---|---|---|
| **Indian Supreme Court Judgments** (AWS Open Data) `s3://indian-supreme-court-judgments` | All reported SC judgments: metadata + PDFs | Public bucket, HTTPS, no key | **Primary** |
| **Indian High Court Judgments** (AWS Open Data) `s3://indian-high-court-judgments` | Judgments/orders from ~25 High Courts (from eCourts) | Public bucket, HTTPS, no key | **Primary** (the bulk of property litigation) |

### 2.2 Considered, not used now

| Source | Why not (now) |
|---|---|
| eCourts portal (district courts, HC sites) | CAPTCHA, no bulk API, scraping may violate terms; district judgments have little precedent value |
| Indian Kanoon API | Good coverage, but paid per request and limits on redistribution; maybe for targeted lookups later |
| SCC Online, Manupatra | Commercial, licensed |
| NJDG | Statistics only (pendency), not judgment text; useful for the presentation |
| RERA authorities, revenue tribunals | Spread across many state websites with inconsistent formats; later |

### 2.3 Reuse rights

Indian copyright law permits reproducing judgments and orders of courts (Copyright Act 1957,
s.52(1)(q)(iv)), unless a court prohibits it. **Before the corpus is used outside the college
project:** read each AWS Open Data dataset's licence on its registry page, credit the dataset in the app
("Source: Indian Supreme Court / High Court Judgments, AWS Open Data"), and keep the original PDF link
for every judgment (we already store `source_url`).

---

## 3. Facts about the data (checked ✅)

### Supreme Court bucket
- ✅ `metadata/parquet/year=YYYY/metadata.parquet`, years **1950–2026**. The 2026 file was last modified
  **2026-10-17**, so it is updated regularly. 2024 has 782 rows; 2026 (so far) 245.
- ✅ Columns: `title, petitioner, respondent, description, judge, author_judge, citation, case_id, cnr,
  decision_date, disposal_nature, court, available_languages, raw_html, path, nc_display, scraped_at, year`.
- ✅ `description` contains the **headnote / "Issue for Consideration"** (median ~545 characters), a rich,
  cheap filtering signal before downloading any PDF.
- ✅ PDFs: `data/pdf/year=YYYY/english/<path>_EN.pdf` and `data/pdf/year=YYYY/regional/…` (other
  languages, including Hindi). Also `metadata/json/`, `metadata/tar/` and tar archives for bulk download.
- ⚠️ **Bug in our current loader** (`ingest/supreme_court.py:53`): it keeps only rows whose
  `available_languages` contains "ENG". In 2026 that field is **empty for 242 of 245 rows**, yet the
  English PDFs exist (checked: `2026_2_107_127_EN.pdf` returns HTTP 200). **Fix: try the English PDF
  for every row and treat a 404 as "not available".**

### High Court bucket
- ✅ Same layout, partitioned by **year → court → bench**: `metadata/parquet/year=2025/court=27_1/bench=hcbgoa/metadata.parquet`.
  Years 1950–2026; **25 court codes** in 2025 (see §3.1). `court=27_1` is Bombay High Court, with benches
  such as `newas` / `newos` (principal seat), `hcaurdb` (Aurangabad), `hcbgoa` (Goa) and `kolhcdb` (Kolhapur).
- ✅ Columns: `court_code, title, description, judge, pdf_link, cnr, date_of_registration,
  decision_date, disposal_nature, court, raw_html, pdf_exists`.
- ✅ The `title` starts with the **case-type code**, e.g. `WP/238/2023 …`. Goa 2025 counts: WP 533,
  MCA 299, CRMA 98, … SA 30, FA 26, AO 11. Second appeals (SA), first appeals (FA), appeals from
  orders (AO, often injunctions) and civil suits are where property disputes concentrate.
- ✅ `description` is the first ~300 characters of the judgment (median 291).
- ⚠️ `pdf_exists` was **False for all 1,466 Goa rows**, yet the PDFs are in the bucket. The key is
  `data/pdf/year=Y/court=C/bench=B/<basename of pdf_link>` (checked: HTTP 200). **Don't trust `pdf_exists`; check the object.**
- ✅ **`metadata/parquet_case_details/court=C/bench=B/case_details-mobile.parquet`** (currently for 4
  courts: `2_5`, `9_13`, `23_23`, `27_1`) has `case_type`, petitioner/respondent, advocates, `lower_court`,
  `linked_cases`, hearings, and **`acts`: a list of {act, section}** (e.g. `{'act': 'ARBITRATION AND
  CONCILIATION ACT', 'section': '11'}`). This is the most precise filter available, where it exists.
- ✅ **Incremental archives:** `data/tar/year=Y/court=C/bench=B/` holds a big `data.tar` plus
  timestamped `part-20260624T200239Z.tar` files added as new judgments arrive, and a
  **`data.index.json`** (`file_count`, `updated_at`, and the list of files in each part). This is how we detect
  new judgments without re-reading everything (§7).

### Measured filter selectivity (small samples)
- Goa HC 2025 case details: 64 / 1,324 rows (4.8%) matched a first "property acts" list, but the top
  matches were **"Limitation Act s.5"** (condonation of delay), a false positive. The act list needs exclusions.
- SC 2024: 44 / 782 (5.6%) matched property keywords in title + headnote. SC 2026: 45 / 245 (18.4%), but
  these included **criminal matters** ("possession" of contraband, Enforcement Directorate). Keywords
  alone aren't enough.

→ Expect roughly **5–10% of judgments** to be property or land disputes, and use **staged filtering
with exclusions and a final score** (§4).

### 3.1 High Courts in the dataset

_(Being filled from the dataset: court code → name, benches, 2025 metadata size. See the survey
output at the end of this section once complete.)_

---

## 4. Pipeline

```
          ┌──────────────── catalogue sync (metadata only, cheap) ───────────────┐
 SC/HC ──►│ new/changed metadata rows → ingestion_items (status = new)           │
 bucket   └──────────────────────────────────────────────────────────────────────┘
                │
   Stage 1      ▼  metadata filter (no download): case-type codes, acts/sections, headnote keywords,
                   exclusions → candidate / rejected (reason kept)
   Stage 2      ▼  download PDF → text (PyMuPDF; OCR for scans) → full-text scoring:
                   statute citations, glossary terms (app/services/glossary.py), cue phrases,
                   exclusions → property score + topic tags
   Stage 3      ▼  local semantic check: similarity to ~30 hand-picked seed judgments (bge embeddings)
   Stage 4      ▼  only for borderline scores: one small LLM yes/no + tags on the first ~3k characters (flash-lite)
                │
   Store        ▼  paragraphs + embeddings (local, free) + metadata + tags + score
   On demand    ▼  LLM summary only when a judgment first appears in a search result (then cached)
```

### Stage 1: metadata filter (all rows; no PDF download)

Score = sum of signals, with hard exclusions:

| Signal | Source | Examples |
|---|---|---|
| Case-type code (HC) | `title` prefix / `case_type` | strong: SA, RSA, FA, RFA, AO, CS, OS, CRP, LPA (when civil); weak: WP, MCA; negative: CRMA, CRMAB, WPCR, TXA, BA |
| Acts and sections (HC with case details) | `acts` | strong: Transfer of Property Act, Specific Relief Act, Registration Act, Land Revenue Code, Rent Control, Tenancy, Land Acquisition / RFCTLARR, RERA, Easements, Benami, Hindu Succession (with partition); IPC 420/467/468/471 **only with a property term**; **excluded alone:** Limitation Act s.5, Constitution 226/227 |
| Headnote keywords (SC) | `description` (headnote) | "specific performance", "agreement to sell", "sale deed", "title", "possession" (with property words), "partition", "mutation", "encroachment", "adverse possession", "land acquisition", "tenant", "eviction", "easement", "benami" |
| Party names | `petitioner` / `respondent` / `title` | "Developers", "Builders", "Housing Society", "Land Acquisition Officer", "Collector", "Tehsildar" (weak) |
| Exclusions | any | NDPS, Arms Act, "bail" without a property context, Income Tax / GST, service matters |

Output: `candidate` (score ≥ threshold) or `rejected` with the reasons stored, so the filter is
auditable and can be re-run with new rules without re-downloading anything.

### Stage 2: full-text scoring (candidates only)
- Download the PDF (English; Hindi from SC `regional/` and Hindi-language HCs), extract text with
  PyMuPDF, and OCR scanned pages with Tesseract `eng+hin` (built already).
- Score on the full text:
  - statutes cited (regex for acts and sections);
  - glossary terms found (agreement to sell, sale deed, khasra, mutation…);
  - cue phrases ("suit for specific performance", "decree for possession", "partition suit");
  - exclusions.
- Assign **topic tags** (§1) with rules. Keep `property_score` (0–1) and the matched evidence
  (which terms or acts, and where) for review.

### Stage 3: local semantic check
- Embed the judgment's first ~2,000 characters plus its headnote. Compare with ~30 **seed judgments** we
  label by hand: 15 clearly property (one or two per tag) and 15 look-alikes that aren't (NDPS
  possession, tax on property income, service).
- Use this to confirm or reject borderline Stage 2 scores. It's free and runs on the CPU.

### Stage 4: LLM check (borderline only)
- One flash-lite call on the first ~3k characters: `{in_scope: bool, tags: [...], reason}`. Expect it
  for only ~10–20% of candidates; hard-capped per run (e.g. 200 a day) to stay within the free tier.

### Storage and summaries
- Store paragraphs and local embeddings for every accepted judgment; **no LLM call at ingestion**.
- **Lazy summary:** the first time a judgment appears among search candidates, summarise it with the
  bulk model and cache it. The search step needs a small change: it falls back to paragraphs when a
  summary is missing. This is what makes "all property judgments" affordable on the free tier.
- **Deduplication:**
  - one row per judgment (SC `path`, HC `cnr` + order date);
  - SC appeals that arose from HC judgments we also hold are linked through `lower_court` /
    `linked_cases` where available, so search can show "appeal decided by the Supreme Court".

---

## 5. Data model changes

`judgments` (existing), with new columns:

| Column | Meaning |
|---|---|
| `source` | `sc` / `hc` |
| `court_code`, `bench` | e.g. `27_1`, `hcbgoa` |
| `cnr` | eCourts case number (HC dedupe; links to case details) |
| `case_type` | e.g. SA, FA, CA |
| `acts` | JSONB list of {act, section} (from metadata or extracted) |
| `topic_tags` | JSONB, e.g. `["sale_contract", "property_fraud"]` |
| `property_score`, `filter_evidence` | Stage 2–4 outcome and why |
| `language` | `en` / `hi` |
| `pdf_key` | object key in the bucket (re-download, audit) |
| `summary_status` | `none` / `done` (lazy summaries) |
| `embedding_model`, `pipeline_version` | to re-process only what changes when the model or rules change |
| `ingested_at` | |

New tables:
- `ingestion_items`: one row per source record seen: `source, key, partition (year/court/bench),
  status (new → rejected | candidate → accepted | failed), stage, score, reasons, attempts, last_error,
  first_seen_at, updated_at`. It's a queue for retries and the audit trail.
- `ingestion_runs`: one row per run: started/finished, partitions scanned, rows seen, new, accepted,
  rejected, failed, LLM calls used, duration.
- `source_partitions`: the **watermark** per partition: last seen `ETag` / `LastModified` of each
  metadata parquet, and the last `data.index.json` `updated_at` and part names (§7).

The schema is now big enough to move from `create_all` plus `ADD COLUMN IF NOT EXISTS` to **Alembic migrations**.

---

## 6. Scale and cost (estimates; verify with a dry run)

- **SC:** about 780 judgments a year recently (2024); a few tens of thousands in total. At ~5–10% in
  scope, that's **~2–4k property judgments**.
- **HC:** far larger (thousands per court per year; the Goa bench alone had 1,466 orders in 2025). Start
  with selected courts and recent years (§9), then expand.
- **Storage:** one 384-d vector is ~1.5 KB. 10k judgments × ~60 paragraphs ≈ 600k vectors ≈ **1–2 GB**
  in Postgres with the index. That's fine on a laptop; hundreds of thousands of judgments need a hosted database.
- **Downloads:** metadata is small (MBs per court-year). PDFs are ~20–200 KB each; download only
  Stage 1 candidates (~10–20%).
- **LLM:** none at ingestion except Stage 4 (capped); summaries are lazy.
- **Time:** the metadata scan takes minutes; PDF + text + embeddings ~1–2 s per judgment on CPU (OCR adds ~1 s per scanned page).

`--dry-run` mode: run Stages 1–3 on a partition and print counts, top reasons and 20 sample titles
per decision, **without storing anything**. Always do this before a big ingest.

---

## 7. Keeping it up to date (dynamic ingestion)

### 7.1 Detecting what's new (no full re-scan)

| Source | Change signal | Incremental action |
|---|---|---|
| SC | `metadata/parquet/year=Y/metadata.parquet` **ETag / LastModified** changed (2026 changed on 2026-10-17) | Re-read only that year's parquet (≤1 MB); new rows are those whose `path` isn't in `ingestion_items` |
| HC | `data/tar/…/data.index.json` `updated_at` changed, and **new `part-*.tar` names** appear | Take the new file names from the index; match them to metadata rows (`pdf_link` basename); queue only those |
| HC | `metadata/parquet/year=Y/court=C/bench=B/metadata.parquet` ETag changed | Diff the rows by `cnr` + date |
| Both | A new `year=` partition appears (e.g. 2027) | Add it to `source_partitions` automatically |

Only the current and previous year are checked each run (late uploads land there). Older years are
checked monthly, by ETag only, which is cheap.

### 7.2 The update job

```bash
uv run python -m ingest.update               # all configured sources: detect → filter → ingest → report
uv run python -m ingest.update --dry-run     # show what would be added
```

It is **idempotent**: it can be re-run any time, and it processes only `ingestion_items` not yet done.
Failed items are retried with backoff up to N times; after that they're kept as `failed` with the error.
The LLM budget per run is capped.

### 7.3 Scheduling options

| Option | Good for | Notes |
|---|---|---|
| **macOS `launchd` / `cron`** on the laptop | The college demo | Weekly (e.g. Sunday night); runs only when the laptop is on; logs to a file |
| **GitHub Actions scheduled workflow** | Always-on without a server | Needs a hosted Postgres with pgvector (e.g. Supabase); check free-tier limits for minutes and DB size |
| **Server cron / a small worker** (e.g. Render, Fly.io) | When the backend is deployed | Same command; add alerting |

### 7.4 Monitoring and corrections
- `GET /corpus/stats`: counts by source, court, year and tag; last run; last new judgment date. The app
  shows "Judgments updated on <date>" on the Similar cases screen.
- The run report (`ingestion_runs`) is printed, and alerts if a source hasn't changed for longer than
  expected (a broken source) or if failures spike.
- **Corrections:** if a metadata row changes (same key, different content), re-process that item.
- **Precedent status (later):** a judgment can be overruled or reversed on appeal. Phase 2: extract
  citations ("relied on", "overruled") to build a citation graph, and link SC appeals to HC judgments,
  so search can warn "this judgment was later reversed".

### 7.5 Re-processing when the rules or models change
`pipeline_version` and `embedding_model` on each judgment let `ingest.update --reprocess` redo only
what's affected: re-score Stage 1–3 from stored text (no re-download), and re-embed when the model
changes.

---

## 8. Languages

- **English** judgments first (most SC and HC judgments).
- **Hindi:**
  - SC `regional/` PDFs;
  - High Courts that publish in Hindi (to be identified from §3.1, e.g. Allahabad, Madhya Pradesh,
    Rajasthan, Patna, Chhattisgarh, Jharkhand, Himachal, Uttarakhand);
  - OCR with `hin` where scanned;
  - glossary Hindi variants for Stage 2.
- **Embeddings:** the current `bge-small-en-v1.5` is English-only. Hindi judgments need a multilingual
  model (e.g. a multilingual e5 variant, ideally 384-d to keep the vector size). Decide by measuring
  retrieval recall@10 on Hindi questions (§10) before switching, because switching means re-embedding everything.

---

## 9. Rollout order

| Phase | Scope | Why |
|---|---|---|
| P0 | Fix the SC language bug; add `--dry-run`; Stage 1 + 2 on SC **2015–2026** | Small, high-value precedents; validates the filter |
| P1 | SC all years (1950–2026) | Complete SC coverage (~2–4k property judgments) |
| P2 | HC: **Bombay (27_1)** and the other courts with `case_details` (`2_5`, `9_13`, `23_23`), 2018–2026 | Precise act-based filtering; Bombay fits the Pune demo scenario |
| P3 | Hindi-belt HCs (e.g. Allahabad, MP, Rajasthan), with Hindi OCR and multilingual embeddings | Hindi documents are in scope |
| P4 | Remaining HCs and older years | Full coverage, subject to hosted DB capacity |
| P5 | Scheduled updates, corpus stats, citation graph | Keep it current and trustworthy |

## 10. Evaluation

| What | How | Target to report |
|---|---|---|
| **Filter precision and recall** | Hand-label a random sample of **300 judgments** (stratified: SC/HC, accepted/rejected/borderline); two labellers on 50 for agreement | precision, recall, F1 with 95% CI; confusion by tag |
| **Tag accuracy** | Same sample, multi-label | per-tag F1 |
| **Retrieval quality** | ~30 property questions (English + Hindi + Hinglish) with the judgments that should be found | recall@10, MRR |
| **Freshness** | Days between a judgment appearing in the bucket and in our corpus | median, max |
| **Cost** | LLM calls per 1,000 ingested; seconds per judgment | per run |

The deterministic stages get unit tests with fixed sample rows (including the known false
positives: Limitation s.5, NDPS "possession"), as done for the rest of the project.

## 11. Implementation steps

1. Fix the SC language bug (`ingest/supreme_court.py:53`) and add a test with a 2026-style row.
2. A shared `ingest/sources.py`: list partitions, read metadata (SC and HC), compute object keys,
   read ETags and `data.index.json`.
3. `ingest/filters.py`: Stage 1 (metadata) and Stage 2 (full text) scoring with reasons, plus the topic
   taxonomy (§1), as pure functions with unit tests.
4. Stage 3 seed set (`ingest/seeds.json`) and the similarity scorer; Stage 4 LLM check with a budget.
5. Alembic migration: the new columns and the `ingestion_items`, `ingestion_runs` and `source_partitions` tables.
6. `ingest/run.py` (`--source sc|hc --years --courts --dry-run --limit`) and `ingest/update.py` (incremental).
7. Lazy summaries in search (`app/services/search.py`: fall back to paragraphs; summarise on first use).
8. `GET /corpus/stats` and "Judgments updated on" in the app; filters by court, year and tag in search.
9. Scheduling: a `launchd` plist and a GitHub Actions workflow template.
10. Evaluation: the labelling sheet, the scorecard section for filter P/R/F1, and the retrieval eval.

## 12. Risks

| Risk | Mitigation |
|---|---|
| The filter misses property cases with unusual wording | Recall measured on a labelled sample; reasons stored; rules re-run without re-download |
| False positives (NDPS "possession", Limitation s.5) | Exclusion rules, Stage 3 negative seeds, measured precision |
| HC volume overwhelms a laptop DB | Phased rollout; hosted Postgres for P4; per-run limits |
| Dataset layout changes | Source adapters isolated in `ingest/sources.py`; a run fails loudly on unknown schemas |
| Dataset metadata is wrong (`pdf_exists`, `available_languages`) | Check the PDF object itself; never trust flags |
| Free-tier LLM limits | No LLM at ingestion except a capped Stage 4; lazy summaries |
| Hindi retrieval is weak with English embeddings | Measure first; switch to a multilingual model only with evidence |
| Overruled precedents shown as good law | Phase-2 citation graph; show appeal links |


## 13. Implementation (2026-11-01)

### One command

```bash
cd backend
docker compose up -d                          # from the repo root, once: Postgres + pgvector
uv run python -m ingest                       # everything in scope, incremental; safe to re-run or Ctrl-C
uv run python -m ingest --dry-run --limit 50  # see what would be ingested, no database needed
uv run python -m ingest --stats               # what the corpus holds
```

Useful options: `--source sc|hc`, `--years 2015-2026`, `--hc-years 2024`, `--courts 27_1`, `--limit N`,
`--full` (re-scan unchanged partitions), `--reprocess` (re-judge after changing rules),
`--llm-budget N`, `--workers N`, `--sample-csv decisions.csv` (for labelling).

Default scope: SC all years; HC Bombay `27_1` plus `2_5`, `9_13`, `23_23`, 2018–now.

### What was built

| Plan item | Where | Notes |
|---|---|---|
| Sources (SC, HC, case details, ETags) | `ingest/sources.py` | Plain HTTPS, paginated listing, disk cache; ignores the unreliable `available_languages` / `pdf_exists` flags |
| Stage 1 + 2 filters, taxonomy, exclusions | `ingest/filters.py` | Pure functions with reasons; known false positives are unit-tested |
| Stage 3 seeds + similarity | `ingest/semantic.py`, `ingest/seeds.json` | 16 positive / 12 negative **hand-written descriptions** rather than real judgments (easy to curate; replace once a labelled sample exists) |
| Stage 4 LLM check | `ingest/semantic.py` | Only for still-borderline cases; budget 50/run if an API key is set, else 0 |
| Pipeline: incremental, idempotent, retries | `ingest/pipeline.py` | ETag watermark per partition; decided items never re-downloaded; failures retried up to 3 times; Ctrl-C safe |
| Data model | `app/models.py`, `app/db.py` | New judgment columns + `ingestion_items`, `ingestion_runs`, `source_partitions`. **Deviation:** kept additive `ADD COLUMN IF NOT EXISTS` instead of Alembic (no new dependency yet) |
| No LLM at ingestion; lazy summaries | `app/api/judgments.py`, `app/services/search.py` | Summary written on first open; search uses the headnote meanwhile |
| Corpus stats | `GET /corpus/stats`, `--stats` | |
| Scheduling | `ingest/schedule/` | launchd plist and GitHub Actions template (not active until copied) |
| Filter evaluation | `ingest/evaluate.py` | Precision/recall with 95% CIs from a hand-labelled `--sample-csv` |
| Old SC loader bug | `ingest/supreme_court.py` | Language-flag filter removed |

### Real-data findings that changed the design (dry runs on live data)

1. **SC metadata has no headnote before 2024** (0% for every year sampled from 1955 to 2022; 21% in
   2024). Stage 1 on titles alone rejected almost everything. → SC records without a headnote go to
   full-text judging, so most SC PDFs are downloaded once (several hours for all years; resumable).
2. Stage 1 was too strict: 8 clearly in-scope SC 2024 cases were missed (land ceiling, consolidation,
   allotment, gift, "the present acquisition"). → Weak "property noun" and second-appeal signals; Stage 1
   now favours recall. 7 of the 8 were then accepted.
3. False positives found and fixed: "*Societies* Registration Act" counted as the Registration Act;
   semantic accepts on thin margins (0.65 vs 0.62); money-laundering and SEBI cases kept by the
   tie-break. → Statute regex fixed, margin 0.05, semantic accept needs a full-text score ≥ 5.5,
   exclusions added, and the tie-break never keeps excluded cases.
4. The HC dataset includes short procedural orders (Lok Adalat sittings, one-paragraph orders); these
   score ~0 and are rejected, which is intended.
5. Only a fraction of HC rows have case details with acts (50 of 1,466 Goa 2025 orders), so HC filtering
   relies mostly on case-type codes and full text.

### Dry-run results (not yet hand-labelled)

| Partition | Records | Downloaded | Accepted | Notes |
|---|---|---|---|---|
| SC 2024 | 782 | 651 | **154 (19.7%)** | Topics: title 62, land records 55, possession 54, sale 37, tenancy 32, acquisition 30… |
| HC Bombay at Goa 2025 | 1,466 | 109 | **16 (1.1%)** | Mostly second appeals (SA) and appeals from orders (AO) |

A spot-check of 30 accepted SC titles found about 4–6 doubtful ones, which led to fix 3 above. **Filter
precision and recall are not yet measured**: label a `--sample-csv` and run `python -m ingest.evaluate`.
Postgres storage could not be run on the development machine (no database there); the DDL was
validated and the full pipeline was tested with an in-memory store.
