# backend/tests/test_report_models.py
import pytest
from backend.app.models.report_models import (
    InsightForgeResult, AgentArc, TopicWindow, TopicEvolutionResult
)

def test_insight_forge_result_is_frozen():
    r = InsightForgeResult(
        query="test", sub_queries=("a", "b"),
        facts=("fact1",), quotable_excerpts=("quote1",), source_agents=("agent1",)
    )
    with pytest.raises(Exception):
        r.query = "changed"  # type: ignore

def test_agent_arc_is_frozen():
    arc = AgentArc(
        agent_id="a1", agent_type="Student", name="陳同學",
        arc_summary="從憤怒到理性", key_turning_round=8,
        stance_shift="情緒宣泄 → 制度追問",
        sentiment_trajectory=(0.2, 0.4, 0.6),
    )
    assert arc.key_turning_round == 8
    with pytest.raises(Exception):
        arc.name = "changed"  # type: ignore

def test_topic_window_tuples():
    w = TopicWindow(
        rounds="1-5",
        dominant_topics=("個案事實", "當事人行為"),
        emerging=(),
        fading=(),
    )
    assert isinstance(w.dominant_topics, tuple)

def test_topic_evolution_result_inflection_nullable():
    result = TopicEvolutionResult(
        windows=(),
        migration_path="A → B",
        inflection_round=None,
    )
    assert result.inflection_round is None
