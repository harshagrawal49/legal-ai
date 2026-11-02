"""Speed behaviour of the LLM client: provider limitations cost one failed request, not one per call."""

import httpx
import openai
import pytest
from pydantic import BaseModel

from app.llm import client


def _bad_request(message: str) -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://llm.test/v1/chat/completions"))
    return openai.BadRequestError(message, response=response, body=None)


@pytest.fixture(autouse=True)
def reset_learned_state(monkeypatch):
    monkeypatch.setattr(client, "_no_reasoning_effort", False)
    monkeypatch.setattr(client, "_no_json_schema", set())


def test_reasoning_effort_is_sent_and_dropped_once_rejected():
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        if "reasoning_effort" in kwargs:
            raise _bad_request("Unknown parameter: reasoning_effort")
        return "ok"

    assert client.create(call, model="m") == "ok"
    assert client.create(call, model="m") == "ok"
    # First call: tried with it, retried without. Second call: never sent again.
    assert ["reasoning_effort" in c for c in calls] == [True, False, False]


def test_other_bad_requests_are_not_swallowed():
    def call(**kwargs):
        raise _bad_request("messages: invalid role")

    with pytest.raises(openai.BadRequestError):
        client.create(call, model="m")


class Answer(BaseModel):
    value: int


class FakeCompletions:
    """parse() always rejects JSON schema; create() returns valid JSON."""

    def __init__(self):
        self.parse_calls = 0
        self.create_calls = 0

    def parse(self, **kwargs):
        self.parse_calls += 1
        raise _bad_request("response_format json_schema not supported")

    def create(self, **kwargs):
        self.create_calls += 1
        message = type("M", (), {"content": '{"value": 7}'})()
        return type("C", (), {"choices": [type("Ch", (), {"message": message})()], "usage": None})()


def test_json_schema_rejection_is_remembered_per_model(monkeypatch):
    fake = FakeCompletions()
    fake_client = type("Client", (), {})()
    fake_client.chat = type("Chat", (), {"completions": fake})()
    monkeypatch.setattr(client, "get_client", lambda: fake_client)

    assert client.structured(Answer, "sys", "user", model="m").value == 7
    assert client.structured(Answer, "sys", "user", model="m").value == 7
    assert fake.parse_calls == 1  # the second call goes straight to JSON mode
    assert fake.create_calls == 2
