"""
HKSimEngine OASIS Reddit Simulation Runner

Usage: python run_reddit_simulation.py --config /path/to/config.json

Runs a Reddit-style social media simulation using the OASIS framework.
Outputs JSONL progress updates to stdout for IPC with parent process.

Actions supported: CREATE_POST, UPVOTE, DOWNVOTE, CREATE_COMMENT
Agent input: CSV file with columns username, description, user_char
Reddit uses subreddits instead of hashtags; shock posts are routed to
appropriate HK-themed subreddits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("reddit_simulation")

# ---------------------------------------------------------------------------
# OASIS imports (with graceful fallback)
# ---------------------------------------------------------------------------

try:
    from oasis import oasis
    from oasis.social_agent.agents_generator import generate_agents
    from oasis.social_platform.typing import DefaultPlatformType, ActionType
    from oasis.social_platform.channel import Channel
except ImportError as exc:
    logger.error(
        "OASIS framework not installed. "
        "Install via: pip install oasis-social-sim  "
        "(or ensure the oasis package is on PYTHONPATH). "
        "Original error: %s",
        exc,
    )
    print(
        json.dumps({
            "type": "error",
            "data": {
                "platform": "reddit",
                "message": (
                    "OASIS framework not found. Install it with "
                    "'pip install oasis-social-sim' or add it to PYTHONPATH."
                ),
            },
        }),
        flush=True,
    )
    sys.exit(1)

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
except ImportError as exc:
    logger.error(
        "CAMEL-AI not installed. Install via: pip install camel-ai. "
        "Original error: %s",
        exc,
    )
    print(
        json.dumps({
            "type": "error",
            "data": {
                "platform": "reddit",
                "message": "CAMEL-AI not found. Install with 'pip install camel-ai'.",
            },
        }),
        flush=True,
    )
    sys.exit(1)

# ManualAction import (best-effort; used for shock injection)
try:
    from oasis.environment.env_action import ManualAction, LLMAction  # noqa: F401
    _HAS_MANUAL_ACTION = True
except ImportError:
    _HAS_MANUAL_ACTION = False
    logger.warning(
        "oasis.environment.env_action not found — "
        "shock injection via ManualAction will be skipped."
    )


# ---------------------------------------------------------------------------
# JSONL IPC helpers
# ---------------------------------------------------------------------------

def emit(msg_type: str, data: dict[str, Any]) -> None:
    """Write a JSONL message to stdout."""
    line = json.dumps({"type": msg_type, "data": data}, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def emit_progress(round_num: int, total: int, detail: str = "") -> None:
    emit("progress", {
        "platform": "reddit",
        "round": round_num,
        "total": total,
        "detail": detail,
    })


# ---------------------------------------------------------------------------
# LLM provider mapping
# ---------------------------------------------------------------------------

LLM_PROVIDER_URLS: dict[str, str] = {
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def build_model(config: dict[str, Any]) -> Any:
    """Create a CAMEL ModelFactory model from config."""
    provider = config.get("llm_provider", "openrouter")
    model_name = config.get("llm_model", "deepseek/deepseek-v3.2")
    api_key = config["llm_api_key"]
    base_url = config.get("llm_base_url", LLM_PROVIDER_URLS.get(provider, ""))

    if not api_key:
        raise ValueError("llm_api_key is required")
    if not base_url:
        raise ValueError(
            f"No base URL for provider '{provider}'. "
            "Set llm_base_url in config."
        )

    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=model_name,
        url=base_url,
        model_config_dict={"temperature": 0.7, "max_tokens": 4096},
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Default subreddits for HK simulation
# ---------------------------------------------------------------------------

DEFAULT_SUBREDDITS: list[dict[str, str]] = [
    {"name": "HongKong", "description": "General Hong Kong discussion"},
    {"name": "HKProperty", "description": "Hong Kong property market discussion"},
    {"name": "HKFinance", "description": "Hong Kong finance and investment"},
    {"name": "HKPolitics", "description": "Hong Kong politics and policy"},
    {"name": "HKLife", "description": "Daily life in Hong Kong"},
    {"name": "HKJobs", "description": "Hong Kong employment and careers"},
    {"name": "HKEmigration", "description": "Emigration from Hong Kong"},
]

# Map shock types to HK subreddits
_SHOCK_SUBREDDIT_MAP: dict[str, str] = {
    "interest_rate_hike": "HKFinance",
    "property_crash": "HKProperty",
    "unemployment_spike": "HKJobs",
    "policy_change": "HKPolitics",
    "market_rally": "HKFinance",
    "emigration_wave": "HKEmigration",
}


# ---------------------------------------------------------------------------
# Shock injection
# ---------------------------------------------------------------------------

def get_shocks_for_round(
    shocks: list[dict[str, Any]], round_num: int
) -> list[dict[str, Any]]:
    """Return shocks scheduled for the given round number."""
    return [s for s in shocks if s.get("round_number") == round_num]


async def inject_shock(env: Any, shock: dict[str, Any]) -> None:
    """Inject a macro shock into the environment via ManualAction CREATE_POST.

    For Reddit, shocks are posted to the most relevant HK subreddit.
    """
    post_content = shock.get("post_content", "")
    if not post_content:
        logger.warning(
            "Shock at round %d has no post_content, skipping",
            shock.get("round_number"),
        )
        return

    if not _HAS_MANUAL_ACTION:
        logger.warning(
            "ManualAction not available — shock '%s' at round %d skipped",
            shock.get("shock_type", "unknown"),
            shock.get("round_number", -1),
        )
        return

    subreddit = _SHOCK_SUBREDDIT_MAP.get(
        shock.get("shock_type", ""), "HongKong"
    )

    try:
        manual = ManualAction(
            agent_id=0,
            action=ActionType.CREATE_POST,
            content=post_content,
        )
        await env.step(env_action=manual)
        logger.info(
            "Injected shock '%s' to r/%s at round %d",
            shock.get("shock_type", "unknown"),
            subreddit,
            shock.get("round_number", -1),
        )
        emit("post", {
            "platform": "reddit",
            "source": "shock",
            "shock_type": shock.get("shock_type", ""),
            "subreddit": subreddit,
            "round": shock.get("round_number", -1),
            "content": post_content[:200],
        })
    except Exception as exc:
        logger.error("Failed to inject shock: %s", exc)
        emit("error", {
            "platform": "reddit",
            "message": (
                f"Shock injection failed at round "
                f"{shock.get('round_number')}: {exc}"
            ),
        })


# ---------------------------------------------------------------------------
# Round stats extraction
# ---------------------------------------------------------------------------

def _extract_round_stats(env: Any, round_num: int) -> dict[str, Any]:
    """Best-effort extraction of round statistics from the OASIS env."""
    stats: dict[str, Any] = {"round": round_num, "action_count": 0}

    for attr in ("last_step_actions", "action_log", "step_results"):
        log = getattr(env, attr, None)
        if log is not None:
            if isinstance(log, (list, tuple)):
                stats["action_count"] = len(log)
            elif isinstance(log, dict):
                stats["action_count"] = log.get("count", len(log))
            break

    return stats


# ---------------------------------------------------------------------------
# Main simulation (async)
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, _frame: Any) -> None:
    global _shutdown_requested
    logger.info("Received signal %d, requesting shutdown", signum)
    _shutdown_requested = True


async def run_reddit_simulation(config: dict[str, Any]) -> None:
    """Execute the Reddit OASIS simulation (fully async)."""
    global _shutdown_requested

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    session_id = config["session_id"]
    round_count = config["round_count"]
    agent_csv_path = config["agent_csv_path"]
    db_path = config.get("oasis_db_path", f"reddit_{session_id}.db")
    shocks = config.get("shocks", [])

    csv_file = Path(agent_csv_path)
    if not csv_file.is_file():
        raise FileNotFoundError(f"Agent CSV not found: {agent_csv_path}")

    logger.info(
        "Reddit simulation starting — session=%s, rounds=%d, csv=%s",
        session_id, round_count, agent_csv_path,
    )
    emit_progress(0, round_count, "Building OASIS Reddit model")

    # Build LLM model
    model = build_model(config)

    # Generate agent graph from CSV
    emit_progress(0, round_count, "Generating agents from CSV")
    channel = Channel()

    agent_graph = await generate_agents(
        agent_info_path=agent_csv_path,
        channel=channel,
        model=model,
        start_time=datetime.now(),
        recsys_type="reddit",
        available_actions=[
            ActionType.CREATE_POST,
            ActionType.UPVOTE,
            ActionType.DOWNVOTE,
            ActionType.CREATE_COMMENT,
        ],
    )

    agent_count = len(agent_graph.nodes) if hasattr(agent_graph, "nodes") else 0
    logger.info("Agent graph built with %d agents", agent_count)

    # Create OASIS environment
    emit_progress(0, round_count, "Creating OASIS Reddit environment")

    env = oasis.make(
        agent_graph=agent_graph,
        platform=DefaultPlatformType.REDDIT,
        database_path=db_path,
    )

    logger.info("OASIS Reddit environment created — agents=%d", agent_count)
    emit_progress(0, round_count, f"Environment ready with {agent_count} agents")

    # Reset environment
    await env.reset()

    # Run simulation rounds
    total_actions = 0
    last_round = 0

    for round_num in range(1, round_count + 1):
        last_round = round_num

        if _shutdown_requested:
            logger.info("Shutdown requested, stopping at round %d", round_num)
            emit_progress(round_num, round_count, "Shutdown requested")
            break

        # Inject any scheduled shocks before stepping
        round_shocks = get_shocks_for_round(shocks, round_num)
        for shock in round_shocks:
            await inject_shock(env, shock)

        # Execute one simulation round
        try:
            await env.step()
        except Exception as exc:
            logger.error("Error in round %d: %s", round_num, exc)
            emit("error", {
                "platform": "reddit",
                "message": f"Round {round_num} failed: {exc}",
                "round": round_num,
            })
            continue

        round_stats = _extract_round_stats(env, round_num)
        round_action_count = round_stats.get("action_count", 0)
        total_actions += round_action_count

        emit_progress(round_num, round_count, f"Round {round_num}/{round_count} complete")
        logger.info(
            "Reddit round %d/%d complete — %d actions this round",
            round_num, round_count, round_action_count,
        )

    # Final summary
    rounds_done = last_round if not _shutdown_requested else last_round - 1
    summary = {
        "platform": "reddit",
        "session_id": session_id,
        "rounds_completed": rounds_done,
        "total_rounds": round_count,
        "agent_count": agent_count,
        "total_actions": total_actions,
        "db_path": db_path,
    }

    emit("complete", summary)
    logger.info("Reddit simulation complete: %s", summary)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict[str, Any]:
    """Load config JSON from file."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HKSimEngine Reddit Simulation (OASIS)"
    )
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        emit("error", {"platform": "reddit", "message": f"Config error: {exc}"})
        sys.exit(1)

    try:
        asyncio.run(run_reddit_simulation(config))
    except Exception as exc:
        emit("error", {"platform": "reddit", "message": f"Fatal error: {exc}"})
        logger.exception("Unhandled exception in Reddit simulation")
        sys.exit(1)


if __name__ == "__main__":
    main()
