# backend/tests/test_report_orchestrator.py
import pytest
from unittest.mock import AsyncMock, patch


def test_report_generate_request_has_scenario_question():
    from backend.app.models.request import ReportGenerateRequest
    req = ReportGenerateRequest(session_id="s1")
    assert req.scenario_question is None  # optional with default None


def test_report_generate_request_accepts_scenario_question():
    from backend.app.models.request import ReportGenerateRequest
    req = ReportGenerateRequest(
        session_id="s1",
        scenario_question="如果X發生，輿情會怎樣？"
    )
    assert req.scenario_question == "如果X發生，輿情會怎樣？"


def test_orchestrator_outline_parses_chapters():
    """ReportOrchestrator._parse_outline extracts chapters list."""
    from backend.app.services.report_orchestrator import ReportOrchestrator
    orch = ReportOrchestrator.__new__(ReportOrchestrator)
    raw = '{"chapters": [{"title": "輿情遷移", "thesis": "議題將升級", "suggested_tools": ["insight_forge"]}]}'
    chapters = orch._parse_outline(raw)
    assert len(chapters) == 1
    assert chapters[0]["title"] == "輿情遷移"


def test_orchestrator_outline_handles_malformed_json():
    from backend.app.services.report_orchestrator import ReportOrchestrator
    orch = ReportOrchestrator.__new__(ReportOrchestrator)
    # Should not raise — returns empty list or fallback
    result = orch._parse_outline("not json at all")
    assert isinstance(result, list)


def test_orchestrator_outline_handles_missing_chapters_key():
    from backend.app.services.report_orchestrator import ReportOrchestrator
    orch = ReportOrchestrator.__new__(ReportOrchestrator)
    result = orch._parse_outline('{"something_else": []}')
    assert result == []
