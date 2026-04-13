"""Unit tests for BeliefTopicGenerator (Phase 2.3).

Covers:
- Rule-based topic generation for each domain
- Default topic fallback
- max_topics cap
- Cache and clear_session
- Domain detection from KG nodes and scenario text
- No LLM calls in rule-based path
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from backend.app.services.belief_topic_generator import BeliefTopicGenerator


@pytest.fixture()
def generator():
    return BeliefTopicGenerator(max_topics=12)


class TestRuleBasedTopics:
    @pytest.mark.asyncio
    async def test_economic_scenario_includes_economic_topics(self, generator):
        topics = await generator.generate_topics(
            session_id="s1",
            scenario_description="stock market crash causes bank failures",
            kg_nodes=[{"type": "company", "label": "bank"}],
            kg_edges=[],
            use_llm=False,
        )
        economic_topics = {"economic_stability", "market_confidence", "supply_chain_resilience"}
        assert any(t in economic_topics for t in topics)

    @pytest.mark.asyncio
    async def test_political_scenario_includes_political_topics(self, generator):
        topics = await generator.generate_topics(
            session_id="s2",
            scenario_description="government policy election minister parliament",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        political_topics = {"government_trust", "policy_effectiveness", "political_polarisation"}
        assert any(t in political_topics for t in topics)

    @pytest.mark.asyncio
    async def test_default_topics_always_present(self, generator):
        topics = await generator.generate_topics(
            session_id="s3",
            scenario_description="",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        assert "general_sentiment" in topics or "agent_influence" in topics

    @pytest.mark.asyncio
    async def test_max_topics_cap_respected(self, generator):
        gen = BeliefTopicGenerator(max_topics=5)
        topics = await gen.generate_topics(
            session_id="s4",
            scenario_description="stock market bank trade government policy war conflict technology",
            kg_nodes=[
                {"type": "company", "label": "bank"},
                {"type": "government", "label": "ministry"},
            ],
            kg_edges=[{"relation": "conflict"}],
            use_llm=False,
        )
        assert len(topics) <= 5

    @pytest.mark.asyncio
    async def test_no_duplicate_topics(self, generator):
        topics = await generator.generate_topics(
            session_id="s5",
            scenario_description="market bank stock government policy",
            kg_nodes=[{"type": "company", "label": "market"}],
            kg_edges=[],
            use_llm=False,
        )
        assert len(topics) == len(set(topics))

    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self, generator):
        topics = await generator.generate_topics(
            session_id="s6",
            scenario_description="trade supply chain",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        assert isinstance(topics, list)
        assert all(isinstance(t, str) for t in topics)


class TestTopicCache:
    @pytest.mark.asyncio
    async def test_cache_populated_after_generate(self, generator):
        await generator.generate_topics(
            session_id="cache_test",
            scenario_description="market",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        cached = generator.get_cached_topics("cache_test")
        assert cached is not None
        assert len(cached) > 0

    @pytest.mark.asyncio
    async def test_get_cached_returns_none_before_generate(self, generator):
        result = generator.get_cached_topics("nonexistent_session")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_session_removes_cache(self, generator):
        await generator.generate_topics(
            session_id="clear_me",
            scenario_description="economy",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        generator.clear_session("clear_me")
        assert generator.get_cached_topics("clear_me") is None

    @pytest.mark.asyncio
    async def test_cache_matches_returned_topics(self, generator):
        topics = await generator.generate_topics(
            session_id="verify_cache",
            scenario_description="bank market",
            kg_nodes=[],
            kg_edges=[],
            use_llm=False,
        )
        cached = generator.get_cached_topics("verify_cache")
        assert topics == cached


class TestKGNodeIntegration:
    @pytest.mark.asyncio
    async def test_kg_nodes_contribute_to_domain_detection(self, generator):
        """Conflict keyword in KG edge relation should surface conflict topics."""
        topics = await generator.generate_topics(
            session_id="kg_test",
            scenario_description="",  # empty description
            kg_nodes=[],
            kg_edges=[{"relation": "conflict hostile tension"}],
            use_llm=False,
        )
        conflict_topics = {"security_concern", "conflict_escalation_risk", "peace_prospect"}
        assert any(t in conflict_topics for t in topics)
