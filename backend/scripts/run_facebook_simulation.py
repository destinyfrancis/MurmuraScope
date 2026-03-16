"""
HKSimEngine OASIS Facebook Simulation Runner

Usage: python run_facebook_simulation.py --config /path/to/config.json

Runs a Facebook-style social media simulation using the OASIS framework.
Facebook groups map to the OASIS Reddit (community/subreddit) backend.
Outputs JSONL progress updates to stdout for IPC with parent process.

Actions supported: CREATE_POST, LIKE_POST, DISLIKE_POST, CREATE_COMMENT
Agent input: CSV file with columns username, description, user_char
Facebook uses HK-themed Chinese FB Groups; shock posts are routed to the
most relevant group based on shock type.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("facebook_simulation")

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
                "platform": "facebook",
                "message": (
                    "OASIS framework not found. Install it with "
                    "'pip install oasis-social-sim' or add it to PYTHONPATH."
                ),
            },
        }, ensure_ascii=False),
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
                "platform": "facebook",
                "message": "CAMEL-AI not found. Install with 'pip install camel-ai'.",
            },
        }, ensure_ascii=False),
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
        "platform": "facebook",
        "round": round_num,
        "total": total,
        "detail": detail,
    })


def emit_new_posts(db_path: str, round_num: int, last_post_id: int) -> int:
    """Read new posts from OASIS DB and emit each as a 'post' event.

    Returns the updated last_post_id (max post_id seen so far).
    """
    if not Path(db_path).exists():
        return last_post_id
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT p.post_id, p.content, u.name
               FROM post p
               LEFT JOIN user u ON p.user_id = u.user_id
               WHERE p.post_id > ?
               ORDER BY p.post_id""",
            (last_post_id,),
        ).fetchall()
        conn.close()
        for row in rows:
            content = (row["content"] or "").strip()
            if not content:
                continue
            emit("post", {
                "platform": "facebook",
                "source": "agent",
                "username": row["name"] or "Agent",
                "content": content[:300],
                "round": round_num,
            })
        if rows:
            return max(row["post_id"] for row in rows)
    except Exception as exc:
        logger.warning("emit_new_posts failed for round %d: %s", round_num, exc)
    return last_post_id


# Content actions whose info payload may contain post text
_CONTENT_ACTIONS = frozenset({
    "create_post", "repost", "quote_post", "create_comment",
})

_TRACKED_ACTIONS = frozenset({
    "create_post", "like_post", "unlike_post", "dislike_post",
    "follow", "unfollow", "repost", "quote_post", "create_comment",
    "like_comment", "dislike_comment", "do_nothing", "mute", "unmute",
    "search_posts", "search_user", "trend", "refresh",
})


