"""LLM access through any OpenAI-compatible API.

Default is the Google Gemini API free tier. Point LLM_BASE_URL / LLM_API_KEY / model names in .env at
another provider (Groq, OpenRouter, a local Ollama server, ...) without code changes.

Speed: every call sends a low `reasoning_effort` (thinking models are otherwise slow), uses few
retries, and logs its duration and token use, so slow steps can be found in the server log.
"""

import json
import logging
import time
from functools import lru_cache
from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("uvicorn.error")

# Learned at runtime, so a provider limitation costs one failed request instead of one per call.
_no_reasoning_effort = False
_no_json_schema: set[str] = set()  # models that rejected JSON-schema structured output


class LLMRefusal(Exception):
    """The model declined the request."""


@lru_cache
def get_client() -> openai.OpenAI:
    s = get_settings()
    return openai.OpenAI(
        base_url=s.llm_base_url, api_key=s.llm_api_key, max_retries=s.llm_max_retries, timeout=s.llm_timeout_seconds
    )


def _extra() -> dict:
    effort = get_settings().llm_reasoning_effort
    return {} if _no_reasoning_effort or not effort else {"reasoning_effort": effort}


def _mentions_reasoning(e: openai.BadRequestError) -> bool:
    return "reasoning" in str(e).lower()


def create(call, **kwargs):
    """Run `call` (e.g. client.chat.completions.create) with the speed settings.

    If the provider rejects `reasoning_effort`, it is dropped for the rest of the process.
    """
    global _no_reasoning_effort
    try:
        return call(**kwargs, **_extra())
    except openai.BadRequestError as e:
        if _extra() and _mentions_reasoning(e):
            log.warning("provider rejected reasoning_effort; continuing without it")
            _no_reasoning_effort = True
            return call(**kwargs)
        raise


def _log_usage(task: str, model: str, started: float, completion) -> None:
    usage = getattr(completion, "usage", None)
    log.info(
        "llm %s model=%s %.1fs in=%s out=%s",
        task, model, time.monotonic() - started,
        getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"),
    )


def structured(
    output_format: type[T],
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 8000,
) -> T:
    """One request whose response is parsed into `output_format`.

    Uses JSON-schema structured output when the provider supports it; otherwise falls back to plain
    JSON mode with the schema in the prompt, and validates the result with Pydantic either way.
    """
    model = model or get_settings().model_main
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    client = get_client()
    task = output_format.__name__
    started = time.monotonic()

    if model not in _no_json_schema:
        try:
            completion = create(
                client.chat.completions.parse,
                model=model, messages=messages, response_format=output_format, max_tokens=max_tokens,
            )
            _log_usage(task, model, started, completion)
            message = completion.choices[0].message
            if message.refusal:
                raise LLMRefusal(message.refusal)
            if message.parsed is not None:
                return message.parsed
        except openai.BadRequestError:
            _no_json_schema.add(model)  # provider doesn't accept this schema; use JSON mode from now on
        except (ValidationError, openai.LengthFinishReasonError):
            pass  # output didn't fit the schema this time; try JSON mode once

    schema = json.dumps(output_format.model_json_schema())
    completion = create(
        client.chat.completions.create,
        model=model,
        messages=[
            messages[0],
            {"role": "user", "content": f"{user}\n\nRespond with only a JSON object matching this JSON schema:\n{schema}"},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    _log_usage(task + " (json mode)", model, started, completion)
    content = completion.choices[0].message.content or ""
    try:
        return output_format.model_validate_json(content)
    except ValidationError as e:
        raise RuntimeError(f"Model returned invalid JSON for {output_format.__name__}: {e}") from e
