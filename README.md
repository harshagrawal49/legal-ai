# Nyaya: AI Legal Case Research Assistant (India)

An Android app where users describe a legal problem in plain language and upload their documents
(agreements to sell, receipts, notices). The app turns them into a structured fact sheet and a
source-linked evidence pack, finds similar Indian court judgments, explains how they relate, lets the
user ask follow-up questions, and drafts a case-preparation brief to take to an advocate. It is a
preparation and research aid, not legal advice. It does not decide ownership, predict outcomes or
file anything.

```
android/   Kotlin + Jetpack Compose app
backend/   Python FastAPI service, LLM via any OpenAI-compatible API (default: Gemini free tier), Postgres + pgvector
  app/         API routes, services (intake, search, advisor, documents, evidence, brief), LLM prompts & schemas
  ingest/      pipeline that loads Supreme Court judgments into the database
  eval/        synthetic benchmark documents + baseline evaluation script
  tests/
docs/        evaluation baseline, future fine-tuning prerequisites
docker-compose.yml   local Postgres with pgvector
```

## How it works

1. **Intake** (`app/services/intake.py`): the LLM turns the description and any follow-up answers
   into a **fact sheet** (parties, timeline, amounts, issues, likely laws, search queries, missing
   info) and asks up to 4 clarifying questions.
2. **Search** (`app/services/search.py`): hybrid retrieval over judgment paragraphs (Postgres
   full-text + pgvector embeddings, merged with reciprocal rank fusion). The LLM then scores each
   candidate's relevance, labels it supports / opposes / mixed, and explains the similarities and
   differences. Only IDs that were actually retrieved are kept.
3. **Advisor chat** (`app/services/advisor.py`): a streaming conversation (server-sent events) in
   which the LLM can call `search_judgments` and `read_judgment`. Citations use the form
   `[[J:<id>]]`, and the backend reports any citation that never appeared in the conversation.
4. **Documents** (`app/services/documents.py`): an uploaded PDF is checked (type, 10 MB, 60 pages,
   encryption) and its text is extracted page by page with PyMuPDF. The LLM extracts candidate facts
   into a validated schema (`DocumentFacts`: parties, property identifiers, amounts, events, clauses,
   referenced documents, uncertainties), and each fact carries a page and a quoted excerpt. Code then
   checks that each excerpt really occurs on that page (`verified`). A PDF without usable text is
   stored as `failed` with the reason, and nothing is made up to fill the gap. Only the extracted
   text is kept, not the file.
5. **Evidence pack** (`app/services/evidence.py`): plain code, no LLM. It builds a chronology from
   the documents and flags differing property identifiers, amounts or dates, mentioned documents that
   weren't uploaded, extraction failures and unverified quotes. Every item links to a document page,
   and the wording never draws a conclusion such as fraud or ownership.
6. **Brief** (`app/services/brief.py`): a draft in separate sections. Document-supported facts
   (verified quotes only), the user's own unverified account, gaps, relevant judgments, advocate
   questions and a checklist. Only the last two come from the LLM, and if that call fails, fallbacks
   derived from the flags are used.
   The advisor chat can also read documents (`read_case_documents`) and cite pages as
   `[[D:<document_id>:p<N>]]`. These citations are checked against real pages.
7. **Ingestion** (`ingest/supreme_court.py`): reads the public
   [Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/)
   dataset, splits each judgment into its numbered paragraphs, and summarises it once with the
   bulk model. It then stores the paragraphs and summary with local embeddings.

