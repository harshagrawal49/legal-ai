# Case facts from documents + the user's account

> Documents: English or Hindi. The user's account: English, Hindi or Hinglish.

The case **fact sheet** is the single source of truth that search, chat and the brief all use. It is
built from **two sources**:

1. **the user's documents**: the primary record for names, dates, amounts and property identifiers;
2. **what the user says**: the description and answers to follow-up questions. This is optional:
   a case can start from documents alone.

Every fact keeps its **provenance**, disagreements are **kept, not resolved**, and every document
reference the AI gives is **checked in code** before it's shown.

---

## 1. Pipeline

```
uploaded PDF / photo
  → text per page (selectable text, or OCR for scans: docs/ocr_report.md)
  → LLM extraction into DocumentFacts (each fact with page + quoted excerpt)
  → code checks: the quote must exist on the cited page          (documents.verify_sources)
  → rule-based NLP cross-check                                    (nlp.cross_check)
       amounts / dates / survey numbers found by both → corroborated
       found by the rules but not the LLM → possibly_missed (shown as a flag)
  → case fact sheet rebuilt                                       (intake.run_intake)
       input: the user's conversation (if any) + verified document facts tagged [D:<doc>:p<N>]
       output: FactSheet with sources on every party / event / amount, plus conflicts
  → code checks every document ref                                (intake.check_sources)
       the ref must be a real page of a processed document, AND the value must appear on that
       page (amounts compared numerically, names as text, dates against rule-found dates)
       → refs that fail are dropped; an item with no source left is marked "unverified"
  → search, chat and the brief use the fact sheet
```

The fact sheet is rebuilt **after every intake answer** and **every time a document finishes
processing** (`documents.extract_in_background → intake.refresh_after_document`). One rebuild per case
runs at a time.

## 2. Rule-based NLP (`app/services/nlp.py`)

Deterministic extractors: no LLM, so they can't invent values.

| Kind | Recognised forms |
|---|---|
| Amounts | `Rs. 5,00,000/-`, `₹ 4.5 lakh`, `INR 1.2 crore`, `रुपये ५,००,०००`, `रुपये ५ लाख`, `करोड़`, `कोटी`; OCR comma-as-dot (`5.50,000`) |
| Dates | `15/03/2023`, `15-03-2023`, `15.03.2023`, `15 March 2023`, `15th March, 2023`, `March 15, 2023`, Hindi month names (`15 मार्च 2023`), Devanagari digits (`१५/०३/२०२३`); impossible dates rejected; day-first (Indian convention) |
| Property identifiers | survey / S. no. / gat / plot / khata / CTS / city survey / flat numbers; `सर्वे क्रमांक`, `सर्वे नंबर`, `खसरा नंबर`, `प्लॉट`, `खाता`, `भूखंड`; values like `123/4`, `123/A`, `१२३/४` |

Normalisation makes different spellings comparable: `123 / 4` = `123/4` = `१२३/४`, and
`Rs 5.5 lakh` = `Rs. 5,50,000/-`.

## 3. Provenance in the fact sheet

```json
{
  "amounts": [
    {"description": "advance", "value": "Rs. 5,50,000/-", "sources": ["D:7f3c…:p1"]}
  ],
  "events": [
    {"date": "2023-03-15", "description": "Advance paid", "sources": ["user", "D:7f3c…:p1"]},
    {"date": "2024-01", "description": "Heard the plot was sold again", "sources": ["user"]}
  ],
  "conflicts": [
    {"description": "advance amount", "user_says": "Rs 6 lakh",
     "documents_say": "Rs. 5,50,000/-", "sources": ["D:7f3c…:p1"]}
  ]
}
```

| `sources` | Meaning | Shown in the app as |
|---|---|---|
| `"user"` | the user said it | "you said" |
| `"D:<id>:p<N>"` | checked against that document page | "from receipt.pdf p.1" |
| `"unverified"` | the AI claimed a source that didn't check out | "source not confirmed" |

How it's used downstream:
- **Brief §5** ("your account, not supported by the documents") lists only items with **no document source**.
- **User-vs-document conflicts** appear first in *Timeline & flags* and in the brief's gaps section,
  linked to the page (`user_document_conflict`).
- **Intake questions** skip what the documents already answer and ask the user to confirm conflicts.

## 4. Documents-only cases

`POST /cases` with an empty description creates the case without an LLM call (title
"New case (from documents)"). When the first document is processed, the fact sheet is built from it.
In the app: attach documents on the first screen and tap **Continue with documents only**; the app
waits ("Reading your documents and building the case summary…") and then shows the summary with sources.

## 5. Measured results (2026-10-31)

| Check | Result |
|---|---|
| Rule-based NLP on the sample text (3 English + 2 Hindi documents) | **20/20** expected amounts, dates and identifiers found (`eval/run_eval.py`) |
| Rule-based NLP on **Tesseract OCR text**, English | clean **13/13**, photo **13/13**, degraded 4/13 |
| Rule-based NLP on **Tesseract OCR text**, Hindi (Devanagari) | clean **7/7**, photo **7/7**, degraded 4/7 (measured with one Marathi page, since dropped) |
| Unit tests | `tests/test_case_facts.py`: extractors (English, Hindi, date formats, lakh/crore), cross-check, prompt block, provenance checking (fake refs, wrong values, "user" when the user said nothing), conflicts, documents-only intake, refresh after a document (including LLM failure), brief separation, `POST /cases` with no description |
| LLM fusion quality (does the model tag sources correctly, find conflicts?) | **not yet measured**: needs an API key; the code checks above apply either way |

## 6. Limitations

- Names are only matched as text: an English name in the user's message won't match the same name
  written in Devanagari in a document, so that ref is dropped (shown as "you said" only). Never wrong, but less linked.
- Undated events can only be checked to the level of "the page exists".
- Rule-based extraction recall drops sharply on degraded scans (31–57%). The LLM extraction and
  the OCR labels remain, and the user is asked to check against originals.
- Whether the LLM finds *all* user-vs-document conflicts isn't guaranteed. Document-vs-document
  differences are always caught by the deterministic evidence flags.
