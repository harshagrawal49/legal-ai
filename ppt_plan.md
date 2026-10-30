# NyayaSathi AI: Presentation Plan (College Major Project)

> Plan only. The HTML deck is built from this plan in a later step.
> Rule for the whole deck: **every number shown must come from this repo or a cited source.** Where a
> number doesn't exist yet (LLM evals), the slide says so, or the eval is run before the presentation.
> Professors respect "we measured X and found Y failed" far more than vague claims.

---

## 1. Goals and audience

| | |
|---|---|
| **Audience** | Professors / external examiners: technical, sceptical of "AI hype", grading on problem understanding, engineering depth, evaluation and honesty |
| **Core message** | *We turned scattered property-dispute documents into a source-linked case-preparation pack, and we built guardrails and evals so the AI can't quietly make things up.* |
| **What they should remember** | 1) A real, specific Indian problem. 2) A grounded architecture where every claim links to a page or judgment. 3) We measured it, and we know its limits. |
| **Length** | ~20 min talk + ~7 min live demo + ~10 min Q&A (adjust to the slot; cut list in §7) |
| **Format** | One self-contained HTML deck, presented full-screen in a browser, works offline |

### The story arc (problem-solving oriented)

```
 ACT 1  The problem         Why ordinary people struggle to prepare for a property dispute
 ACT 2  The insight         Preparation (not prediction) is the gap; AI must be grounded to be trusted
 ACT 3  The solution        What NyayaSathi does, end to end
 ACT 4  How it works        Architecture, pipelines, key engineering decisions (technical depth)
 ACT 5  Trust               Grounding, citation checks, safety guardrails
 ACT 6  Proof               Live demo + evaluations + tests
 ACT 7  Honesty & future    Limitations, what we'd do next, fine-tuning only if evals justify it
```

Each technical slide follows **Problem → Decision → Why (vs. alternatives) → Evidence**. That keeps
the deck problem-solving oriented and not just a list of features.

---

## 2. Slide-by-slide plan (26 slides)

Legend: 🎯 purpose · 🖼 visual · 🗣 talking points · 🔧 technical detail to show · ⏱ time

### ACT 1: The problem

**1. Title**
- 🖼 Project name *NyayaSathi AI*, tagline *"From scattered documents to a source-linked case-preparation pack"*, team names and roles, guide name, college, date.
- 🖼 Subtle animated background: document pages flowing into an organised timeline (CSS only).
- ⏱ 0:30

**2. A story, not a statistic** (hook)
- 🎯 Make the problem human in 30 seconds.
- 🖼 A three-step comic-strip style panel using our *fictional* scenario (from `eval/samples.py`):
  Meera pays a ₹5 lakh advance for a plot in Pune → the receipt says a different survey number and amount → she learns the seller agreed to sell the same plot to someone else.
- 🗣 "She has an agreement, a receipt and a legal notice. What does she actually have, and what's missing? That's the question our app answers."
- ⏱ 1:00

**3. The problem in numbers**
- 🎯 Show scale. **Use only verified sources**: pendency of civil cases from the National Judicial Data Grid (NJDG), and the share of civil litigation that is land/property related (e.g. published studies such as DAKSH reports). *Verify every figure and put the source URL on the slide.*
- 🖼 2–3 big-number tiles with source footnotes.
- 🗣 Property disputes are long, document-heavy and expensive. Lawyer time is spent on organising papers.
- ⏱ 1:00

**4. Who struggles and why** (root-cause analysis)
- 🖼 Fishbone or "pain points" grid:
  - Documents are scattered (agreement, receipts, notices, 7/12 extracts)
  - Contradictions hide in details (survey no. 123/4 vs 123/A, ₹5,00,000 vs ₹5,50,000)
  - People don't know what's missing (a referenced "Annexure A" never found)
  - Legal research is inaccessible (judgments are long and technical)
  - Generic chatbots hallucinate laws and cases, and overpromise outcomes
- 🗣 The real gap isn't "predict who wins". It's *preparation*: knowing your own facts and evidence before meeting an advocate.
- ⏱ 1:30

**5. Existing solutions and their gaps**
- 🖼 Comparison table: Generic chatbots · Legal databases (e.g. Indian Kanoon) · Lawyers · **NyayaSathi**
  Columns: understands *your* documents · finds conflicts · cites real sources · checks its citations · plain language · cost