## Run it locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Android Studio (or the Android SDK), and
a free Gemini API key from https://aistudio.google.com/apikey (or a local
[Ollama](https://ollama.com) install; see `backend/.env.example`).

```bash
# 1. Database
docker compose up -d

# 2. Backend
cd backend
cp .env.example .env          # add LLM_API_KEY
uv sync

# 3. Load some judgments (start small; each one costs one bulk-model call)
uv run python -m ingest.supreme_court --year 2023 --limit 30
uv run python -m ingest.supreme_court --year 2022 --limit 30 --match "developers" "buildwell" "infratech"

# 4. Start the API  (docs at http://localhost:8000/docs)
uv run uvicorn app.main:app --reload

# 5. Tests (no database or API key needed)
uv run pytest            # if the .venv was moved from another folder: uv run python -m pytest

# 6. Baseline evaluation on the synthetic benchmark (see docs/evaluation.md)
uv run python -m eval.run_eval          # deterministic checks
uv run python -m eval.run_eval --llm    # + LLM fact extraction (needs LLM_API_KEY)
uv run python -m eval.run_safety_eval   # safety red-team, 17 cases (needs LLM_API_KEY)
```

To try the document flow, generate the synthetic sample PDFs (fictional people and places) and upload
them in the app under **My documents**:

```bash
uv run python -c "from eval.samples import SAMPLES, make_pdf; [open(f'/tmp/{n}','wb').write(make_pdf(p)) for n,p in SAMPLES.items()]"
```

**Android:** open `android/` in Android Studio and run it on an emulator. The debug build talks to
`http://10.0.2.2:8000/`, which is your machine as seen from the emulator. From the command line,
run `cd android && ./gradlew assembleDebug`.

## Speed (Gemini free tier)

- **Two model tiers**: `MODEL_FAST` (flash-lite) for intake, document extraction and the brief;
  `MODEL_MAIN` (flash) for search analysis and chat.
- **Short thinking**: every call sends `reasoning_effort=low` (`LLM_REASONING_EFFORT`). It's dropped
  automatically if the provider rejects it.
- **No wasted calls**: if a model rejects JSON-schema output once, later calls go straight to JSON mode.
- **Fail fast**: 2 retries and a 90 s timeout instead of waiting minutes on rate limits; the app shows "busy, try again".
- **Uploads return at once**: page text is extracted during the upload; LLM fact extraction runs in
  the background (`processing`) while the app polls.
- **Smaller prompts**: search sends 8 candidates with 2 short paragraphs each (was 15 × 4); chat uses
  at most 3 tool rounds; the embedding model loads at startup.
- **Measure it**: every LLM call logs `llm <task> model=… <seconds>s in=<tokens> out=<tokens>` in the server log.

## Safety guardrails

- **Prompt rules** (`SAFETY_RULES` in `app/llm/prompts.py`, used by every prompt that talks to users):
  no help with illegal or harmful acts (forgery, evidence tampering, stamp-duty or tax evasion, benami
  deals, bribery, avoiding summons, threats, illegal eviction), with a lawful alternative offered
  instead. Safety resources when someone may be at risk (112, 181, Tele-MANAS 14416, NALSA 15100).
  Neutral, non-stereotyping language. No digging up third parties' personal data. No guaranteed outcomes.
- **Code checks**: citations must resolve to sources actually retrieved or uploaded; quotes must exist
  on the cited page; evidence flags never draw conclusions; disclaimers are fixed text; blocked or
  empty chat replies become a safe fallback message.
- **Tests**: `tests/test_safety.py` (wiring and scoring) and `eval/run_safety_eval.py` (red-team run
  against the real model).

These reduce risk but are not a guarantee. See `docs/evaluation.md` for limitations.

## LLM provider

All LLM calls go through `app/llm/client.py` using the `openai` Python SDK. Any OpenAI-compatible API
works by changing `LLM_BASE_URL`, `LLM_API_KEY` and the model names in `.env`:

| Provider | Cost | Notes |
|---|---|---|
| Google Gemini (default) | Free tier, with rate limits | On the free tier Google may use prompts to improve its products, so don't send real users' data. The paid tier doesn't. |
| Ollama (local) | Free | Nothing leaves your machine; needs a decent GPU / Apple Silicon for good quality |
| Groq, OpenRouter, … | Free tiers vary | Same code, different base URL |

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/cases` | New case from a description → fact sheet + questions |
| POST | `/cases/{id}/intake` | Answer questions / add details |
| PUT | `/cases/{id}/fact-sheet` | User edits the summary |
| POST | `/cases/{id}/search` | Find and explain similar judgments |
| GET | `/cases/{id}/results` | Saved results |
| GET/POST | `/cases/{id}/chat` | History / send a message (SSE stream) |
| GET | `/judgments/{id}` | Judgment summary and full paragraphs |
| POST | `/cases/{id}/documents` | Upload a PDF (multipart `file`) → page text + extracted facts (415 non-PDF, 413 too large) |
| GET | `/cases/{id}/documents` | Uploaded documents and their status |
| GET/DELETE | `/cases/{id}/documents/{doc_id}` | Page text and facts / delete document and its data |
| POST | `/cases/{id}/documents/{doc_id}/extract` | Retry fact extraction |
| GET | `/cases/{id}/evidence` | Chronology and gap/conflict flags with page sources |
| POST | `/cases/{id}/brief` | Draft case-preparation brief (returned for review only) |

## Status

Done: project scaffold, ingestion pipeline, intake, hybrid search with LLM analysis, streaming
advisor chat with citation checks, and the document workflow from `plan_claude.md`: PDF upload,
source-linked fact extraction, evidence pack, document-aware chat and case-preparation brief, plus
Android screens (My documents, document review, brief). Baseline evaluation is described in
`docs/evaluation.md`. Fine-tuning is deliberately deferred (`docs/future_finetuning.md`).

Known limitations: no OCR (scanned PDFs are rejected with a clear message); the benchmark is only 3
synthetic documents; the Android document screens have not yet been compiled on a machine with the
Android SDK; the legal corpus is Supreme Court judgments only, with no statutes.

Next:
- **Auth**: Supabase Auth; replace the `X-User-Id` header in `app/api/deps.py` and `Api.kt`.
- **Compare** two judgments side by side, and the **position assessment** screen.
- **Document drafts**: templates (legal notice, consumer complaint, …) filled from the fact sheet, with DOCX/PDF export.
- **Data**: High Court judgments, OCR for scanned PDFs, the Batches API for bulk summarisation,
  and a legal-domain embedding model.
- **Evals**: a golden set of case descriptions → expected judgments (recall@10), plus lawyer review.
- Alembic migrations once the schema settles, and deployment (Render/Fly + Supabase).
