"""The advisor's stream parsing, using fake OpenAI-format chunks (no network)."""

from openai.types.chat import ChatCompletionChunk

from app.services.advisor import _stream_one_turn


def _chunk(delta: dict, finish: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


class FakeClient:
    def __init__(self, chunks):
        self.chat = self
        self.completions = self
        self.chunks = chunks

    def create(self, **kwargs):
        return iter(self.chunks)


def test_text_and_fragmented_tool_call_with_extra_fields():
    chunks = [
        _chunk({"role": "assistant", "content": "Let me "}),
        _chunk({"content": "check."}),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "search_judgments", "arguments": '{"query": '}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"builder delay"}'},
                                "extra_content": {"google": {"thought_signature": "sig"}}}]}),
        _chunk({}, finish="tool_calls"),
    ]
    items = list(_stream_one_turn(FakeClient(chunks), []))
    assert items[:2] == ["Let me ", "check."]
    message = items[-1]
    assert message["content"] == "Let me check."
    (call,) = message["tool_calls"]
    assert call["id"] == "call_1"
    assert call["function"] == {"name": "search_judgments", "arguments": '{"query": "builder delay"}'}
    assert call["extra_content"] == {"google": {"thought_signature": "sig"}}


def test_plain_answer_has_no_tool_calls():
    items = list(_stream_one_turn(FakeClient([_chunk({"content": "Hi"}), _chunk({}, finish="stop")]), []))
    assert items[-1] == {"role": "assistant", "content": "Hi"}


def test_history_uses_current_case_context_and_drops_stored_ones():
    import uuid

    from app.models import Case, CaseDocument, CaseResult, ChatMessage, Judgment
    from app.services.advisor import _history, _seen_judgment_ids

    case = Case(id=uuid.uuid4(), user_id="u", fact_sheet={"summary": "Advance paid, plot sold twice."})
    judgment = Judgment(id="sc-2023-1", title="A v B", court="Supreme Court of India", source_url="https://example.org")
    case.results = [CaseResult(judgment_id=judgment.id, judgment=judgment, rank=1, relevance=80, stance="supports",
                               explanation="similar facts", key_paragraphs=[])]
    case.documents = [CaseDocument(id=uuid.uuid4(), filename="receipt.pdf", status="processed", pages=["p1"], facts={})]
    case.messages = [
        ChatMessage(role="user", message={"role": "user", "content": "old context"}, display_text=None),
        ChatMessage(role="user", message={"role": "user", "content": "Can I get my advance back?"}, display_text="Can I get my advance back?"),
        ChatMessage(role="tool", message={"role": "tool", "tool_call_id": "c1", "content": "x"}, display_text=None),
    ]
    history = _history(case)
    assert "receipt.pdf" in history[0]["content"] and "plot sold twice" in history[0]["content"]
    assert [m["content"] for m in history[1:]] == ["Can I get my advance back?", "x"]
    assert "sc-2023-1" in _seen_judgment_ids(case)
