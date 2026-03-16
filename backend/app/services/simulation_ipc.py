"""Inter-process communication for agent interviews during/after simulation.

Provides the ability to interview individual agents about their decisions,
using their persona profile, action history, and an LLM to generate
contextual responses.
"""

from __future__ import annotations

import json
from typing import Any

from backend.app.config import get_settings
from backend.app.services.simulation_runner import SimulationRunner
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_ipc")

_INTERVIEW_SYSTEM_PROMPT = """You are role-playing as a Hong Kong resident in a social simulation.
You must stay in character based on the profile and action history provided.
Answer the interviewer's question from your character's perspective.
Be specific about your reasoning, referencing your demographic background,
personal circumstances, and the actions you took during the simulation.
Respond in the language the question is asked in (English or Chinese)."""

_REASONING_SYSTEM_PROMPT = """You are an analyst reviewing a simulated Hong Kong resident's actions.
Based on their profile and action history, provide a concise summary of their
decision-making patterns, key motivations, and notable behavioural shifts.
Write in clear, analytical language."""


class SimulationIPC:
    """Allows interviewing agents during/after simulation."""

    def __init__(self, runner: SimulationRunner | None = None) -> None:
        self._runner = runner or SimulationRunner()

    async def interview_agent(
        self,
        session_id: str,
        agent_id: int,
        question: str,
    ) -> str:
        """Ask a specific agent a question about their decisions.

        Constructs a prompt from the agent's persona profile and their
        action history, then uses the LLM to generate an in-character
        response.

        Args:
            session_id: UUID of the simulation session.
            agent_id: Numeric ID of the agent to interview.
            question: The interview question.

        Returns:
            The agent's in-character response string.

        Raises:
            ValueError: If agent not found in the session.
        """
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")

        profile = await self._load_agent_profile(session_id, agent_id)
        history = await self.get_agent_history(session_id, agent_id)

        prompt = _build_interview_prompt(profile, history, question)
        response = await _call_llm(prompt, _INTERVIEW_SYSTEM_PROMPT)

        logger.info(
            "Interview agent %d in session %s: Q=%s",
            agent_id,
            session_id,
            question[:80],
        )
        return response

    async def get_agent_history(
        self,
        session_id: str,
        agent_id: int,
    ) -> list[dict[str, Any]]:
        """Get an agent's action history from the OASIS output database.

        Reads from the OASIS DB (oasis.db) action_logs table stored per session.

        Args:
            session_id: UUID of the simulation session.
            agent_id: Numeric ID of the agent.

        Returns:
            List of action dicts ordered by round number.
        """
        try:
            all_logs = await self._runner.get_action_logs(session_id)
            return [r for r in all_logs if r.get("agent_id") == agent_id]
        except Exception:
            logger.warning(
                "Could not load action history for agent %d session %s",
                agent_id,
                session_id,
            )
            return []

    async def get_agent_reasoning(
        self,
        session_id: str,
        agent_id: int,
    ) -> str:
        """Get agent's decision reasoning summary.

        Uses the agent's profile and full action history to generate
        an analytical summary of their decision-making patterns.

        Args:
            session_id: UUID of the simulation session.
            agent_id: Numeric ID of the agent.

        Returns:
            Analytical summary string of the agent's reasoning patterns.
        """
        profile = await self._load_agent_profile(session_id, agent_id)
        history = await self.get_agent_history(session_id, agent_id)

        if not history:
            return "No actions recorded for this agent."

        prompt = _build_reasoning_prompt(profile, history)
        summary = await _call_llm(prompt, _REASONING_SYSTEM_PROMPT)

        logger.info(
            "Generated reasoning summary for agent %d in session %s",
            agent_id,
            session_id,
        )
        return summary

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    async def _load_agent_profile(
        self, session_id: str, agent_id: int
    ) -> dict[str, Any]:
        """Load agent profile from agent_profiles table.

        Raises:
            ValueError: If agent not found.
        """
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT * FROM agent_profiles
                   WHERE session_id = ? AND id = ?""",
                (session_id, agent_id),
            )
            row = await cursor.fetchone()

        if row is None:
            raise ValueError(
                f"Agent {agent_id} not found in session {session_id}"
            )

        return {
            "id": row["id"],
            "agent_type": row["agent_type"],
            "age": row["age"],
            "sex": row["sex"],
            "district": row["district"],
            "occupation": row["occupation"],
            "income_bracket": row["income_bracket"],
            "housing_type": row["housing_type"],
            "oasis_persona": row["oasis_persona"],
            "oasis_username": row["oasis_username"],
        }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_interview_prompt(
    profile: dict[str, Any],
    history: list[dict[str, Any]],
    question: str,
) -> str:
    """Build the interview prompt combining profile, history, and question."""
    profile_text = _format_profile(profile)
    history_text = _format_history(history)

    return (
        f"## Your Profile\n{profile_text}\n\n"
        f"## Your Actions During the Simulation\n{history_text}\n\n"
        f"## Interview Question\n{question}"
    )


def _build_reasoning_prompt(
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    """Build the reasoning analysis prompt."""
    profile_text = _format_profile(profile)
    history_text = _format_history(history)

    return (
        f"## Agent Profile\n{profile_text}\n\n"
        f"## Action History ({len(history)} actions)\n{history_text}\n\n"
        "## Task\n"
        "Analyse this agent's decision-making patterns. Cover:\n"
        "1. Key motivations and driving factors\n"
        "2. Notable behavioural shifts across rounds\n"
        "3. How their demographics influenced decisions\n"
        "4. Overall sentiment trajectory"
    )


def _format_profile(profile: dict[str, Any]) -> str:
    """Format agent profile dict as readable text."""
    lines = []
    for key, value in profile.items():
        if key == "personality" and isinstance(value, dict):
            lines.append(f"- Personality: {json.dumps(value)}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _format_history(history: list[dict[str, Any]]) -> str:
    """Format action history as readable text."""
    if not history:
        return "No actions recorded."

    lines = []
    for action in history:
        round_num = action.get("round", "?")
        action_type = action.get("action_type", "unknown")
        content = action.get("content", "")
        lines.append(f"Round {round_num} [{action_type}]: {content}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_llm(prompt: str, system_prompt: str) -> str:
    """Call the configured LLM for agent interview/reasoning.

    Uses DeepSeek by default for cost efficiency. Falls back to
    a placeholder if no API key is configured.

    Args:
        prompt: User prompt content.
        system_prompt: System prompt for role/context.

    Returns:
        LLM response text.
    """
    settings = get_settings()

    if settings.DEEPSEEK_API_KEY:
        return await _call_deepseek(prompt, system_prompt, settings.DEEPSEEK_API_KEY)

    logger.warning(
        "No LLM API key configured for IPC. "
        "Set DEEPSEEK_API_KEY in .env for agent interviews."
    )
    return "[LLM not configured] Unable to generate response."


async def _call_deepseek(
    prompt: str, system_prompt: str, api_key: str
) -> str:
    """Call DeepSeek Chat API."""
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1024,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("DeepSeek returned no choices")

    return choices[0]["message"]["content"]
