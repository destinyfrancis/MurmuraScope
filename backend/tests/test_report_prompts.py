"""Tests for report_prompts.py — Task 6: future-rehearsal framing.

Tests cover:
- PLANNING_SYSTEM_PROMPT (future rehearsal framing)
- build_planning_user_prompt (accepts scenario_question)
- KG_DRIVEN_SECTION_SYSTEM_PROMPT (future tense instruction, min 3 tool calls)
- HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT (macro references, min 3 tool calls)
- SECTION_INSUFFICIENT_TOOLS_MSG
- SECTION_FORCE_FINAL_MSG
"""

from __future__ import annotations


def test_planning_prompt_contains_future_rehearsal_framing():
    from backend.prompts.report_prompts import PLANNING_SYSTEM_PROMPT

    assert "未來的預演" in PLANNING_SYSTEM_PROMPT or "future rehearsal" in PLANNING_SYSTEM_PROMPT.lower()


def test_planning_prompt_accepts_scenario_question():
    from backend.prompts.report_prompts import build_planning_user_prompt

    prompt = build_planning_user_prompt(
        session_id="s1",
        agent_count=100,
        round_count=20,
        scenario_question="如果X發生，Y會怎樣？",
        sim_mode="kg_driven",
    )
    assert "如果X發生，Y會怎樣？" in prompt


def test_kg_driven_section_prompt_exists():
    from backend.prompts.report_prompts import KG_DRIVEN_SECTION_SYSTEM_PROMPT

    assert len(KG_DRIVEN_SECTION_SYSTEM_PROMPT) > 100


def test_kg_driven_section_prompt_uses_future_tense_instruction():
    from backend.prompts.report_prompts import KG_DRIVEN_SECTION_SYSTEM_PROMPT

    assert "未來式" in KG_DRIVEN_SECTION_SYSTEM_PROMPT or "將會" in KG_DRIVEN_SECTION_SYSTEM_PROMPT


def test_hk_demographic_section_prompt_exists():
    from backend.prompts.report_prompts import HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT

    assert len(HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT) > 100


def test_hk_demographic_section_prompt_references_macro():
    from backend.prompts.report_prompts import HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT

    assert "宏觀" in HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT or "macro" in HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT.lower()


def test_section_prompt_enforces_min_tool_calls():
    from backend.prompts.report_prompts import KG_DRIVEN_SECTION_SYSTEM_PROMPT

    assert "至少3次" in KG_DRIVEN_SECTION_SYSTEM_PROMPT or "min 3" in KG_DRIVEN_SECTION_SYSTEM_PROMPT.lower()


def test_section_nudge_message_exists():
    from backend.prompts.report_prompts import SECTION_INSUFFICIENT_TOOLS_MSG

    assert len(SECTION_INSUFFICIENT_TOOLS_MSG) > 20


def test_section_force_final_message_exists():
    from backend.prompts.report_prompts import SECTION_FORCE_FINAL_MSG

    assert len(SECTION_FORCE_FINAL_MSG) > 10
