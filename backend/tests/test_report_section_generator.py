# backend/tests/test_report_section_generator.py


def test_section_generator_counts_tool_calls():
    """Tool call counter increments correctly."""
    from backend.app.services.report_section_generator import _count_tool_calls
    text = '<tool_call>{"name": "a"}</tool_call>\n<tool_call>{"name": "b"}</tool_call>'
    assert _count_tool_calls(text) == 2


def test_section_generator_counts_zero():
    from backend.app.services.report_section_generator import _count_tool_calls
    assert _count_tool_calls("no tool calls here") == 0


def test_section_generator_detects_final_answer():
    from backend.app.services.report_section_generator import _has_final_answer
    assert _has_final_answer("Final Answer: Here is the content.")
    assert not _has_final_answer("Still thinking.")


def test_section_generator_extracts_final_answer():
    from backend.app.services.report_section_generator import _extract_final_answer
    text = "Final Answer: This is the section content.\nWith multiple lines."
    result = _extract_final_answer(text)
    assert result == "This is the section content.\nWith multiple lines."


def test_section_generator_extracts_tool_name():
    from backend.app.services.report_section_generator import _extract_tool_calls
    text = '<tool_call>{"name": "insight_forge", "parameters": {"query": "test"}}</tool_call>'
    calls = _extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "insight_forge"


def test_section_generator_handles_malformed_tool_call():
    from backend.app.services.report_section_generator import _extract_tool_calls
    text = '<tool_call>not valid json</tool_call>'
    calls = _extract_tool_calls(text)
    assert calls == []
