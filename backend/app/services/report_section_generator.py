"""Per-section ReACT loop for report generation.

Each section gets its own focused evidence-collection loop with
enforced minimum tool calls (3) and maximum (5).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Awaitable

from backend.app.utils.logger import get_logger

logger = get_logger("report_section_generator")

_MIN_TOOL_CALLS = 3
_MAX_TOOL_CALLS = 5
_MAX_ITERATIONS = 8


def _count_tool_calls(text: str) -> int:
    return len(re.findall(r"<tool_call>", text))


def _has_final_answer(text: str) -> bool:
    return "Final Answer:" in text


def _extract_final_answer(text: str) -> str:
    idx = text.find("Final Answer:")
    if idx == -1:
        return text
    return text[idx + len("Final Answer:"):].strip()


def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
    calls = []
    for match in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        try:
            calls.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool call: %s", match.group(1)[:100])
    return calls


async def generate_section(
    *,
    system_prompt: str,
    section_outline: dict[str, Any],
    previous_sections: list[str],
    tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
    llm_caller: Callable[[list[dict]], Awaitable[str]],
    unused_tools: list[str],
) -> str:
    """Run a focused ReACT loop for one report section.

    Args:
        system_prompt: Mode-specific system prompt (kg_driven or hk_demographic).
        section_outline: Dict with 'title', 'thesis', 'suggested_tools'.
        previous_sections: Already-written sections (for context injection).
        tool_handler: Async function (tool_name, params) -> result string.
        llm_caller: Async function (messages list) -> LLM response string.
        unused_tools: Tool names not yet called — used in nudge message.

    Returns:
        Markdown content for this section.
    """
    from backend.prompts.report_prompts import (
        SECTION_INSUFFICIENT_TOOLS_MSG,
        SECTION_FORCE_FINAL_MSG,
    )

    context_block = ""
    if previous_sections:
        context_block = "\n\n已完成章節:\n" + "\n---\n".join(previous_sections[-2:])

    user_content = (
        f"章節標題：{section_outline['title']}\n"
        f"核心論點：{section_outline.get('thesis', '')}\n"
        f"建議工具：{', '.join(section_outline.get('suggested_tools', []))}"
        f"{context_block}"
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    total_tool_calls = 0
    iteration = 0

    while iteration < _MAX_ITERATIONS:
        iteration += 1
        response = await llm_caller(messages)
        messages.append({"role": "assistant", "content": response})

        # Execute any tool calls in this response
        tool_calls_in_response = _extract_tool_calls(response)
        for tc in tool_calls_in_response:
            total_tool_calls += 1
            try:
                observation = await tool_handler(tc["name"], tc.get("parameters", {}))
            except Exception as e:
                observation = f"Error executing {tc['name']}: {e}"
            messages.append({"role": "user", "content": f"Observation: {observation}"})

        # Check for final answer
        if _has_final_answer(response):
            if total_tool_calls < _MIN_TOOL_CALLS:
                # Reject — demand more research
                nudge = SECTION_INSUFFICIENT_TOOLS_MSG.format(
                    count=total_tool_calls,
                    unused_tools=", ".join(unused_tools[:3]) or "insight_forge",
                )
                messages.append({"role": "user", "content": nudge})
                continue
            return _extract_final_answer(response)

        # Enforce max tool calls
        if total_tool_calls >= _MAX_TOOL_CALLS:
            messages.append({"role": "user", "content": SECTION_FORCE_FINAL_MSG})

    # Force final answer on timeout
    final = await llm_caller(messages + [{"role": "user", "content": SECTION_FORCE_FINAL_MSG}])
    return _extract_final_answer(final) or final