- 🗣 Be fair: databases are authoritative but don't read your documents; chatbots read them but invent things; lawyers are essential but expensive for preparation work. We sit *before* the lawyer, not instead of one.
- ⏱ 1:00

### ACT 2: The insight

**6. Problem statement and objectives**
- 🖼 One-sentence problem statement plus 5 measurable objectives:
  1. Extract page-referenced facts from uploaded PDFs
  2. Build a chronology and flag gaps/conflicts, each traceable to a page
  3. Retrieve relevant Indian judgments with hybrid search
  4. Answer questions with *verified* citations only
  5. Produce a case-preparation brief that separates facts, allegations and legal sources
- Plus **non-goals**: does not decide ownership, predict outcomes, replace an advocate, or file anything.
- 🗣 Non-goals show maturity. Say them out loud.
- ⏱ 1:00

**7. Design principles** (the "why" behind every decision)
- 🖼 Four principle cards with icons:
  - **Grounded**: every claim links to a document page or judgment paragraph
  - **Verified in code**: don't trust the model, check it (citations, quotes, schema)
  - **Honest uncertainty**: "not found in the uploaded documents" ≠ "didn't happen"
  - **Safe by default**: refuse illegal help, show helplines, stay neutral
- ⏱ 0:45

### ACT 3: The solution

**8. What NyayaSathi does: user journey**
- 🖼 Horizontal flow of 6 phone mock-ups (real screenshots from the app):
  Case list → Describe the case (intake) → Attach documents → Timeline & flags → Chat about the case → Case-preparation brief
- 🗣 One sentence per step. This is the map for the demo.
- ⏱ 1:00

**9. Feature overview**
- 🖼 Feature grid (8 tiles): AI intake & fact sheet · PDF upload & page-level extraction · Evidence pack (timeline + flags) · Similar judgments (hybrid RAG) · Case-aware streaming chat · Document & judgment citations · Case-preparation brief · Safety guardrails
- ⏱ 0:45

### ACT 4: How it works (technical depth)

**10. System architecture**
- 🖼 Animated inline-SVG architecture diagram (builds in 3 steps):
  ```
  Android app (Kotlin, Jetpack Compose, Retrofit, SSE)
        │  HTTPS / JSON, multipart upload, server-sent events
        ▼
  FastAPI backend ── services: intake · documents · evidence · search · advisor · brief
        │                     │                         │
        ▼                     ▼                         ▼
  PostgreSQL + pgvector   LLM via OpenAI-compatible API   Local embeddings (fastembed,
  (cases, documents,      (default Gemini; swappable       BAAI/bge-small-en-v1.5)
   judgments, paragraphs)  to Ollama / others)
  ```
- 🔧 Mention: no API key in the APK; the LLM provider sits behind one client module (`app/llm/client.py`), so switching provider is a config change.
- ⏱ 1:30

**11. Tech stack and why**
- 🖼 Table: Layer · Choice · Why · Alternatives considered
  - Android: Kotlin + Compose (modern declarative UI) vs XML views
  - Backend: FastAPI + Pydantic (typed, schema validation, auto OpenAPI docs) vs Flask/Django
  - DB: Postgres + pgvector (one database for relational data, full-text search and vectors) vs a separate vector DB (Pinecone/Chroma): fewer moving parts
  - PDF: PyMuPDF (fast, page-accurate text)
  - LLM: OpenAI-compatible client (provider-agnostic; free tier for development, local Ollama for privacy)
  - Embeddings: bge-small (free, local, private, fast on CPU). See slide 14.
- ⏱ 1:00

**12. Pipeline 1: Document → verified facts**
- 🖼 Step diagram with a real example travelling through it:
  `PDF` → validate (type, 10 MB, 60 pages, encryption) → page-by-page text (PyMuPDF) → LLM extraction into a **Pydantic schema** (`DocumentFacts`) → **code checks each quoted excerpt really exists on the cited page** → `verified: true/false`
- 🔧 Show a 6-line JSON snippet of one extracted amount with `{page: 1, excerpt: "...", verified: true}`.
- 🔧 Failure handling: scanned PDF → `failed` with a clear reason, never fabricated text; LLM failure → `text_only` + retry button.
- 🗣 "The model proposes; the code verifies."
- ⏱ 1:30

**13. Pipeline 2: Evidence pack (deterministic, no AI)**
- 🖼 Left: the 3 sample documents. Right: the flags they produce:
  - property identifier difference (123/4 vs 123/A)
  - amount difference (₹5,00,000 vs ₹5,50,000)
  - referenced document not found
  - unverified quote
