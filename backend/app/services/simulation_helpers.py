"""Standalone helper functions for the simulation runner.

Pure utility functions with no ``self`` dependency, extracted from
simulation_runner.py to keep that file within the 800-line target.
"""

from __future__ import annotations

import contextlib
import json
import os
import time as _time
from pathlib import Path
from typing import Any

from backend.app.utils.logger import get_logger
from backend.app.utils.telemetry import get_tracer as _get_tracer

_sim_tracer = _get_tracer("simulation")
logger = get_logger("simulation_runner")

# Paths computed relative to this file's location — portable across deployments.
# This file lives at: backend/app/services/simulation_helpers.py
# Project root is 4 levels up: services → app → backend → project_root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@contextlib.contextmanager
def _timed_block(hook_name: str, session_id: str, round_num: int = 0):
    """Context manager that logs execution time of a simulation hook at DEBUG level."""
    t0 = _time.monotonic()
    with _sim_tracer.start_as_current_span(f"hook.{hook_name}"):
        try:
            yield
        finally:
            ms = round((_time.monotonic() - t0) * 1000)
            logger.debug(
                "hook=%s session=%s round=%d duration=%dms",
                hook_name,
                session_id[:8],
                round_num,
                ms,
            )


def _require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(
            f"{label} not found at {path}. Check that the .venv311 virtual environment is set up correctly."
        )


def _build_full_config(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Merge simulation config with LLM settings (excluding API key).

    Adds:
    - llm_provider  (default: fireworks)
    - llm_model     (default: deepseek/deepseek-v3.2)
    - llm_base_url  (Fireworks AI endpoint)
    - oasis_db_path (stable per-session path)

    Note: llm_api_key is intentionally excluded from the written config file
    to prevent credentials being stored on disk. Pass it via subprocess env.
    """
    session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
    oasis_db_path = str(session_dir / "oasis.db")

    provider = config.get("llm_provider", "openrouter")
    model = config.get("llm_model", "deepseek/deepseek-v3.2")
    base_url = config.get("llm_base_url", "https://openrouter.ai/api/v1")

    # Strip llm_api_key so it is never written to sim_config.json
    safe_config = {k: v for k, v in config.items() if k != "llm_api_key"}

    return {
        **safe_config,
        "session_id": session_id,
        "llm_provider": provider,
        "llm_model": model,
        "llm_base_url": base_url,
        "oasis_db_path": oasis_db_path,
    }


def _get_api_key() -> str:
    """Read OpenRouter API key from settings or OS env."""
    try:
        from backend.app.config import get_settings as _get_settings  # noqa: PLC0415

        key = getattr(_get_settings(), "OPENROUTER_API_KEY", "") or ""
    except Exception:
        key = ""
    if not key:
        key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        logger.warning("OPENROUTER_API_KEY is not set — simulation will fail at LLM call")
    return key


def _try_parse_jsonl(line: str) -> dict[str, Any] | None:
    """Parse *line* as JSON; return None on failure."""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_faction_peer_stance(
    faction_id: str,
    agent_id: str,
    agent_beliefs: dict[str, dict[str, float]],
    agent_factions: dict[str, str],
) -> dict[str, float]:
    """Return average belief values of other agents in the same faction.

    Used by BeliefPropagationEngine to compute conformity peer pressure.
    Returns an empty dict if the faction has no other members.
    """
    if not faction_id:
        return {}
    peer_beliefs = [b for aid, b in agent_beliefs.items() if aid != agent_id and agent_factions.get(aid) == faction_id]
    if not peer_beliefs:
        return {}
    all_metrics = {m for b in peer_beliefs for m in b}
    return {m: sum(b.get(m, 0.5) for b in peer_beliefs) / len(peer_beliefs) for m in all_metrics}


def _build_key_relationships(
    agent_id: str,
    rel_states: dict,
    stakeholder_agents_by_id: dict[str, dict] | None = None,
) -> list[dict]:
    """Extract top-5 key relationships for agent_id from relationship_states dict.

    Args:
        agent_id: The agent whose perspective we use.
        rel_states: Dict keyed by (agent_a_id, agent_b_id) → RelationshipState.
        stakeholder_agents_by_id: Optional map of agent_id → agent profile dict.
            When provided, high-intimacy peers (>0.6) reveal their goals and
            faction — implementing Sotopia-style relationship-depth disclosure.

    Returns:
        List of relationship dicts suitable for CognitiveAgentEngine context.
    """
    from backend.app.models.relationship_state import RelationshipState  # noqa: PLC0415

    relationships: list[dict] = []
    for (aid, bid), state in rel_states.items():
        if aid != agent_id:
            continue
        if not isinstance(state, RelationshipState):
            continue
        entry: dict = {
            "other_id": bid,
            "rel_type": _infer_rel_type(state),
            "intimacy": state.intimacy,
            "trust": state.trust,
            "commitment": state.commitment,
            "passion": state.passion,
        }
        # Relationship-depth disclosure: high-intimacy peers share goals + faction
        if state.intimacy > 0.6 and stakeholder_agents_by_id:
            peer = stakeholder_agents_by_id.get(bid)
            if peer:
                peer_goals = peer.get("goals", [])
                peer_faction = peer.get("faction", "")
                if peer_goals:
                    entry["peer_goals"] = list(peer_goals)
                if peer_faction:
                    entry["peer_faction"] = peer_faction
        relationships.append(entry)
    # Sort by intimacy + |trust| (most salient relationships first)
    relationships.sort(
        key=lambda r: r["intimacy"] + abs(r["trust"]),
        reverse=True,
    )
    return relationships[:5]


def _infer_rel_type(state: Any) -> str:
    """Heuristically label relationship type from state dimensions."""
    if state.passion > 0.4 and state.intimacy > 0.3:
        return "romantic"
    if state.trust < -0.3:
        return "adversarial"
    if state.commitment > 0.6:
        return "committed"
    if state.intimacy > 0.3:
        return "close"
    return "associate"
