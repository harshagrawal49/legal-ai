# Document understanding: plan

> Project topic: **Legal document analysis using NLP**. This plan makes every uploaded document
> *understood*, not just stored: classified, summarised in plain language, its legal terms explained,
> and linked into the conversation (citations, and `@` references to a document).
>
> Scope: documents in **English or Hindi**; chat in English, Hindi or **Hinglish** (Roman-script Hindi
> mixed with English).
>
> Status: **D1–D4 and D6 (deterministic parts) implemented; D5 (Android) written, not compiled.**
> Measured results: [`docs/eval_report.md`](docs/eval_report.md). LLM quality needs an API key.

---

## 1. Goals

| # | What the user gets | Done when |
|---|---|---|
| G1 | **Every attached document is in "My documents"**, wherever it was attached (new-case screen, documents screen, chat 📎), plus one place listing documents across all cases | A file attached in chat appears in the case's My documents and in "All my documents" |
| G2 | **Tap a document → understand it**: what it is, a plain-language summary, what each important part means, legal terms explained, what to check | Each statement links to a page; every number/date/name in the summary exists in the document (checked in code) |
| G3 | **Chat shows which documents an answer used**: a "Sources" list under every reply (document + page, judgments) | Sources come from verified citation markers; tapping one opens the page |
| G4 | **`@` references**: typing `@` in chat offers the case's documents; the answer then focuses on and cites the referenced document | `@receipt.pdf What amount does this show?` answers from that document with a `receipt.pdf p.1` source |
| G5 | **Measured quality**: faithfulness, term-explanation accuracy, readability, citation validity | Numbers with sample sizes and 95% intervals in `docs/eval_report.md` |

Non-goals: legal advice about the document ("is this valid?", "will I win?"), editing or signing
documents, translating whole documents.

---

## 2. Where this sits in the NLP pipeline (framing for the project)

| Stage | NLP task | Technique | Status |
|---|---|---|---|
| 1 | Text acquisition | PDF text extraction; **OCR** for scans/photos (Tesseract, eng+hin) | ✅ built |
| 2 | Language/script identification | Script ratio per page (Latin / Devanagari) → language tag | 🆕 this plan |
| 3 | Normalisation | Unicode NFC, Devanagari → ASCII digits, Indian number formats, OCR confusables (comma/dot) | ✅ built |
| 4 | Document classification | LLM label (agreement to sell, sale deed, receipt, notice, 7/12 extract…) **+ rule-based keyword classifier** as cross-check | partly (LLM only) → 🆕 rules |
| 5 | Information extraction (NER-like) | LLM structured extraction (parties, amounts, dates, identifiers, clauses) **+ rule-based extractors** cross-check | ✅ built |
| 6 | **Legal term spotting** | Dictionary matching against a curated bilingual glossary of Indian property-law terms (with Hindi variants) | 🆕 this plan |
| 7 | **Summarisation** (abstractive, grounded) | LLM summary + plain-language section explanations, each sentence with page citations; numbers verified in code | 🆕 this plan |
| 8 | Cross-document analysis | Entity/value comparison across documents → conflicts; user-vs-document conflicts | ✅ built |
| 9 | Retrieval (RAG) | Hybrid BM25-style full-text + embeddings over judgments; document pages via tool | ✅ built |
| 10 | Grounded QA with citations | Tool-using LLM; citation markers verified against sources; **`@` document focus** | partly → 🆕 sources UI + `@` |
| 11 | Evaluation | P/R/F1 with confidence intervals, CER/WER, faithfulness, readability | ✅ framework → 🆕 summary metrics |

This table is the backbone of the presentation's "How it works" act.

---

## 3. G1: documents always in "My documents"

**Today:** all three upload paths call the same endpoint, so documents already belong to their case
and show in that case's My documents. Missing: a cross-case view, and a link from chat attachments.

Changes:
- **API:** `GET /documents`: all of the user's documents across cases (filename, case title,
  type, status, date). Paginated, newest first.
- **App:**
  - Home screen gets a second tab, **All my documents**, grouped by case. Tap → document view.
  - The chat attachment line ("Attached receipt.pdf …") becomes tappable → the document view.
  - The document card shows type, language, pages, OCR badge and status ("Reading…", "Understood").

## 4. G2: the document view ("Understand this document")

### 4.1 What the screen shows (top to bottom)

1. **Header:** filename, detected type (e.g. *Agreement to sell*), language, pages, "read by OCR" if applicable.
2. **In one sentence:** "This is an agreement to sell a plot in Pune from Ravi Kulkarni to Meera Iyer for ₹45,00,000, with ₹5,00,000 paid as advance."
3. **Plain-language summary** (5–8 short bullet points), each with page chips `p.1`.
4. **Key details** (from extraction, already built): parties, property, amounts, dates, each with page + quote + verified/OCR marks.
5. **What the important parts mean:** clause-by-clause explanations ("Clause 5: if the seller does not complete the sale, the advance must be refunded with 12% interest per year"), each with its page and the original wording on tap.
6. **Legal terms in this document** (glossary): term → plain meaning → why it matters here → page where it appears. E.g. *Earnest money / advance (बयाना)*: a part payment made to show the buyer is serious; often refundable or forfeitable depending on the agreement. Appears on p.1.
7. **Things to check** (neutral, no conclusions): missing signatures or witnesses mentioned? referenced annexures not uploaded? stamp/registration details absent? dates inconsistent? These come from the existing flags plus document-specific checks.
8. **Ask about this document** button → opens chat with `@<this document>` prefilled.
9. **Full text by page** (already built), with the cited page highlighted when opened from a link.

