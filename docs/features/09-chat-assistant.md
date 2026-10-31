# 09 · Chat assistant

## What it does
The user can ask anything about their case in English, Hindi or Hinglish. Answers:
- **stream** word by word;
- know the whole case (fact sheet, documents, similar judgments);
- **cite** document pages and judgments;
- end with a **Sources** list.

Typing **`@`** suggests the case's documents; the answer then focuses on the mentioned document.

## How it is implemented
- **A tool-using LLM** with three tools: `search_judgments` (hybrid search, see [08](08-legal-search.md)),
  `read_judgment` (specific paragraphs) and `read_case_documents` (extracted facts or page text). At most
  3 tool rounds per reply, to keep latency down.
- **Fresh context on every turn:** the case context (fact sheet, document list, search results) is rebuilt
  for each message rather than stored once, so a document uploaded mid-conversation is seen straight away.
- **@ mentions:** the request carries `mentions` (document IDs, validated to belong to the case). The
  mentioned documents' summary, facts and page text (capped at 12k characters) travel inside that user
  message as untrusted data, with an instruction to answer from them and cite their pages.
- **Citations as checkable markers:** `[[J:<judgment>]]` and `[[D:<document>:p<N>]]`. After the reply,
  code verifies them (see [04](04-verification-layer.md)), stores the verified **sources** with the
  message (so they reappear in history), and reports any @-mentioned document the answer didn't cite.
- **Streaming:** server-sent events (`text`, `tool`, `done` with sources, `error`). The app parses them
  with OkHttp SSE into an unbounded buffer, so events are never dropped.
- **Prompt rules:**
  - answer in the user's language and script (Hinglish when they write Hinglish);
  - keep what a document says, what the user says and what the AI infers separate;
  - say "not found in the uploaded documents", not "didn't happen";
  - general legal points without a retrieved judgment are labelled as general information;
  - plus the safety rules ([11](11-safety-guardrails.md)).

## Why this design
| Alternative | Why not |
|---|---|
| Plain chat with everything stuffed into the prompt | Too long for big cases; the model can't fetch what it needs; slower and more expensive |
| Free-text citations ("see the Supreme Court case on…") | Can't be verified; markers can |
| Storing the case context once at the start | The original design: chat missed later documents and searches |
| Polling instead of streaming | Long answers feel frozen; streaming shows progress immediately |

## Results
- Unit-tested: stream parsing (including fragmented tool calls), safe fallback when a reply is blocked,
  @-mention context, rejecting mentions from another case, sources stored and returned in history.
- The Android chat was reviewed twice by an independent static review; fixes included tracking each
  reply by position (a race could write text into the wrong bubble) and never dropping stream events.
- **Answer quality and citation accuracy on real conversations are not yet measured.**
