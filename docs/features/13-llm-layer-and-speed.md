# 13 · The LLM layer and speed

## What it does
It gives every feature one way to call a language model: provider-independent, validated, fast enough on
a free tier, and failing gracefully.

## How it is implemented
- **Provider-agnostic:** one client for any **OpenAI-compatible API**. The default is the Google Gemini
  free tier, and switching to Groq, OpenRouter or a local Ollama server is a configuration change. **No
  API key is ever in the Android app**; only the backend holds it.
- **Two model tiers:** a *fast* model (flash-lite) for intake, document extraction, explanations and brief
  suggestions; a *main* model for search analysis and chat.
- **Short thinking:** calls send a low `reasoning_effort`. If a provider rejects that parameter, it's
  dropped once and remembered.
- **No wasted calls:** if a model rejects JSON-schema output, later calls go straight to JSON mode (with
  the schema in the prompt), and the result is still validated.
- **Fail fast:**
  - 2 retries and a 90 s timeout, instead of waiting minutes on free-tier rate limits;
  - a friendly "busy, try again" message (HTTP 503);
  - clear refusal messages.
- **Background work:** OCR, fact extraction, explanations and fact-sheet rebuilds run after the upload
  returns, while the app polls. Uploads respond in about a second.
- **Smaller prompts:**
  - search sends 8 candidates with 2 short paragraphs each (previously 15 × 4);
  - chat uses at most 3 tool rounds;
  - the embedding model is loaded at startup.
- **Observability:** every LLM call logs the task, model, seconds and tokens in and out, so slow steps can
  be found from the server log.

## Why
| Alternative | Why not |
|---|---|
| Hard-wire one provider's SDK | Lock-in; the project must run on a free tier now and a private/local model later |
| Run the LLM locally (Ollama) by default | Too heavy for a 16 GB laptop alongside the backend; kept as an option for privacy |
| Do everything inside the upload request | Users waited minutes with no feedback (the original problem) |

## Results
- The original complaint ("it takes minutes to respond") was addressed by these changes. The per-call
  timing logs are in place, but **before/after timings on the free tier haven't been recorded**.
- Unit-tested: `reasoning_effort` is dropped once when rejected; a JSON-schema rejection is remembered per
  model; other bad requests aren't swallowed.
