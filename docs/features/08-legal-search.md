# 08 · Legal search: finding similar judgments (RAG)

## What it does
From the case fact sheet, it finds real Indian court judgments similar to the user's situation and
explains each one:
- whether it **supports**, **opposes** or is **mixed** for the user;
- similarities and differences;
- the key paragraphs.

## How it is implemented
1. **Queries:** the fact-sheet summary plus 3–5 search queries the intake model wrote ("refund of advance
   agreement to sell").
2. **Hybrid retrieval in PostgreSQL**, three ranked lists per query:
   - **keyword:** full-text search over judgment paragraphs (`to_tsvector('english', text)`, GIN index,
     OR-matched terms ranked by `ts_rank_cd`), which catches exact legal terms such as "specific
     performance" and "Section 54";
   - **meaning, paragraphs:** cosine similarity over paragraph embeddings (pgvector), which catches
     paraphrases ("seller sold plot to another buyer" ≈ "double sale");
   - **meaning, summaries:** cosine similarity over one embedding per judgment summary.
3. **Reciprocal Rank Fusion (RRF, k = 60)** merges the lists at judgment level. Each judgment counts once
   per list, so a long judgment can't win just by having many matching paragraphs. The top 8 candidates go on.
4. **LLM relevance analysis:** the model reads each candidate's summary and its best-matching paragraphs
   and returns relevance (0–100), stance, explanation, similarities, differences and key paragraphs.
5. **Guardrails in code:**
   - only judgment IDs that were actually retrieved are kept, which stops invented citations;
   - relevance must be ≥ 30;
   - **one result per judgment** (duplicates crashed the app's lists before this fix);
   - the top 5 are stored.
6. **Embeddings:** `BAAI/bge-small-en-v1.5` (384 dimensions), run **locally** with fastembed on the CPU,
   with no API cost and no data sent out.

## Why hybrid search, and why this embedding model
| Alternative | Why not |
|---|---|
| Keyword search only | Misses paraphrases: users describe facts, not legal terms |
| Vector search only | Weak on exact legal terms, section numbers and party names |
| A separate vector database (Pinecone, Chroma…) | pgvector keeps everything in one database: fewer moving parts and consistent transactions |
| Score fusion by weighted sums | Keyword and cosine scores aren't on the same scale; RRF needs only ranks |
| Larger or hosted embedding models (bge-large, OpenAI, Voyage-law) | Slower, or paid, or send data out; the small local model is a sensible start |
| Multilingual embeddings | Needed for Hindi judgments: planned, but only after measuring retrieval recall (see [12](12-judgment-ingestion.md)) |

## Results
- Behaviour unit-tested: an empty database gives a clear message, a search with no matches still
  completes, and duplicates are removed.
- **Retrieval quality (recall@10) is not yet measured.** It needs a loaded property-dispute corpus and a
  labelled question set; both are part of the ingestion plan.
