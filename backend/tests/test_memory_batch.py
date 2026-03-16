"""Tests for batch memory salience evaluation."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_batch_memory_processing():
    from backend.app.services.agent_memory import AgentMemoryService

    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(
        return_value={
            "salience_scores": [0.8, 0.6, 0.4, 0.7, 0.5, 0.3, 0.9, 0.2, 0.6, 0.5]
        }
    )

    svc = AgentMemoryService(llm_client=mock_llm)
    agent_memories = [
        {"agent_id": f"a{i}", "memory_text": f"Memory {i}", "round": 5}
        for i in range(10)
    ]
    scores = await svc.batch_evaluate_salience(agent_memories)

    assert len(scores) == 10
    assert mock_llm.chat_json.call_count == 1


@pytest.mark.asyncio
async def test_batch_memory_multiple_batches():
    from backend.app.services.agent_memory import AgentMemoryService

    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(return_value={"salience_scores": [0.5] * 10})

    svc = AgentMemoryService(llm_client=mock_llm)
    agent_memories = [
        {"agent_id": f"a{i}", "memory_text": f"Memory {i}", "round": 5}
        for i in range(25)
    ]
    scores = await svc.batch_evaluate_salience(agent_memories)

    assert len(scores) == 25
    assert mock_llm.chat_json.call_count == 3  # 10 + 10 + 5


@pytest.mark.asyncio
async def test_batch_memory_clamps_scores():
    """Scores outside [0, 1] should be clamped."""
    from backend.app.services.agent_memory import AgentMemoryService

    mock_llm = AsyncMock()
    # Return out-of-range values
    mock_llm.chat_json = AsyncMock(
        return_value={"salience_scores": [-0.5, 1.5, 0.7]}
    )

    svc = AgentMemoryService(llm_client=mock_llm)
    agent_memories = [
        {"agent_id": f"a{i}", "memory_text": f"Memory {i}", "round": 1}
        for i in range(3)
    ]
    scores = await svc.batch_evaluate_salience(agent_memories, batch_size=10)

    assert scores[0] == 0.0
    assert scores[1] == 1.0
    assert abs(scores[2] - 0.7) < 1e-6


@pytest.mark.asyncio
async def test_batch_memory_llm_error_fallback():
    """If LLM fails, all scores in that batch default to 0.5."""
    from backend.app.services.agent_memory import AgentMemoryService

    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    svc = AgentMemoryService(llm_client=mock_llm)
    agent_memories = [
        {"agent_id": f"a{i}", "memory_text": f"Memory {i}", "round": 1}
        for i in range(5)
    ]
    scores = await svc.batch_evaluate_salience(agent_memories)

    assert len(scores) == 5
    assert all(s == 0.5 for s in scores)


@pytest.mark.asyncio
async def test_batch_memory_partial_scores():
    """If LLM returns fewer scores than batch size, remainder defaults to 0.5."""
    from backend.app.services.agent_memory import AgentMemoryService

    mock_llm = AsyncMock()
    mock_llm.chat_json = AsyncMock(
        return_value={"salience_scores": [0.9, 0.8]}  # Only 2 of 5
    )

    svc = AgentMemoryService(llm_client=mock_llm)
    agent_memories = [
        {"agent_id": f"a{i}", "memory_text": f"Memory {i}", "round": 1}
        for i in range(5)
    ]
    scores = await svc.batch_evaluate_salience(agent_memories, batch_size=10)

    assert len(scores) == 5
    assert scores[0] == 0.9
    assert scores[1] == 0.8
    assert scores[2] == 0.5  # fallback
    assert scores[3] == 0.5
    assert scores[4] == 0.5
