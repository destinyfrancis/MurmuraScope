"""Tests for NarrativeEngine and narrative models."""
import pytest
from unittest.mock import AsyncMock

from backend.app.services.narrative_engine import NarrativeEngine
from backend.app.models.narrative import TrendNarrative, TrendBlock


MOCK_NARRATIVE_RESPONSE = {
    "executive_summary": "未來6個月樓價大概率下跌，主要由加息壓力及移民潮驅動。",
    "trends": [
        {
            "title": "郊區住宅承壓",
            "direction": "down",
            "confidence": "high",
            "narrative": "模擬顯示35-50歲家庭客群對加息最敏感，傾向暫緩置業決定。",
            "evidence": ["73% agents 傾向觀望", "28% agents 已降低置業預算"],
            "counter_signals": ["12% agents 認為政府可能補貼"],
        },
        {
            "title": "商業地產穩定",
            "direction": "stable",
            "confidence": "medium",
            "narrative": "企業客戶對加息反應滯後，短期租賃需求維持穩定。",
            "evidence": ["商業租賃指數持平"],
            "counter_signals": ["部分跨國企業縮減辦公室面積"],
        },
    ],
    "deep_dive_summary": "詳細分析顯示，政治立場偏民主派嘅代理人對移民決策更敏感。",
    "methodology_note": "基於500名LLM驅動嘅模擬市民，30輪次模擬，OpenRouter DeepSeek V3.2。",
}


@pytest.mark.asyncio
async def test_generate_narrative():
    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(return_value=MOCK_NARRATIVE_RESPONSE)

    engine = NarrativeEngine(llm_client=mock_llm)
    result = await engine.generate(
        report_artifacts={"summary": "test", "trends": []},
        confidence_score=0.78,
        confidence_level="high",
    )

    assert isinstance(result, TrendNarrative)
    assert "下跌" in result.executive_summary
    assert len(result.trends) >= 1
    assert result.trends[0].direction == "down"


@pytest.mark.asyncio
async def test_generate_narrative_multiple_trends():
    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(return_value=MOCK_NARRATIVE_RESPONSE)

    engine = NarrativeEngine(llm_client=mock_llm)
    result = await engine.generate(
        report_artifacts={"summary": "multi-trend test"},
        confidence_score=0.6,
        confidence_level="medium",
    )

    assert len(result.trends) == 2
    assert result.trends[1].direction == "stable"
    assert result.trends[1].confidence == "medium"


@pytest.mark.asyncio
async def test_generate_metadata_populated():
    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(return_value=MOCK_NARRATIVE_RESPONSE)

    engine = NarrativeEngine(llm_client=mock_llm)
    result = await engine.generate(report_artifacts={})

    assert result.generated_at is not None
    assert result.methodology_note is not None
    assert "DeepSeek" in result.methodology_note


@pytest.mark.asyncio
async def test_generate_llm_failure_returns_empty():
    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM error"))

    engine = NarrativeEngine(llm_client=mock_llm)
    result = await engine.generate(report_artifacts={"data": "test"})

    assert isinstance(result, TrendNarrative)
    assert result.executive_summary == ""
    assert result.trends == []


@pytest.mark.asyncio
async def test_generate_no_llm_raises():
    engine = NarrativeEngine(llm_client=None)
    with pytest.raises(RuntimeError, match="requires an LLM client"):
        await engine.generate(report_artifacts={})


def test_trend_block_is_frozen():
    block = TrendBlock(
        title="test",
        direction="up",
        confidence="high",
        narrative="test narrative",
    )
    with pytest.raises(Exception):
        block.direction = "down"  # type: ignore[misc]


def test_trend_narrative_is_frozen():
    narrative = TrendNarrative(
        executive_summary="summary",
        trends=[],
    )
    with pytest.raises(Exception):
        narrative.executive_summary = "changed"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_generate_handles_malformed_trend_gracefully():
    """A malformed trend block should be skipped, not crash the engine."""
    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(return_value={
        "executive_summary": "test",
        "trends": [
            {"title": "valid", "direction": "up", "confidence": "high", "narrative": "ok"},
            {"bad_field": "no direction"},  # malformed — missing required fields
        ],
    })

    engine = NarrativeEngine(llm_client=mock_llm)
    result = await engine.generate(report_artifacts={})

    # Only the valid trend should survive
    assert len(result.trends) == 1
    assert result.trends[0].direction == "up"
