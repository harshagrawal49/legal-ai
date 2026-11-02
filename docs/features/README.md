# Features: how each one is built

One document per feature of NyayaSathi AI (*legal document analysis using NLP*). Each explains
**what it does, how it is implemented, why we chose this approach over the alternatives, and the
results we measured**. Scope: documents in English or Hindi; chat in English, Hindi or Hinglish.

| # | Feature | NLP / engineering technique | Status |
|---|---|---|---|
| 01 | [Case intake](01-case-intake.md) | LLM structured extraction from free text (incl. Hinglish) | ✅ |
| 02 | [Document upload and reading (OCR)](02-document-reading-ocr.md) | PDF text extraction, OCR (Tesseract), page detection | ✅ measured |
| 03 | [Information extraction (hybrid NLP)](03-information-extraction.md) | Rule-based extraction + LLM schema extraction + cross-check | ✅ measured |
| 04 | [Verification layer](04-verification-layer.md) | Quote matching, value checking, citation validation | ✅ measured |
| 05 | [Evidence pack: timeline and conflicts](05-evidence-pack.md) | Normalisation, cross-document comparison | ✅ measured |
| 06 | [Case facts: one source of truth](06-case-facts-provenance.md) | Information fusion with provenance | ✅ measured |
| 07 | [Document understanding](07-document-understanding.md) | Term spotting, language ID, classification, grounded summarisation | ✅ partly measured |
| 08 | [Legal search (RAG)](08-legal-search.md) | Hybrid retrieval (full-text + embeddings), reciprocal rank fusion, LLM re-ranking | ✅ |
| 09 | [Chat assistant](09-chat-assistant.md) | Tool-using LLM, @mentions, verified sources, streaming | ✅ |
| 10 | [Case-preparation brief](10-case-brief.md) | Assembled in code; LLM only for suggestions | ✅ |
| 11 | [Safety guardrails](11-safety-guardrails.md) | Prompt rules, fallbacks, red-team evaluation | ✅ harness ready |
| 12 | [Judgment corpus and ingestion](12-judgment-ingestion.md) | Ingestion, paragraph segmentation, filtering, incremental updates | ✅ partly; plan for the rest |
| 13 | [Speed and the LLM layer](13-llm-layer-and-speed.md) | Provider-agnostic client, model tiers, background jobs | ✅ |
| 14 | [Android app](14-android-app.md) | Kotlin + Jetpack Compose client | ✅ built and run |
| 15 | [Evaluation framework](15-evaluation.md) | Synthetic ground truth, P/R/F1, confidence intervals | ✅ |

Detailed reports: [`../eval_report.md`](../eval_report.md) (all measurements),
[`../ocr_report.md`](../ocr_report.md) (OCR engine comparison), [`../case_facts.md`](../case_facts.md),
[`../../doc_plan.md`](../../doc_plan.md), [`../../ingest_plan.md`](../../ingest_plan.md).

All numbers in these documents come from the evaluation scripts (`backend/eval/`) on synthetic,
fictional data, unless stated otherwise. Where something has not been measured, the document says so.
