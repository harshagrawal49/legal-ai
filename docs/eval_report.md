# Evaluation report

Project: **Legal document analysis using NLP** (NyayaSathi AI). Date: 2026-10-31.
Scope: documents in **English and Hindi**; chat in English, Hindi and Hinglish.
Every number here was produced by scripts in `backend/eval/` and can be reproduced (§8).

## 1. Headline

On **200 synthetic property-dispute cases: 517 documents (117 English cases, 83 Hindi cases)** with known ground truth:

| What | Result | 95% CI |
|---|---|---|
| **Key values (amounts, dates, survey numbers) from typed documents**, F1 | **100%** (2,268 / 2,268, no false positives) | ≥ 99.8% |
| **Key values after OCR, clean scans**, F1 | **98.3%** (precision 99.1%, recall 97.6%) | recall 95.7–98.6% |
| **Key values after OCR, phone-photo-like scans**, F1 | **96.1%** (precision 97.3%, recall 95.0%) | recall 92.5–96.6% |
| Key values after OCR, degraded scans, F1 | 43.7% (precision 74.2%, recall 30.9%) | recall 26.9–35.3% |
| **Legal terms spotted** (glossary), F1 | **100%** (2,185 / 2,185) | ≥ 99.8% |
| **Document type** (rule-based classifier), accuracy | **100%** (517 / 517) | ≥ 99.3% |
| **Document language** (English / Hindi), accuracy | **100%** (517 / 517) | ≥ 99.3% |
| **Chat language** (English / Hindi / Hinglish), accuracy | 100% (24 / 24) | ≥ 86.2%; development set, see §3.3 |
| **Planted discrepancies between documents flagged**, F1 | **100%** (163 / 163, 0 false alarms) | ≥ 97.7% |
| **Fact-sheet document references checked correctly** | **100%** (600 good refs kept, 0 of 800 bad refs kept) | ≥ 99.4% |

The **LLM parts** have harnesses ready but are **not yet measured**, because the development machine
has no API key (§6). These are document extraction, plain-language explanations, combining the user's
account with the documents, chat answers, and the safety red-team.

## 2. Test data

`eval/generate_cases.py` creates fictional disputes (a buyer paid an advance under an agreement to
sell; the seller allegedly agreed to sell to someone else) as an agreement, a receipt and, for
English cases, a legal notice. Because the generator picks every fact, every expected value is known.

- **Languages:** English (60%) and Hindi (40%), with Devanagari rendered with correct conjunct shaping.
- **Varied formats:**
  - amounts: `Rs. 5,00,000/-`, `Rs 5,00,000`, `INR 500000`, `Rs. 5 lakh`, `रुपये 5,00,000`, `रुपये ५,००,०००`, `रुपये 5 लाख`;
  - dates: `15 March 2023`, `15/03/2023`, `15th March, 2023`, `March 15, 2023`, `15 मार्च 2023`, `१५/०३/२०२३`.
- **Planted discrepancies:** in 40% of cases the receipt shows a different survey number, and in 40% a different advance.
- **Distractors that must not be extracted:** cheque numbers, plot area, phone numbers, "Section 54", "15 days".
- **Labels per document:** expected values, party names, glossary terms, document type, language.
- **Scans** (`eval/scans.py`): clean (300 dpi); photo (150 dpi, 1.5° tilt, blur, JPEG); degraded (120 dpi, 3° tilt, more blur, speckle, strong JPEG).

Fixed seed (7), so every run uses the same cases and changes can be compared fairly.

## 3. Results in detail

### 3.1 Rule-based extraction on typed text (`app/services/nlp.py`)

| Field | Precision | Recall | TP / FP / FN |
|---|---|---|---|
| Amounts | 100% | 100% | 917 / 0 / 0 |
| Dates | 100% | 100% | 834 / 0 / 0 |
| Property identifiers | 100% | 100% | 517 / 0 / 0 |
| English · Hindi | 100% · 100% | 100% · 100% | 1,521 · 747 TP |

**Caveat:** the same team wrote the rules and the document templates, so this is an optimistic upper
bound. It shows the rules handle every format we know about and ignore the distractors. The OCR results
(§3.2) and the hand-written samples (20/20 in `eval/run_eval.py`) are more independent checks.

### 3.2 After OCR (Tesseract 5.5.4, `eng+hin`, 40 cases ≈ 100 documents per level)

| Quality | Key values P / R / F1 | Party names recall | s/page |
|---|---|---|---|
| clean | 99.1% / 97.6% / **98.3%** | 98.7% | 0.5 |
| photo | 97.3% / 95.0% / **96.1%** | 95.3% | 0.6 |
| degraded | 74.2% / 30.9% / 43.7% | 44.4% | 1.3 |

Almost everything survives clean and photo-quality scans. On degraded scans recall collapses, and a
quarter of the values read are wrong (precision 74.2%). That's why every OCR'd value is labelled
"read by OCR, check digits and names" in the app. The engine comparison and choice are in
[`ocr_report.md`](ocr_report.md).

