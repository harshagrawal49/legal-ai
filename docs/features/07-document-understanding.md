# 07 · Document understanding

## What it does
Opening any document shows **Explained**:
- the document type and a one-line description;
- a plain-language summary (5–8 points);
- what the important clauses mean;
- the **legal terms** in it, with their meaning, their Hindi name, why they matter, the law, and the page
  where each appears;
- **things to check**;
- an **Ask about this document** button that opens chat with the document `@`-mentioned.

It's available in **English, हिन्दी or Hinglish**. All documents also appear under **All my documents**
across cases.

## How it is implemented
Four NLP components:

1. **Legal term spotting (dictionary-based):**
   - a curated glossary of **46 Indian property-law terms**: agreement to sell, sale deed, earnest
     money/बयाना, specific performance, mutation/दाखिल-खारिज, khasra/khatauni, 7/12, encumbrance, lis
     pendens, adverse possession, benami, RERA, and others;
   - each term has English and Hindi variants;
   - matching is normalised (Unicode NFC, case-folded, flexible whitespace), uses boundaries that work for
     Devanagari, and lets longer variants win (so "encumbrance certificate" beats "encumbrance").
2. **Language identification:** the share of Devanagari letters decides Hindi; a weighted list of common
   Roman-script Hindi words (hai, ka, maine, diya, nahi, isme, kitna…) separates **Hinglish** from English,
   with words like "par" and "mai" that are also English counted at lower weight.
3. **Document classification (rule-based):** weighted cue phrases per type, with title cues counted
   extra, e.g. "agreement to sell", "received from", "under instructions from my client", रसीद, खसरा. The
   result cross-checks the LLM's label; a disagreement is shown ("could also be…").
4. **Grounded plain-language summarisation (LLM):**
   - one fast-model call per document and language, run in the background after extraction and cached;
   - other languages are generated on first request;
   - every statement must cite pages and a quote, and then goes through the verification layer
     ([04](04-verification-layer.md)): quotes checked, any statement with an invented amount/date/survey
     number dropped, advice dropped;
   - term **definitions come from the glossary**, and the model only says how each term is used *in this
     document*;
   - if the LLM is unavailable, the type, terms and rule-based checks are still shown.

## Why this design
| Alternative | Why not |
|---|---|
| LLM-written definitions of legal terms | They vary between runs and can be subtly wrong for Indian law; a curated glossary is stable and reviewable |
| Free-form summaries | Can't be checked; ours are point-by-point with pages and quotes, so each point can be verified |
| A trained language-ID / classification model | Not needed: English vs Hindi script is trivial, and Hinglish markers plus cue phrases reach 100% on our sets with no training data |
| Translating the whole document | Error-prone and not what users need; we explain the document in their language and keep quotes in the original |

## Results (200 synthetic cases, 517 documents)
| Check | Result |
|---|---|
| Glossary terms spotted | **100%** precision and recall (2,185) |
| Document type (rule-based) | 517 / 517 |
| Document language | 517 / 517 |
| Chat-message language (en / hi / Hinglish, 24 hand-labelled) | 24 / 24 (development set: 23/24 before the word list was widened) |
| False positives checked | "will" (the verb) isn't matched as *will* the document; "advanced" isn't matched as *advance* |
| Plain-language explanation quality | **Not yet measured.** Harness ready: dropped-statement rate, quote verification rate, key-value coverage |

The synthetic set uses three document templates, so classification is easy here; real documents (sale
deeds, land records, court filings) need their own test set. The Hindi explanations of glossary terms
should be reviewed by a native speaker before being added.
