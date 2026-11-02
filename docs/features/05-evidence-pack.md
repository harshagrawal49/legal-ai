# 05 · Evidence pack: timeline and conflicts

## What it does
Across all of a case's documents:
- **Chronology:** every dated event, oldest first, each linked to its document page.
- **Flags:**
  - different survey numbers, amounts or key dates between documents;
  - documents mentioned but not uploaded ("Annexure A");
  - no property identifier anywhere;
  - extraction failures;
  - unverified quotes;
  - OCR quality issues;
  - values possibly missed by extraction;
  - user-vs-document conflicts.

## How it is implemented
- **Deterministic code, no LLM**, so it's reproducible and explainable.
- **Normalisation** before comparison:
  - identifiers: lowercase, punctuation removed, Devanagari digits mapped to ASCII, Devanagari letters
    kept (`१२३/अ` → `123अ`);
  - amounts: one parser for the whole app, handling Indian grouping, lakh/crore/लाख/करोड़ and the OCR
    comma-as-dot slip;
  - dates: ISO.
- Comparison only where one value is expected: total consideration, advance, agreement date,
  registration, deadline. Instalments, for example, can legitimately differ.
- **Neutral wording:** "may be a typo, a different property, or a real discrepancy; check the originals".
  Never "fraud". Gaps are phrased as "not found in the uploaded documents", never "didn't happen".
- Every flag carries its sources (document, page, value, whether the page was OCR'd).

## Why rules, not the LLM
Conflicts have to be stable (the same input always gives the same flags), auditable (each flag shows its
evidence) and free of judgement. An LLM asked "are there inconsistencies?" gives different answers on
each run and tends to characterise them ("suspicious"). Rules do this job better.

## Results (200 synthetic cases, from correctly extracted facts with varied wording)
| Flag | Precision | Recall | TP / FP / FN |
|---|---|---|---|
| Survey-number difference | 100% | 100% | 81 / 0 / 0 |
| Advance-amount difference | 100% | 100% | 82 / 0 / 0 |
| All planted discrepancies | **100%** (95% CI ≥ 97.7%) | **100%** | 163 / 0 / 0 |

The first run had **4 false alarms (precision 96%)** because Hindi "लाख" wasn't parsed, so "रुपये 5 लाख"
was read as ₹5. That's fixed, with a regression test. This measures the comparison logic; end-to-end flag
quality also depends on extraction ([03](03-information-extraction.md)).
