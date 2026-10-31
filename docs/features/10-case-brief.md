# 10 · Case-preparation brief

## What it does
A draft the user takes to an advocate, in nine sections that keep different kinds of information apart:

1. The user's summary
2. Documents processed (including those that couldn't be read, and OCR quality)
3. Chronology, each event linked to a page
4. Facts supported by the documents (verified quotes only)
5. The user's account **not** supported by documents
6. Gaps, inconsistencies and user-vs-document conflicts
7. Potentially relevant judgments and why they may matter
8. Questions to discuss with an advocate (AI-suggested, labelled)
9. A preparation checklist (AI-suggested, labelled)

It carries a fixed disclaimer, and nothing is filed, signed or sent.

## How it is implemented
- **Sections 1–7 are assembled in code** from stored, already-verified data: the timeline and flags
  ([05](05-evidence-pack.md)), facts whose quotes were verified, fact-sheet items with no document source
  (for section 5), conflicts ([06](06-case-facts-provenance.md)), and search results ([08](08-legal-search.md)).
- **Sections 8–9 come from one fast-model call**, labelled "AI-suggested". If that call fails, simple
  questions and checklist items are derived from the flags instead, and the brief says so.
- The disclaimer is fixed text, never written by the model.

## Why this design
| Alternative | Why not |
|---|---|
| Let the LLM write the whole brief | It mixes facts, claims and suggestions and can invent; assembling in code keeps every item traceable |
| No separation between the user's claims and document facts | An advocate needs to know what is proven by paper and what is only alleged |

## Results
- Unit-tested: section separation, LLM fallback, user-only statements filtered correctly, conflicts
  included with page links.
- Exercised end to end in the app journey test against the real API handlers.