### 3.3 Document understanding without an LLM (`app/services/glossary.py`)

| Check | Result |
|---|---|
| Glossary term spotting (46 curated terms, English + Hindi variants) | P = R = 100% (2,185 TP) |
| Document type, rule-based classifier (agreement / receipt / legal notice) | 517 / 517 |
| Document language (English / Hindi) | 517 / 517 |
| Chat language (English / Hindi / Hinglish), 24 hand-labelled messages | 24 / 24 |

**Caveats:**
- The synthetic documents use 3 templates, so classification is easy here. Real documents (sale deeds,
  land records, court filings) need their own test set.
- The 24 chat messages were also used while building the Hinglish detector: the first run got 23 / 24,
  and the word list was then widened. Treat 24 / 24 as a development-set score; a fresh, held-out
  set of Hinglish messages should be collected.
- Glossary hits were also tested for false positives, such as "will" the verb not matching *will*
  (the document), and "advanced" not matching *advance* (`tests/test_glossary.py`).

### 3.4 Evidence flags

| Flag | Precision | Recall | TP / FP / FN |
|---|---|---|---|
| Survey-number difference | 100% | 100% | 81 / 0 / 0 |
| Advance-amount difference | 100% | 100% | 82 / 0 / 0 |

These flags are computed from correctly extracted facts with the documents' varied wording, so this
measures the comparison logic: normalisation (`123 / 4` = `१२३/४`), Indian number formats
(`Rs 5 lakh` = `Rs. 5,00,000/-` = `रुपये ५,००,०००`), and no false alarms.

**A bug found by this evaluation:** an earlier run gave **4 false amount alarms (precision 96.0%)**.
The amount parser used by the flags understood "lakh" but not the Hindi **लाख**, so "रुपये 5 लाख" was
read as ₹5. It's fixed (one shared parser for the whole app, with a regression test).

### 3.5 Provenance checking

For each case the fact sheet was given 3 correct document references and 4 bad ones: a name that isn't
on the page, a wrong amount, a page that doesn't exist, and an unknown document. `intake.check_sources`
kept all 600 correct references and none of the 800 bad ones.

## 4. Other checks

| Check | Result | Source |
|---|---|---|
| PDF failure handling (not a PDF, damaged, blank, password-protected) | 4/4 correct errors | `eval/run_eval.py` |
| Rule-based extraction on hand-written samples (3 English + 2 Hindi documents) | 20/20 | `eval/run_eval.py` |
| OCR on the Hindi samples, Tesseract `eng+hin` | clean and photo 100% key values; degraded 40% | `ocr_report.md` §4.2b |
| Unit tests | 102 passing, 1 skipped (PaddleOCR, on request) | `uv run python -m pytest` |

## 5. What the code checks (so LLM mistakes are caught, not shown)

| Risk | Check in code |
|---|---|
| A made-up value in a summary or explanation | Values in each statement must exist in the document, otherwise the statement is dropped |
| A quote that isn't really there | Quotes must match the cited page, otherwise shown as "quote not confirmed" |
| Advice or outcome claims in an explanation | Phrase filter drops them ("you will win", "this is illegal") |
| A wrong legal definition | Definitions come from the curated glossary, not the model |
| Fact-sheet facts with a fake source | References verified against the page (§3.5) |
| Chat citing a page that doesn't exist, or a judgment never retrieved | Shown as "[unverified source]"; only verified sources appear in the Sources list |

## 6. Not yet measured (needs an API key)

| Part | Harness | Command |
|---|---|---|
| LLM document extraction, P/R/F1 per field | ready | `uv run python -m eval.run_all --llm --llm-cases 20` |
| Plain-language explanations: dropped-statement rate, quote verification, key-value coverage | ready | same command (§6 of the scorecard) |
| Safety red-team (17 cases) | ready | `uv run python -m eval.run_safety_eval` |
| Combining the user's account with documents (sources, conflicts) | to add | — |
| Similar-case search, recall@10 | to add (needs loaded judgments + labelled questions) | — |

## 7. Limitations

- **Synthetic data:** template documents and simulated scans. Real documents vary more (layouts,
  handwriting, stamps, shadows, curved pages). The most important next step is a check on 10–20 real,
  permissioned documents labelled by two people, reported separately from the synthetic numbers.
- **The same team wrote the rules and the templates** (§3.1), and the chat-language set was used during development (§3.3).
- Values are matched exactly; a value that's "nearly right" counts as wrong.

## 8. Reproduce

```bash
cd backend
brew install tesseract tesseract-lang          # once
uv run python -m eval.run_all                  # deterministic sections; OCR on 40 cases (~6 min)
uv run python -m eval.run_all --ocr-cases 0    # without OCR (~10 s)
uv run python -m eval.run_eval                 # hand-written samples + PDF handling
```
Raw results: `eval/results/scorecard-20261031-175115.{json,md}` (with OCR) and
`scorecard-20261031-175202.{json,md}` (all non-OCR sections, including §3.3).
