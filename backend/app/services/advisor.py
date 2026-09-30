"""The follow-up conversation ("advisor"): the LLM with tools to search and read judgments, streamed to the app.

History is stored append-only in chat_messages with the exact messages the model returned, so each
request replays the conversation unchanged (some providers require this, e.g. for thought signatures).
"""

import json
import logging
import re
import uuid
from collections.abc import Iterator

import openai
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.llm import prompts
from app.config import get_settings
from app.llm.client import get_client
from app.models import Case, ChatMessage, Judgment, JudgmentParagraph
from app.services.search import hybrid_search

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
CITATION_RE = re.compile(r"\[\[J:([^\]]+)\]\]")
JUDGMENT_ID_RE = re.compile(r'judgment_id="([^"]+)"')

# ---------- Tools ----------


class SearchInput(BaseModel):
    query: str = Field(min_length=3)


class ReadInput(BaseModel):
    judgment_id: str
    paragraphs: list[int] | None = None


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_judgments",
            "description": (
                "Search the database of Indian court judgments. Returns up to 6 judgments with summaries. "
                "Use specific legal and factual keywords, e.g. 'builder delay possession refund interest RERA'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_judgment",
            "description": (
                "Read a judgment's summary and paragraphs. Pass paragraph numbers to read specific paragraphs; "
                "omit them to get the paragraphs with the core reasoning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "judgment_id": {"type": "string"},
                    "paragraphs": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["judgment_id"],
            },
        },
    },
]


def _judgment_header(j: Judgment) -> str:
    return (
        f'<judgment judgment_id="{j.id}">\nTitle: {j.title}\nCourt: {j.court}\n'
        f"Date: {j.decision_date}\nCitation: {j.citation or j.neutral_citation}\nDisposal: {j.disposal}\n"
    )


def _tool_search(db: Session, args: SearchInput) -> str:
    candidates = hybrid_search(db, [args.query], limit=6)
    if not candidates:
        return "No judgments found."
    out = []
    for c in candidates:
        j = db.get(Judgment, c.judgment_id)
        s = j.summary
        out.append(
            _judgment_header(j)
            + f"Outcome: {s.get('outcome')}\nFacts: {s.get('facts')}\nHolding: {s.get('holding')}\n</judgment>"
        )
    return "\n\n".join(out)


def _tool_read(db: Session, args: ReadInput) -> str:
    j = db.get(Judgment, args.judgment_id)
    if j is None:
        raise ValueError(f"No judgment with id {args.judgment_id}")
    wanted = args.paragraphs or j.summary.get("key_paragraphs") or [1, 2, 3]
    paras = db.scalars(
        select(JudgmentParagraph).where(
            JudgmentParagraph.judgment_id == j.id, JudgmentParagraph.para_no.in_(wanted[:12])
        )
    ).all()
    body = "\n\n".join(f"[¶{p.para_no}] {p.text}" for p in paras) or "(paragraphs not found)"
    return (
        _judgment_header(j)
        + f"Summary: {json.dumps(j.summary, ensure_ascii=False)}\n\nParagraphs:\n{body}\n</judgment>"
    )


def _run_tool(db: Session, name: str, arguments: str) -> str:
    """Run a tool call; errors are returned as text so the model can correct itself."""
    try:
        if name == "search_judgments":
            return _tool_search(db, SearchInput.model_validate_json(arguments or "{}"))
        if name == "read_judgment":
            return _tool_read(db, ReadInput.model_validate_json(arguments or "{}"))
        return f"Error: unknown tool {name}"
    except (ValidationError, ValueError) as e:
        return f"Error: {e}"


# ---------- Conversation ----------


