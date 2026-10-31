# 15 · Evaluation framework

## What it does
It measures each part of the pipeline with **precision, recall, F1 and 95% confidence intervals**, on test
data where the right answers are known, so changes can be compared fairly and claims can be backed by
numbers.

## How it is implemented
- **Synthetic case generator:**
  - fictional property disputes: an agreement to sell, a receipt, and (in English cases) a legal notice;
  - English (60%) and Hindi (40%), with correctly shaped Devanagari;
  - **every expected value is known**: amounts, dates, survey numbers, names, glossary terms, document
    type, language;
  - **traps:** 40% of receipts show a different survey number, 40% a different advance;
  - **distractors that must not be extracted:** cheque numbers, plot area, phone numbers, "Section 54", "15 days";
  - **varied formats:** `Rs. 5,00,000/-`, `Rs 5 lakh`, `INR 500000`, `रुपये ५,००,०००`, `15th March, 2023`, `१५/०३/२०२३`;
  - a fixed seed, so every run uses the same cases.
- **Simulated scans** at three qualities: clean (300 dpi); phone photo (150 dpi, tilt, blur, JPEG);
  degraded (120 dpi, more tilt and blur, speckle, strong JPEG).
- **Scorecard**, one command:
  - rule-based extraction;
  - after-OCR extraction;
  - glossary, classifier and language identification;
  - evidence flags;
  - provenance checking;
  - optional LLM sections: extraction F1, explanation quality.
- **Statistics:** Wilson 95% intervals, so small samples are reported as ranges. For example, 20/20 means
  "at least 84%", not "100%".
- **Other harnesses:** the OCR engine benchmark (character/word error rate, key values, speed, memory);
  the safety red-team (17 cases, code checks plus an LLM judge); the app journey test.

## Why synthetic data first
Real legal documents are private and slow to label. Synthetic cases give exact ground truth at scale
(517 documents) and can plant the specific traps we care about. They are optimistic, so the next step is
a separate check on 10–20 real, permissioned documents labelled by two people.

## Results (summary; full report in [`../eval_report.md`](../eval_report.md))
| Measure | Result |
|---|---|
| Key values from typed documents | 100% F1 (2,268) |
| After OCR, clean / photo / degraded | 98.3% / 96.1% / 43.7% F1 |
| Glossary terms · document type · language | 100% · 517/517 · 517/517 |
| Planted conflicts flagged | 163/163, 0 false alarms |
| Bad source references rejected | 800/800 |
| Unit and integration tests | 105 passing |

**Bugs the evaluation found** (all fixed, each with a regression test):
1. Hindi "लाख" amounts were misread, causing false conflict alarms.
2. Devanagari survey numbers were erased during comparison.
3. OCR's comma-as-dot "5.50,000" was read as ₹5.5.
4. The Supreme Court loader would have skipped 242 of 245 judgments from 2026 (fixed in the new ingester
   and the old loader).

**Not yet measured** (needs an API key): LLM extraction, explanations, fused case facts, chat answers, and
the safety red-team. Retrieval recall@10 needs the corpus and labelled questions.