def emit_new_actions(db_path: str, round_num: int, last_trace_ts: str) -> str:
    """Read non-content actions from OASIS trace table and emit as 'action' events.

    Returns updated last_trace_ts (max created_at seen).
    """
    if not Path(db_path).exists():
        return last_trace_ts
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT t.user_id, t.created_at, t.action, t.info, u.name
               FROM trace t
               LEFT JOIN user u ON t.user_id = u.user_id
               WHERE t.created_at > ?
               ORDER BY t.created_at""",
            (last_trace_ts,),
        ).fetchall()
        conn.close()

        max_ts = last_trace_ts
        for row in rows:
            action = (row["action"] or "").strip()
            if action not in _TRACKED_ACTIONS:
                continue
            if action in _CONTENT_ACTIONS:
                ts = row["created_at"] or ""
                if ts > max_ts:
                    max_ts = ts
                continue

            username = row["name"] or f"Agent_{row['user_id']}"
            info_raw = row["info"] or "{}"
            try:
                info = json.loads(info_raw) if isinstance(info_raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                info = {}

            emit("action", {
                "platform": "facebook",
                "source": "agent",
                "action_type": action,
                "username": username,
                "round": round_num,
                "info": info,
            })

            ts = row["created_at"] or ""
            if ts > max_ts:
                max_ts = ts

        return max_ts
    except Exception as exc:
        logger.warning("emit_new_actions failed for round %d: %s", round_num, exc)
    return last_trace_ts


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
    api_key = config.get("llm_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    base_url = config.get("llm_base_url", LLM_PROVIDER_URLS.get(provider, ""))

    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — simulation will fail at LLM call")
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
# Default Facebook Groups for HK simulation (Chinese group names)
# ---------------------------------------------------------------------------

DEFAULT_GROUPS: list[dict[str, str]] = [
    {"name": "香港交流區", "description": "香港一般討論交流"},
    {"name": "香港樓市討論", "description": "香港物業市場討論"},
    {"name": "香港理財", "description": "香港財務及投資討論"},
    {"name": "香港移民交流", "description": "香港移民資訊交流"},
    {"name": "香港湊仔經", "description": "香港育兒及家庭生活"},
    {"name": "香港搵工區", "description": "香港就業及職場討論"},
    {"name": "香港時事", "description": "香港時事及政策討論"},
]

# Map shock types to the most relevant FB group
_SHOCK_GROUP_MAP: dict[str, str] = {
    "interest_rate_hike": "香港理財",
    "property_crash": "香港樓市討論",
    "unemployment_spike": "香港搵工區",
    "policy_change": "香港時事",
    "market_rally": "香港理財",
    "emigration_wave": "香港移民交流",
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

    For Facebook, shocks are posted to the most relevant HK FB group.
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

    group = _SHOCK_GROUP_MAP.get(shock.get("shock_type", ""), "香港交流區")

    try:
        manual = ManualAction(
            agent_id=0,
            action=ActionType.CREATE_POST,
            content=post_content,
        )
        await env.step(env_action=manual)
        logger.info(
            "Injected shock '%s' to group '%s' at round %d",
            shock.get("shock_type", "unknown"),
            group,
            shock.get("round_number", -1),
        )
        emit("post", {
            "platform": "facebook",
            "source": "shock",
            "shock_type": shock.get("shock_type", ""),
            "group": group,
            "round": shock.get("round_number", -1),
            "content": post_content[:200],
        })
    except Exception as exc:
        logger.error("Failed to inject shock: %s", exc)
        emit("error", {
            "platform": "facebook",
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


async def run_facebook_simulation(config: dict[str, Any]) -> None:
    """Execute the Facebook OASIS simulation (fully async).

    Facebook maps to the OASIS Reddit (community) backend — agents interact
    inside groups mirroring the subreddit community structure.
    """
    global _shutdown_requested

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    session_id = config["session_id"]
    round_count = config["round_count"]
    agent_csv_path = config["agent_csv_path"]
    db_path = config.get("oasis_db_path", f"facebook_{session_id}.db")
    shocks = config.get("shocks", [])

    csv_file = Path(agent_csv_path)
    if not csv_file.is_file():
        raise FileNotFoundError(f"Agent CSV not found: {agent_csv_path}")

    # Ensure db directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Facebook simulation starting — session=%s, rounds=%d, csv=%s",
        session_id, round_count, agent_csv_path,
    )
    emit_progress(0, round_count, "Building OASIS Facebook (Reddit backend) model")

    # Build LLM model
    model = build_model(config)

    # Generate agent graph from CSV (Reddit backend for community-style interaction)
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
            ActionType.LIKE_POST,
            ActionType.DISLIKE_POST,
            ActionType.FOLLOW,
            ActionType.UNFOLLOW,
            ActionType.REPOST,
            ActionType.CREATE_COMMENT,
            ActionType.DO_NOTHING,
            ActionType.MUTE,
            ActionType.SEARCH_POSTS,
            ActionType.TREND,
        ],
    )

    agent_count = len(agent_graph.nodes) if hasattr(agent_graph, "nodes") else 0
    logger.info("Agent graph built with %d agents", agent_count)

    # Create OASIS environment using Reddit backend (Facebook group = subreddit)
    emit_progress(0, round_count, "Creating OASIS environment (Reddit backend for FB groups)")

    env = oasis.make(
        agent_graph=agent_graph,
        platform=DefaultPlatformType.REDDIT,
        database_path=db_path,
    )

    logger.info("OASIS Facebook environment created — agents=%d", agent_count)
    emit_progress(0, round_count, f"Environment ready with {agent_count} agents")

    # Reset environment
    await env.reset()

    # Run simulation rounds
    total_actions = 0
    last_round = 0
    last_post_id = 0
    last_trace_ts = ""

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
            # Emit new agent posts from OASIS DB for this round
            last_post_id = emit_new_posts(db_path, round_num, last_post_id)
            # Emit non-content actions from trace table
            last_trace_ts = emit_new_actions(db_path, round_num, last_trace_ts)
        except Exception as exc:
            logger.error("Error in round %d: %s", round_num, exc)
            emit("error", {
                "platform": "facebook",
                "message": f"Round {round_num} failed: {exc}",
                "round": round_num,
            })
            continue

        round_stats = _extract_round_stats(env, round_num)
        round_action_count = round_stats.get("action_count", 0)
        total_actions += round_action_count

        emit_progress(round_num, round_count, f"Round {round_num}/{round_count} complete")
        logger.info(
            "Facebook round %d/%d complete — %d actions this round",
            round_num, round_count, round_action_count,
        )

    # Final summary
    rounds_done = last_round if not _shutdown_requested else last_round - 1
    summary = {
        "platform": "facebook",
        "session_id": session_id,
        "rounds_completed": rounds_done,
        "total_rounds": round_count,
        "agent_count": agent_count,
        "total_actions": total_actions,
        "db_path": db_path,
    }

    emit("complete", summary)
    logger.info("Facebook simulation complete: %s", summary)


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
        description="HKSimEngine Facebook Simulation (OASIS Reddit backend)"
    )
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        emit("error", {"platform": "facebook", "message": f"Config error: {exc}"})
        sys.exit(1)

    try:
        asyncio.run(run_facebook_simulation(config))
    except Exception as exc:
        emit("error", {"platform": "facebook", "message": f"Fatal error: {exc}"})
        logger.exception("Unhandled exception in Facebook simulation")
        sys.exit(1)


if __name__ == "__main__":
    main()