A language toggle (English / हिन्दी / Hinglish) regenerates the explanation in that language (cached per language).

### 4.2 How it's generated (grounded, not free-form)

New service `app/services/understanding.py`, run in the background after fact extraction
(one fast-model call, cached in `case_documents.understanding` JSONB):

```python
class Explained(BaseModel):          # one statement in the summary/explanations
    text: str                         # plain language
    pages: list[int]                  # where it comes from
    quote: str | None                 # short original wording backing it (verified in code)

class DocumentUnderstanding(BaseModel):
    one_line: str
    document_type: str
    summary: list[Explained]          # 5-8 bullets
    clause_explanations: list[ClauseExplained]   # clause label, plain meaning, pages, quote
    things_to_check: list[Explained]
    language: str                     # en | hi | hinglish
```

Inputs: the page text (as untrusted data), the already-verified extracted facts, and the glossary
terms found in the document (§4.3), so the model explains the terms we detected rather than inventing others.

Checks in code after generation (same philosophy as the rest of the app):
- **Pages exist** and **quotes appear on the cited page** (reuse `excerpt_on_page`) → otherwise the
  statement is marked "not verified" and shown greyed out.
- **Numbers, dates and survey numbers in every statement must appear in the document** (rule-based NLP
  `nlp.extract` on the statement vs. on the document); a statement introducing a value that isn't in
  the document is **dropped** and logged. This is the main anti-hallucination check for summaries.
- **No advice or outcome language**: a small blocklist ("you will win", "this is invalid", "illegal",
  "fraud" unless quoting the document) → the statement is rewritten neutrally or dropped.
- Safety rules (`SAFETY_RULES`) apply to the prompt.

### 4.3 Legal glossary and term spotting (NLP, no LLM)

New `app/data/legal_glossary.json`: about 60 curated Indian property-law terms, each with:
`term`, `variants` (English spellings and abbreviations, Hindi forms, e.g. *agreement to sell / sale
agreement / विक्रय अनुबंध*), `plain_meaning` (English; Hindi after native-speaker review), `why_it_matters`,
`law` (e.g. Transfer of Property Act s.54, Registration Act s.17, Specific Relief Act). The meanings
are written and reviewed by us, not generated.

Initial term list (property disputes): agreement to sell, sale deed, conveyance, consideration,
earnest money / advance / बयाना, balance consideration, possession, title, clear and marketable
title, encumbrance, encumbrance certificate, 7/12 extract, khasra / khatauni / jamabandi, mutation (दाखिल-खारिज),
khata, property card, survey / gat / CTS number, power of attorney (GPA/SPA), stamp duty, registration,
sub-registrar, specific performance, refund with interest, forfeiture, time is of the essence, default,
breach, legal notice, lis pendens, injunction, caveat, indemnity, witness, attestation, executant,
vendor / purchaser, freehold / leasehold, NA (non-agricultural) permission, layout sanction, occupancy
certificate, RERA, allotment letter, cheque bounce (s.138 NI Act), succession / legal heir, partition,
gift deed, will / probate, adverse possession, benami.

`app/services/glossary.py`: `find_terms(pages) -> [(term_id, page, excerpt)]` using normalised
matching (case-folding, Devanagari normalisation, word boundaries, variants). Glossary hits feed both
the document view (§4.1 item 6) and the explanation prompt.

**Why curated, not LLM-defined:** definitions of legal terms must be stable, correct and reviewable;
an LLM may define a term slightly differently each time or wrongly for Indian law.

### 4.4 Rule-based document classifier (cross-check)

`classify(pages) -> (type, score)` from weighted keyword cues ("AGREEMENT TO SELL", "RECEIPT",
"Received from", "LEGAL NOTICE", "Under instructions from my client", "खसरा", "रसीद",
"विक्रय अनुबंध"…). If the rule label and the LLM label disagree, the document view shows
"Type: Receipt (check: could also be a payment proof)". Measured as classification accuracy on the
synthetic set and the hand-made samples.

### 4.5 Language identification

`detect_language(text)`: share of Devanagari vs Latin letters, plus Hindi marker words in Roman script
(*hai, ka, ki, ko, mein, maine, diya, nahi*) to tell **Hinglish** apart from English in chat messages. Stored per document; used to (a) pick the
default explanation language, (b) show the language on the card, (c) report results by language.

---

## 5. G3: sources under every chat reply

- The backend already verifies `[[J:…]]` and `[[D:…:pN]]` markers. Add per-message storage of the
  verified sources (`chat_messages.sources` JSONB), so they also show for old messages.
