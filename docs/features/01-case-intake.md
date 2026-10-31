# 01 · Case intake

## What it does
The user describes the problem in their own words, in English, Hindi or Hinglish ("maine 5 lakh advance
diya tha par seller ne plot kisi aur ko bech diya"), or skips this and only attaches documents. The app
turns that into a structured **fact sheet** and asks up to four follow-up questions about what's missing.

## How it is implemented
- **Structured extraction:** one LLM call returns an `IntakeResult` that is validated against a strict
  schema:
  - case title;
  - fact sheet: summary, parties, events, amounts, documents, actions taken, relief sought, location,
    issues, legal areas, search queries, missing information and conflicts;
  - follow-up questions;
  - `ready_to_confirm`.
- **Fused with documents:** the prompt receives the user's conversation **and** the verified facts from
  their uploaded documents, each tagged `[D:<document>:p<page>]` (see [06](06-case-facts-provenance.md)).
- **Rebuilt, not appended:** every new answer re-derives the whole fact sheet from the full conversation
  plus the current documents, so corrections replace old values. Unanswered questions are replaced rather
  than piled up.
- **Documents-only cases:** an empty description creates the case without an LLM call; the fact sheet is
  built when the first document finishes processing.
- **Fast model:** intake uses the lighter model tier (see [13](13-llm-layer-and-speed.md)).
- **Safety:** if the user asks for help with something illegal, it is not recorded as "relief sought"; the
  first follow-up question becomes a polite refusal with the lawful alternative (see [11](11-safety-guardrails.md)).

## Why this approach
| Alternative | Why not |
|---|---|
| A long form with fixed fields | People in distress don't think in fields; free text plus a few targeted questions gets better information with less friction |
| Rule-based parsing of the description | Free-form Hinglish narratives are too varied for rules; the LLM is good at this, and the schema keeps its output structured |
| Appending each answer to the previous fact sheet | Leads to contradictions and stale values; rebuilding from the full conversation keeps one consistent version |

## Results
- Behaviour covered by unit tests (documents-only cases, rebuild after a document, failure handling).
- **LLM intake quality has not been measured yet** (needs an API key). The evaluation harness for
  extraction is ready ([15](15-evaluation.md)).
