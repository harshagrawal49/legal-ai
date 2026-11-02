# 06 · Case facts: one source of truth with provenance

## What it does
The case **fact sheet** (used by search, chat and the brief) is built from the user's documents (the
primary record) and the user's own account (optional). Every party, event and amount shows where it came
from: "you said", "from receipt.pdf p.1", or "source not confirmed". When the user and a document
disagree, **both** versions are kept and shown as a conflict.

## How it is implemented
1. Verified document facts are formatted as tagged lines, e.g.
   `[D:7f3c…:p1] amount (advance): advance: Rs. 5,50,000/- (read by OCR)`.
   Only facts whose quote was found on the page are included.
2. The intake LLM receives these lines plus the user's conversation, and returns a `FactSheet` where each
   item has `sources` (`"user"` and/or document refs) and a `conflicts` list.
3. Code checks every ref (see [04](04-verification-layer.md)):
   - the page must exist;
   - amounts must match numerically (on the page or in that page's extracted facts);
   - names must appear in the page text;
   - dates must match a date found on the page.

   Refs that fail are dropped, and `"user"` is dropped when the user hasn't written anything.
4. The fact sheet is **rebuilt automatically** after each document finishes processing, one rebuild per
   case at a time.
5. Downstream:
   - the brief lists only items with **no** document source as "your account, not supported by
     documents";
   - conflicts appear first in Timeline & flags and in the brief.

Full description: [`../case_facts.md`](../case_facts.md).

## Why this design
| Alternative | Why not |
|---|---|
| Fact sheet from the user's text only (the original design) | The documents barely shaped the case; mistakes in the user's memory went unchallenged |
| Documents silently override the user | Hides real disagreements, which are often the crux of a dispute |
| Merge in code only, no LLM | Matching "the seller" in a Hinglish sentence to "Ravi Kulkarni (Vendor)" on page 1 needs language understanding |

## Results
| Check | Result |
|---|---|
| Provenance checking, 200 cases (600 good / 800 bad refs) | All good refs kept, none of the bad kept |
| Rule-based extraction feeding the cross-check | 20/20 on samples; 100% / 96–98% / 31–57% on text / OCR (clean, photo) / degraded |
| LLM fusion quality (correct sources, conflicts found) | **Not yet measured** (needs an API key) |

**Known limitation:** an English name typed by the user doesn't match the same name written in Devanagari
in a document, so that link is dropped and shown as "you said" only. It's never wrong, just less linked.
