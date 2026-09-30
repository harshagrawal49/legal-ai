# Nyaya: AI Legal Case Research Assistant (India)

An Android app where users describe a legal problem in plain language. The app turns it into a
structured fact sheet, finds similar Indian court judgments, explains how they relate, and lets the
user ask follow-up questions. It is a research aid, not legal advice.

```
android/   Kotlin + Jetpack Compose app
backend/   Python FastAPI service, LLM via any OpenAI-compatible API (default: Gemini free tier), Postgres + pgvector
  app/         API routes, services (intake, search, advisor), LLM prompts & schemas
  ingest/      pipeline that loads Supreme Court judgments into the database
  tests/
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
4. **Ingestion** (`ingest/supreme_court.py`): reads the public
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
uv run pytest
```

**Android:** open `android/` in Android Studio and run it on an emulator. The debug build talks to
`http://10.0.2.2:8000/`, which is your machine as seen from the emulator. From the command line,
run `cd android && ./gradlew assembleDebug`.

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

## Status

Done (Phases 0–3 of the plan): project scaffold, ingestion pipeline, intake, hybrid search with
LLM analysis, streaming advisor chat with citation checks, and Android screens for all of these.

Next:
- **Auth**: Supabase Auth; replace the `X-User-Id` header in `app/api/deps.py` and `Api.kt`.
- **Compare** two judgments side by side, and the **position assessment** screen.
- **Document drafts**: templates (legal notice, consumer complaint, …) filled from the fact sheet, with DOCX/PDF export.
- **Data**: High Court judgments, OCR for scanned PDFs, the Batches API for bulk summarisation,
  and a legal-domain embedding model.
- **Evals**: a golden set of case descriptions → expected judgments (recall@10), plus lawyer review.
- Alembic migrations once the schema settles, and deployment (Render/Fly + Supabase).