def _case_context(case: Case) -> str:
    """First (hidden) message of every conversation: the fact sheet and the search results."""
    results = "\n\n".join(
        _judgment_header(r.judgment)
        + f"Rank: {r.rank}, relevance {r.relevance}/100, stance: {r.stance}\n"
        f"How it relates: {r.explanation}\nKey paragraphs: {r.key_paragraphs}\n</judgment>"
        for r in case.results
    )
    return (
        "Context for this conversation (not written by the user).\n\n"
        f"<fact_sheet>\n{json.dumps(case.fact_sheet, ensure_ascii=False, indent=1)}\n</fact_sheet>\n\n"
        f"<search_results>\n{results or 'No search has been run yet.'}\n</search_results>"
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _append(db: Session, case: Case, message: dict, display_text: str | None) -> ChatMessage:
    msg = ChatMessage(role=message["role"], message=message, display_text=display_text)
    case.messages.append(msg)
    db.commit()
    return msg


def _seen_judgment_ids(case: Case) -> set[str]:
    """IDs of every judgment shown to the model in this conversation (context message + tool results)."""
    ids: set[str] = set()
    for m in case.messages:
        if m.role in ("user", "tool") and isinstance(m.message.get("content"), str):
            ids.update(JUDGMENT_ID_RE.findall(m.message["content"]))
    return ids


def _stream_one_turn(client: openai.OpenAI, history: list[dict]) -> Iterator[str | dict]:
    """Stream one model response. Yields text deltas (str), then the complete assistant message (dict)."""
    stream = client.chat.completions.create(
        model=get_settings().model_main,
        messages=[{"role": "system", "content": prompts.ADVISOR_SYSTEM}, *history],
        tools=TOOLS,
        stream=True,
    )
    text = ""
    calls: dict[int, dict] = {}  # tool calls arrive in fragments, keyed by index
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            text += delta.content
            yield delta.content
        for tc in delta.tool_calls or []:
            call = calls.setdefault(
                tc.index if tc.index is not None else len(calls),
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if tc.id:
                call["id"] = tc.id
            if tc.function and tc.function.name:
                call["function"]["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                call["function"]["arguments"] += tc.function.arguments
            # Keep provider-specific fields (e.g. Gemini's thought signatures); they must be sent back.
            call.update(tc.model_extra or {})

    message: dict = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    yield message


def stream_reply(case_id: uuid.UUID, user_text: str) -> Iterator[str]:
    """Generator of server-sent events: `text` deltas, `tool` status updates, then `done` (or `error`)."""
    try:
        yield from _stream_reply(case_id, user_text)
    except openai.APIError:
        log.exception("advisor request failed")
        yield _sse("error", {"message": "The assistant is unavailable right now. Please try again."})


def _stream_reply(case_id: uuid.UUID, user_text: str) -> Iterator[str]:
    client = get_client()
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if not case.messages:
            _append(db, case, {"role": "user", "content": _case_context(case)}, None)
        _append(db, case, {"role": "user", "content": user_text}, user_text)

        reply_text = ""
        last_msg: ChatMessage | None = None
        for _ in range(MAX_TOOL_ROUNDS):
            history = [m.message for m in case.messages]
            message: dict = {}
            for item in _stream_one_turn(client, history):
                if isinstance(item, str):
                    yield _sse("text", {"delta": item})
                else:
                    message = item

            reply_text += message.get("content") or ""
            last_msg = _append(db, case, message, message.get("content"))

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                break
            for call in tool_calls:
                fn = call["function"]
                yield _sse("tool", {"name": fn["name"]})
                output = _run_tool(db, fn["name"], fn["arguments"])
                _append(db, case, {"role": "tool", "tool_call_id": call["id"], "content": output}, None)

        # Citation check: only judgments that appeared in this conversation may be cited.
        seen_ids = _seen_judgment_ids(case)
        cited = list(dict.fromkeys(CITATION_RE.findall(reply_text)))
        yield _sse(
            "done",
            {
                "message_id": last_msg.id if last_msg else None,
                "cited_judgments": [c for c in cited if c in seen_ids],
                "unverified_citations": [c for c in cited if c not in seen_ids],
            },
        )