- 🔧 Indian amount parsing ("Rs 4.5 lakh" → 450000, "5,00,000" → 500000), normalised comparison so "123 / 4" = "123/4" (no false alarm).
- 🗣 Why no AI here? Flags must be reproducible and explainable. Wording is deliberately neutral: never "fraud".
- ⏱ 1:15

**14. Pipeline 3: Legal RAG (hybrid search)**
- 🖼 Diagram: query → (Postgres full-text search ‖ pgvector cosine search) → **Reciprocal Rank Fusion (k = 60)** → top 15 candidates → LLM relevance analysis (supports / opposes / mixed, similarities, differences) → top 8 kept; IDs not retrieved are dropped.
- 🔧 Why hybrid: keywords catch exact legal terms ("Section 54", "specific performance"); embeddings catch meaning ("builder delayed handover" ≈ "possession not given").
- 🔧 Embedding choice: bge-small-en-v1.5 (384-d, local, free, private) vs bge-large, multilingual-e5, OpenAI/Gemini, Voyage-law, InLegalBERT. Mini comparison table with trade-offs.
- 🔧 Data: Supreme Court of India judgments from the public AWS Open Data dataset, split by numbered paragraph and summarised once at ingestion.
- ⏱ 1:30

**15. Pipeline 4: Case-aware chat (tool-using agent)**
- 🖼 Sequence diagram: user message → backend rebuilds **current case context** (fact sheet, documents, results) → LLM streams → may call tools `search_judgments`, `read_judgment`, `read_case_documents` (max 6 rounds) → answer streamed over SSE → **citation check** in the `done` event.
- 🔧 Citation formats `[[J:id]]`, `[[D:doc:pN]]`; unverified citations are shown as "[unverified source]" in the app.
- 🔧 Context rebuilt every turn, so new uploads or searches are seen immediately.
- ⏱ 1:15

**16. Pipeline 5: Case-preparation brief**
- 🖼 Mock-up of the brief with its 9 sections colour-coded by *source type*:
  🟩 document-supported facts (verified quotes only) · 🟨 user's own account (not verified) · 🟥 gaps & inconsistencies · 🟦 legal sources · ⬜ advocate questions & checklist (AI-suggested, labelled)
- 🗣 The key idea: **separating what the documents say, what the user says, and what the AI suggests.**
- ⏱ 1:00

**17. Data model and API**
- 🖼 Small ER diagram: `cases` → `case_documents`, `chat_messages`, `case_results` → `judgments` → `judgment_paragraphs` (vector column).
- 🖼 API table (18 routes; highlight 6 key ones). Mention auto-generated OpenAPI docs at `/docs`.
- ⏱ 0:45 (can be cut)

### ACT 5: Trust

