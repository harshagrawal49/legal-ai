# 04 · Verification layer: "the model proposes, the code verifies"

## What it does
Nothing the LLM writes is shown to the user as fact until code has checked it. Unverified items are
marked as unverified or removed, never silently trusted. This is what makes the app usable for legal
preparation.

## How it is implemented (five layers)
| Layer | Check | What happens on failure |
|---|---|---|
| 1. Schema | Every LLM output must validate against a Pydantic schema; if the provider rejects JSON-schema mode, JSON mode with the schema in the prompt is used, and the result is validated either way | Invalid output is treated as a failure, with a safe fallback (e.g. a document is kept as "text only") |
| 2. Quotes | Each extracted item's quote must occur on the cited page (Unicode-normalised, ignoring line breaks and punctuation) | Item marked `verified: false`; shown as "quote not confirmed" and excluded from the brief's "supported facts" |
| 3. Values | Every amount, date or survey number in an AI-written statement (summaries, clause explanations) must exist in the document, checked with the rule-based extractors | The statement is **dropped** and logged |
| 4. Sources | A fact-sheet reference `D:<document>:p<N>` must point to a real page of a processed document, and the value must be on that page (amounts compared numerically) | The reference is dropped; an item with no valid source is marked "unverified" |
| 5. Citations in chat | Judgment citations must be judgments actually retrieved in the conversation; document citations must be real pages | Shown as "[unverified source]"; only verified ones appear in the Sources list |

There's also an **advice filter**: explanation statements making outcome or legal-validity claims ("you
will win", "this is illegal/void") are dropped.

## Why not simply trust a better prompt
Prompts reduce errors but can't guarantee anything: models still occasionally invent a page number or an
amount. Checks in code are deterministic, testable and cheap. Their cost is recall: a correct statement
with a badly copied quote is shown as "not confirmed" rather than as verified. We think that trade-off
is right for legal material.

## Results
| Check | Result |
|---|---|
| Source references (200 cases): 600 correct, 800 bad (name not on the page, wrong amount, missing page, unknown document) | **All 600 correct kept, 0 of 800 bad kept** (95% CI ≥ 99.4%) |
| Explanation statements with invented values / advice | Dropped in tests with a fake LLM; real-model drop rate to be measured (`run_all --llm`) |
| Chat citation checking | Unit-tested; live rate to be measured |
