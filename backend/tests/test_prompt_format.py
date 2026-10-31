"""LLM output is read on a phone: the chat prompt asks for phone-friendly Markdown (no tables), and the
structured prompts whose text fields are shown directly ask for plain sentences."""

from app.llm import prompts


def test_chat_prompt_asks_for_phone_friendly_markdown():
    assert prompts.CHAT_FORMAT_RULES in prompts.ADVISOR_SYSTEM
    assert "Do not use tables" in prompts.CHAT_FORMAT_RULES
    # The safety rules still come last, after the formatting guidance.
    assert prompts.ADVISOR_SYSTEM.endswith(prompts.SAFETY_RULES)


def test_structured_prompts_ask_for_plain_text_fields():
    for name in ["SEARCH_ANALYSIS_SYSTEM", "DOCUMENT_UNDERSTANDING_SYSTEM", "BRIEF_SUGGESTIONS_SYSTEM"]:
        assert prompts.PLAIN_FIELD_RULES in getattr(prompts, name), name