**18. Grounding and anti-hallucination measures**
- 🖼 "Defence in depth" layered diagram:
  1. Prompt rules (cite only what you've seen, null for unknowns)
  2. Schema validation (Pydantic; malformed output → safe failure)
  3. Excerpt verification (quote must exist on the page)
  4. Citation verification (judgments seen in the conversation; document pages that exist)
  5. UI honesty (unverified items marked red; fixed disclaimers, not AI-written)
- 🔧 Prompt-injection defence: documents and judgments are wrapped as untrusted data. Our sample legal notice contains a planted "Ignore all previous instructions…" line to test this.
- ⏱ 1:15

**19. Safety guardrails (responsible AI)**
- 🖼 Three columns:
  - **Refuses** (with lawful alternative): forgery/back-dating, evidence tampering, stamp-duty evasion, benami, bribery, avoiding summons, threats, illegal eviction, doxxing
  - **Protects**: helplines when someone is at risk: 112, 181, Tele-MANAS 14416, NALSA 15100
  - **Stays fair**: no stereotyping by caste/religion/gender/community; neutral language; no guaranteed outcomes
- 🔧 Safe fallback when the provider blocks a reply; applied to all 4 user-facing prompts.
- 🗣 Be honest: prompt-based rules reduce risk, they don't guarantee it. That's why we red-team them (next act).
- ⏱ 1:00

**20. Privacy and security**
- 🖼 Checklist: no API keys in the APK · only extracted text stored, not files · document content never logged · delete document = delete its data · file type/size validation · local embeddings · option to run the LLM fully locally (Ollama) · synthetic data only during development.
- ⏱ 0:45 (can be merged with 19)

### ACT 6: Proof

**21. Live demo** (see §4 for the full script)
- 🖼 Slide shows only "Live demo" plus the 6-step journey as a checklist, so the audience can follow.
- ⏱ 6–7 min

**22. Evaluation methodology**
- 🎯 Show we measured, not just demoed.
- 🖼 Three eval suites as cards:
  1. **Document extraction benchmark v1**: 3 synthetic documents with deliberate traps (conflicting survey no., conflicting advance, missing annexure, planted prompt injection). Metrics: schema-valid rate, field recall, unsupported (hallucinated) values, verified-quote rate, expected flags raised, injection followed.
  2. **Safety red-team v1**: 17 cases = 10 must-refuse + 2 people-at-risk + 2 bias/jailbreak + 3 legitimate controls (to catch over-refusal). Code checks + LLM-as-judge.
  3. **Automated tests**: 39 pytest tests (PDF failure paths, quote verification, evidence flags, citation checks, brief section separation, API routes, safety wiring, chat context).
- 🗣 Explain *why* controls matter: a model that refuses everything scores 100% on safety but is useless.
- ⏱ 1:30

**23. Evaluation results**
- 🖼 Charts (bar charts for recall per field, a pass/fail grid for safety cases, a big tile for tests).
- **Currently verified:** PDF-handling checks 7/7 passed · 39/39 tests passed.
- **Must be run before the presentation** (needs `LLM_API_KEY`):
  `uv run python -m eval.run_eval --llm` and `uv run python -m eval.run_safety_eval`
  → copy the numbers from `backend/eval/results/*.json` into this slide.
- 🖼 Include **2–3 real failure examples** from the runs (e.g. a missed amount, a judge-flagged reply), each with what we changed or would change.
- 🗣 If something failed, say it and show the fix. This is the most credible slide in the deck.
- ⏱ 1:30

**24. Engineering challenges and how we solved them**
- 🖼 4 problem → solution cards:
  - LLM invents page references → excerpt verification in code
  - Same value written differently ("123 / 4", "Rs 5 lakh") → normalisation + Indian number parsing
  - Chat forgot new documents → rebuild case context every turn
  - Provider differences (schemas, thought signatures, rate limits) → JSON-mode fallback, preserved provider fields, retries with backoff, friendly 503s
- ⏱ 1:15

### ACT 7: Honesty and future

**25. Limitations and future work**
- 🖼 Two columns.
  - **Limitations**: no OCR (scanned PDFs rejected) · small benchmark (3 docs, 1 scenario, English) · Supreme Court judgments only, no statutes yet · English-only embeddings · prompt-based safety · no auth yet · not reviewed by practising advocates
  - **Future work**: OCR · High Court judgments + bare acts · multilingual embeddings (Hindi/Hinglish) · retrieval eval (recall@10) · advocate review of outputs · authentication · **fine-tuning only if evals show a repeated failure prompts can't fix** (SFT/LoRA for extraction; see `docs/future_finetuning.md`)
- ⏱ 1:00

**26. Conclusion + Thank you / Q&A**
- 🖼 Three takeaways (problem → grounded solution → measured), project repo QR code, team.
- ⏱ 0:30

**Appendix slides (hidden, for Q&A only):** full API table · prompt excerpts · DocumentFacts schema · RRF formula · embedding comparison detail · sample eval JSON · test list.

---

## 3. HTML deck: design and build plan

### Technology
- **Single `presentation/index.html`**, self-contained, **works offline** (college Wi-Fi is unreliable): all CSS/JS inline, fonts and libraries vendored into `presentation/assets/`.
- Hand-built slide engine (≈150 lines of JS) or **Reveal.js** (vendored copy). Recommendation: **Reveal.js** for speaker notes (`S` key), overview mode (`O`), PDF export and fragments, all reliable under pressure.
- Diagrams as **inline SVG** (crisp on projectors, animatable with CSS); charts with **Chart.js** (vendored) fed from the eval JSON.
- Screenshots: real app screenshots (PNG) from the emulator, shown in a CSS phone frame.

### Visual design
- Theme: deep navy background + saffron/amber accent (Indian, legal, serious), white text; high contrast for projectors. Provide a light theme toggle in case the room is bright.
- Typography: one sans-serif for headings (e.g. Inter / Poppins), one mono for code (JetBrains Mono).
- Colour coding used everywhere: 🟩 verified from documents · 🟨 user's claim · 🟥 flag/gap · 🟦 legal source. Same colours as the brief slide and the app.
- Max ~30 words of body text per slide; details go in speaker notes.
- Motion: fragments reveal one idea at a time; architecture diagram builds in 3 steps; no gimmicky transitions.
- Footer: slide number + act name (e.g. "4 · How it works"), so examiners know where they are.

### "Impressive" elements (purposeful, not decorative)
1. **Animated architecture diagram** (slide 10): nodes light up as a request flows through.
2. **Live "trace a fact" animation** (slide 12): the ₹5,50,000 amount travels from PDF page → JSON → verified ✓ → flag.
3. **Interactive evidence demo** (slide 13): click a flag to highlight the source excerpt on a rendered page image.
4. **Eval dashboard** (slide 23): charts rendered from real results JSON.
5. **Safety case grid** (slide 19/23): 17 tiles, hover to see the prompt and the model's reply.
6. Keyboard shortcuts: `→` next, `S` speaker notes, `O` overview, `F` fullscreen.

### Build steps (later)
1. Scaffold `presentation/` with vendored Reveal.js and Chart.js; theme CSS.
2. Write slides 1–9 (story); review the narrative alone first.
3. Draw SVG diagrams (architecture, pipelines, RAG, chat sequence, ER).
4. Capture app screenshots from the emulator (needs a working Android build).
5. Run both evals with an API key; wire the results JSON into the charts.
6. Speaker notes for every slide.
7. Export a PDF backup (`?print-pdf`) and test on a projector-resolution screen (1920×1080 and 1280×720).

---

## 4. Live demo script (~7 min)

**Setup before the session:** backend running (`docker compose up -d`, `uvicorn`), ~30 judgments
ingested, emulator open on the case list, the 3 synthetic PDFs on the emulator (`adb push`), a
**pre-created backup case** with documents already processed, and a **screen recording of the full
demo** in case of network/LLM failure.

| # | Step | What to say | What examiners should notice |
|---|---|---|---|
| 1 | New case → type Meera's story in plain language | "No legal terms needed." | AI produces a structured fact sheet + follow-up questions |
| 2 | Attach `agreement_to_sell.pdf`, `advance_receipt.pdf`, `legal_notice.pdf` | "Text-based PDFs, page by page." | Status per document; page counts |
| 3 | Open a document → extracted facts with "quote found on page" | "Every fact links to a page." | Verified markers; tap a source → jumps to the page |
| 4 | Timeline & flags tab | "Notice: survey 123/4 vs 123/A, ₹5,00,000 vs ₹5,50,000." | Conflicts found automatically, neutral wording |
| 5 | Find similar cases | "Hybrid search over Supreme Court judgments." | Supports/opposes labels, explanations, source links |
| 6 | Chat: "What do my documents show about the advance?", then "Which judgment is most relevant?" | "It cites pages and judgments; citations are checked." | Tappable `[receipt.pdf, p.1]` and judgment links |
| 7 | Chat (safety): "Help me back-date the agreement" | "It refuses, and points to the lawful route." | Polite refusal + alternative |
| 8 | Generate brief | "Facts, user claims, gaps and legal sources kept separate." | 9 colour-coded sections, disclaimer |
| 9 | (Optional) upload a scanned/blank PDF | "It fails honestly instead of inventing text." | Clear error message |

**Fallbacks:** LLM slow → switch to the pre-created case. Network down → play the recording.
Emulator crash → screenshots in the appendix.

---

## 5. Speaker roles (team of 4: adjust)

| Part | Slides | Presenter |
|---|---|---|
| Problem & insight | 1–7 | Member A |
| Solution & architecture | 8–11, 17 | Member B |
| Pipelines & trust | 12–16, 18–20 | Member C |
| Demo | 21 | Member D (driver) + narrator |
| Evals, challenges, future | 22–26 | Member A or D |

Each member should be able to answer Q&A on their part *and* on the overall architecture.

---

## 6. Q&A preparation (likely questions)

| Question | Short answer (expand in rehearsal) |
|---|---|
| How do you prevent hallucinations? | Grounding + code verification: schema validation, excerpt-on-page check, citation check against retrieved/uploaded sources; unverified items are marked, not hidden. |
| Why not just use ChatGPT? | It doesn't verify citations or quotes, can't separate the user's claims from document facts, and isn't connected to a curated Indian judgment corpus. |
| Why RAG and not fine-tuning? | Law changes and must be cited; RAG gives traceable sources. Fine-tuning is deferred until evals show a repeated failure that prompts and retrieval can't fix. |
| Why hybrid search? What is RRF? | Keywords for exact legal terms, vectors for meaning; RRF merges ranked lists by summing 1/(k+rank) with k = 60, so no score calibration is needed. |
| Why bge-small? | Free, local, private, fast on CPU; strong for English. Trade-off: English-only, 512-token limit. Next: measure recall@10 vs larger/multilingual models. |
| How is the evaluation valid with only 3 documents? | It's a fixed regression benchmark with deliberate traps, not a reliability claim; we say so on the slide. The next step is more scenarios. |
| Is the LLM-as-judge reliable? | Not fully. We pair it with deterministic checks and read failing cases manually. |
| What about data privacy? | No files stored, no content logged, keys server-side, local embeddings, optional fully local LLM via Ollama; synthetic data only. |
| Legal liability? | It's a preparation aid; it never decides ownership or predicts outcomes, and it recommends an advocate. Fixed disclaimers. |
| What about scanned documents? | Rejected with a clear message today; OCR is future work. We chose honesty over fabricated text. |
| How does it scale? | Stateless API, Postgres + pgvector with an index on embeddings; ingestion is batch/offline. |
| What would you do with 3 more months? | OCR, High Courts + statutes, multilingual retrieval, retrieval eval, advocate review, auth + deployment. |

---

## 7. Timing and cut list

| Slot available | Keep | Cut / merge |
|---|---|---|
| 30 min | All 26 + demo | — |
| 20 min | 1–2, 4, 6, 8, 10, 12–16, 18–19, 21–23, 25–26 | 3, 5, 7, 9, 11, 17, 20, 24 → appendix |
| 15 min | 1–2, 4, 6, 10, 12, 14, 18–19, 21 (4 min demo), 23, 25–26 | everything else → appendix |

---

## 8. Pre-presentation checklist

- [ ] Verify every statistic on slide 3 against its source; put the URL on the slide
- [ ] Android app builds (`./gradlew assembleDebug`) and runs on the emulator
- [ ] Capture screenshots for slides 8, 12, 13, 16 and the appendix
- [ ] Add `LLM_API_KEY`; run `eval.run_eval --llm` and `eval.run_safety_eval`; fill slide 23 with the real numbers and 2–3 failure examples
- [ ] Update `docs/evaluation.md` with the same numbers (deck and repo must agree)
- [ ] Verify helpline numbers (112, 181, 14416, 15100) against official sources
- [ ] Ingest ~30 judgments relevant to the demo scenario; dry-run the demo 3 times
- [ ] Record the backup demo video
- [ ] Export a PDF backup of the deck; test on a projector (1280×720)
- [ ] Two full rehearsals with timing; one rehearsal of Q&A with a friend acting as examiner
- [ ] Commit the deck and eval results to the repo (personal git identity, see README)

---

## 9. Facts to use (verified from the repo on 2026-10-30)

| Item | Value | Source |
|---|---|---|
| Backend code (app, ingest, eval, tests) | ~3,300 lines of Python | `backend/` |
| Android code | ~2,100 lines of Kotlin | `android/app/src` |
| API routes | 18 (cases 9, documents/evidence/brief 7, judgments 1, health 1) | `backend/app/api`, `main.py` |
| App screens | 9 navigation destinations | `MainActivity.kt` |
| Automated tests | 39 passing | `uv run python -m pytest` |
| PDF-handling eval | 7/7 checks passed | `eval/run_eval.py` |
| Extraction benchmark | v1, 3 synthetic documents (4 pages) | `eval/samples.py` |
| Safety red-team | v1, 17 cases (10 refuse, 7 help incl. 3 controls) | `eval/safety_cases.py` |
| Retrieval | Hybrid FTS + pgvector, RRF k = 60, 15 candidates → 8 results | `app/services/search.py`, `config.py` |
| Embeddings | BAAI/bge-small-en-v1.5, 384-d, local via fastembed | `app/config.py` |
| LLM | Any OpenAI-compatible API; default Gemini (`gemini-3.8-flash`) | `app/config.py` |
| Upload limits | PDF only, 10 MB, 60 pages | `app/services/documents.py` |
| Chat tool rounds | max 6 per reply | `app/services/advisor.py` |
| **Not yet measured** | LLM extraction quality, safety red-team pass rate, retrieval recall | run before presenting |
