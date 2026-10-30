# Fine-tuning: deferred

Fine-tuning is **not** part of the initial build. Nothing in this repository trains a model, and no
training dependencies are installed. This note records when it would make sense and what has to be
in place first.

## Start only if all of these hold

1. The end-to-end workflow (upload → facts → evidence → brief) works.
2. The baseline in `docs/evaluation.md` has been run with the real model and shows **one repeated,
   measurable failure**. Examples: amounts missed in one document type, or a low schema-valid rate.
3. Better prompts, validation and retrieval have been tried and haven't fixed that failure enough.
4. Reviewed, **permissioned** training examples exist (synthetic, or with documented consent), plus a
   held-out test set split by underlying case/document, not by random rows.
5. The model's licence allows fine-tuning and the intended use, and compute and time are available.

## Likely first experiment

Supervised fine-tuning (LoRA/QLoRA) of an open model for **structured fact extraction** into
`DocumentFacts`. Compare the base and tuned models on the same held-out set, using the metrics from
`eval/run_eval.py`. Report the metrics, failures, compute used, and whether tuning helped.

Fine-tuning does not replace RAG or an up-to-date legal-source corpus, and it does not remove the
need for code-side validation and source verification.