- **App:** under each assistant reply, a **Sources** block:
  - 📄 `receipt.pdf · p.1` (tap → document view at that page)
  - ⚖️ `Ravi v. State (2019), Supreme Court · ¶12` (tap → judgment)
  - If none: *"No sources cited: general information. Verify with an advocate."*
- **Prompt rule:** a reply that states a fact about the user's documents must cite the page; a reply
  making a legal point must cite a retrieved judgment or say it's general information.

## 6. G4: `@` references in chat

- **Typing `@`** in the chat box opens a dropdown of the case's documents (filename, type), filtered as
  the user types; choosing one inserts a chip `@receipt.pdf`. Several are allowed.
- **Request:** `POST /cases/{id}/chat` gets `mentions: [document_id, …]` (validated: they must belong
  to the case and be processed). The message text keeps the readable `@filename`.
- **Backend:** for that turn, the advisor adds a context block "The user is asking about these documents:"
  with each mentioned document's understanding + extracted facts + page text (untrusted, size-capped).
  The model is told to answer from them and cite their pages.
- **History:** mentions are stored with the user message and shown as chips.
- **Edge cases:** a deleted document's chip shows "(deleted)"; a document still processing gets
  "still being read, I can see its text but not its summary yet".

---

## 7. Data model and API changes

| Change | Detail |
|---|---|
| `case_documents.understanding` JSONB | `{ "en": DocumentUnderstanding, "hi": … }` cached per language |
| `case_documents.language`, `case_documents.type_rule` | Language and rule-based type |
| `chat_messages.sources` JSONB | Verified sources of an assistant reply |
| `chat_messages.mentions` JSONB | Document ids `@`-mentioned in a user message |
| `GET /documents` | All of the user's documents across cases |
| `GET /cases/{id}/documents/{doc}/understanding?lang=en` | The explanation (generated on demand if missing for that language) |
| `POST /cases/{id}/documents/{doc}/understanding/regenerate` | Rebuild |
| `POST /cases/{id}/chat` | Body gains `mentions: list[uuid]` |
| `GET /cases/{id}/chat` | Messages include `sources` and `mentions` |
| `GET /glossary/{term_id}` | A glossary entry (for tapping a term anywhere in the app) |

Migrations: additive `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, as done for `page_info`.

---

## 8. Evaluation (feeds the scorecard)

| Metric | How | Target to report |
|---|---|---|
| **Summary faithfulness (values)** | Share of numbers/dates/identifiers in the generated summary that exist in the document (rule-based check) | precision with 95% CI |
| **Summary coverage** | Share of the document's key values (ground truth) that the summary mentions | recall |
| **Quote verification rate** | Share of statements whose quote is found on the cited page | rate |
| **Faithfulness (meaning)** | LLM-as-judge on a sample (supported / partly / unsupported) + manual check of 20 | rate + agreement with manual |
| **Glossary term spotting** | Precision/recall against terms planted by the synthetic generator (and hand-labelled samples) | P/R/F1 |
| **Classifier accuracy** | Rule-based and LLM document type vs ground truth | accuracy + confusion matrix |
| **Language identification** | vs ground truth language of synthetic docs | accuracy |
| **Readability** | Flesch reading ease (English) of the plain-language summary vs the original text | before → after |
| **Citation validity in chat** | Share of `[[D:…]]` markers that resolve to a real page; share of `@`-questions whose answer cites the mentioned document | rate |
| **Latency** | Seconds to "Understood" per document (fast model) | median, p90 |

Deterministic parts (glossary, classifier, language ID, value faithfulness checker) run without an
API key; the LLM parts run with `--llm`.

---

## 9. Implementation order (milestones)

| # | Milestone | Needs API key to *verify*? |
|---|---|---|
| D1 | Language ID + rule-based classifier + glossary data + term spotting, with tests and scorecard sections | No |
| D2 | `understanding.py` (schema, prompt, code checks: pages, quotes, values, advice blocklist), background generation, endpoints, tests with a fake LLM | Code no; quality yes |
| D3 | Chat: stored sources per message, prompt rule, `mentions` in the request, focused context, tests | Code no; quality yes |
| D4 | `GET /documents` (all documents) | No |
| D5 | Android: document view sections, glossary chips, language toggle, "Ask about this document"; chat Sources block, `@` dropdown + chips, tappable attachment line; All my documents tab | Needs the Android SDK to compile |
| D6 | Evaluation: scorecard sections, `docs/eval_report.md`, presentation slide | LLM parts need a key |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Summary invents or changes a number | Value check in code drops the statement; quotes verified; "not verified" styling |
| Plain-language explanation drifts into advice ("this clause is unfair/illegal") | Prompt rules + advice blocklist + fixed disclaimer on the screen |
| Wrong definition of a legal term | Curated, reviewed glossary; the LLM explains *why it matters here*, not the definition |
| Free-tier latency/rate limits | One fast-model call per document, run in the background, cached per language; regenerate only on request |
| Long documents | Explain the first 30 pages / 120k characters and say so, as extraction already does |
| Hindi/Hinglish explanation quality | Language toggle with English fallback; Hindi glossary meanings reviewed by a native speaker |
| `@` mention of a huge document | Context size cap: understanding + facts + only the most relevant pages (embedding search over pages) |
