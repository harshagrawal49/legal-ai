"""Turns the user's plain-language description (and answers to follow-up questions) into a fact sheet."""

import json

from app.llm import prompts
from app.llm.client import structured
from app.llm.schemas import IntakeResult
from app.models import Case


def _transcript(case: Case) -> str:
    lines = []
    for item in case.intake_inputs:
        speaker = "User" if item["role"] == "user" else "Assistant (follow-up questions)"
        lines.append(f"{speaker}:\n{item['text']}")
    return "\n\n".join(lines)


def run_intake(case: Case) -> IntakeResult:
    """Re-derive the fact sheet from the full intake conversation and update the case in place."""
    user_prompt = f"<intake_conversation>\n{_transcript(case)}\n</intake_conversation>"
    if case.fact_sheet:
        # Keep any corrections the user made to the previous version.
        user_prompt += (
            "\n\n<current_fact_sheet>\n"
            f"{json.dumps(case.fact_sheet, ensure_ascii=False, indent=1)}\n"
            "</current_fact_sheet>\nUpdate this fact sheet with the new information."
        )

    result = structured(IntakeResult, prompts.INTAKE_SYSTEM, user_prompt)

    case.title = result.case_title
    case.fact_sheet = result.fact_sheet.model_dump()
    if result.questions:
        case.intake_inputs = [*case.intake_inputs, {"role": "assistant", "text": "\n".join(result.questions)}]
    return result
