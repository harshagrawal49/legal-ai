"""LLM access through any OpenAI-compatible API.

Default is the Google Gemini API free tier. Point LLM_BASE_URL / LLM_API_KEY / model names in .env at
another provider (Groq, OpenRouter, a local Ollama server, ...) without code changes.
"""

import json
from functools import lru_cache
from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMRefusal(Exception):
    """The model declined the request."""


@lru_cache
def get_client() -> openai.OpenAI:
    s = get_settings()
    # Retries cover free-tier rate limits (HTTP 429) with exponential backoff.
    return openai.OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, max_retries=5, timeout=300)


def structured(
    output_format: type[T],
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 16000,
) -> T:
    """One request whose response is parsed into `output_format`.

    Uses JSON-schema structured output when the provider supports it; otherwise falls back to plain
    JSON mode with the schema in the prompt, and validates the result with Pydantic either way.
    """
    model = model or get_settings().model_main
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    client = get_client()

    try:
        completion = client.chat.completions.parse(
            model=model, messages=messages, response_format=output_format, max_tokens=max_tokens
        )
        message = completion.choices[0].message
        if message.refusal:
            raise LLMRefusal(message.refusal)
        if message.parsed is not None:
            return message.parsed
    except openai.BadRequestError:
        pass  # provider doesn't accept this schema; use JSON mode below

    schema = json.dumps(output_format.model_json_schema())
    completion = client.chat.completions.create(
        model=model,
        messages=[
            messages[0],
            {"role": "user", "content": f"{user}\n\nRespond with only a JSON object matching this JSON schema:\n{schema}"},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    content = completion.choices[0].message.content or ""
    try:
        return output_format.model_validate_json(content)
    except ValidationError as e:
        raise RuntimeError(f"Model returned invalid JSON for {output_format.__name__}: {e}") from e
