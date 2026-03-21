"""
MurmuraScope OASIS Instagram Simulation Runner

Usage: python run_instagram_simulation.py --config /path/to/config.json

Runs an Instagram-style social media simulation using the OASIS framework.
Instagram maps to the OASIS Twitter (feed/follower) backend.
Outputs JSONL progress updates to stdout for IPC with parent process.

Actions supported: CREATE_POST, LIKE_POST, FOLLOW, CREATE_COMMENT, REPOST
REPOST represents "Share to Story" on Instagram.
Post content is capped at 200 characters (IG caption style).
Agent input: CSV file with columns username, description, user_char
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
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("instagram_sim")

# ---------------------------------------------------------------------------
# OASIS imports (correct top-level API)
# ---------------------------------------------------------------------------
try:
    import oasis
    from oasis import (
        ActionType,
        DefaultPlatformType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
    )
except ImportError as exc:
    logger.error("OASIS not installed: %s", exc)
    print(
        json.dumps({"type": "error", "data": {"platform": "instagram", "message": str(exc)}},
                   ensure_ascii=False),
        flush=True,
    )
    sys.exit(1)

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
except ImportError as exc:
    logger.error("CAMEL-AI not installed: %s", exc)
    print(
        json.dumps({"type": "error", "data": {"platform": "instagram", "message": str(exc)}},
                   ensure_ascii=False),
        flush=True,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Instagram caption character limit (enforced on emitted posts)
_IG_CAPTION_LIMIT = 200

# ---------------------------------------------------------------------------
# IPC helpers
# ---------------------------------------------------------------------------

def emit(msg_type: str, data: dict[str, Any]) -> None:
    """Write a JSONL message to stdout."""
    sys.stdout.write(
        json.dumps({"type": msg_type, "data": data}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def emit_progress(current: int, total: int, detail: str = "") -> None:
    emit("progress", {
        "platform": "instagram",
        "round": current,
        "total": total,
        "detail": detail,
    })


def emit_new_posts(db_path: str, round_num: int, last_post_id: int) -> int:
    """Read new posts from OASIS DB and emit each as a 'post' event.

    Post content is truncated to _IG_CAPTION_LIMIT (200 chars) to match
    Instagram caption style. Returns the updated last_post_id.
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
                "platform": "instagram",
                "source": "agent",
                "username": row["name"] or "Agent",
                "content": content[:_IG_CAPTION_LIMIT],
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
                "platform": "instagram",
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
# Model builder
# ---------------------------------------------------------------------------

LLM_URLS: dict[str, str] = {
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
    base_url = config.get("llm_base_url") or LLM_URLS.get(provider, "")

    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — simulation will fail at LLM call")
    if not base_url:
        raise ValueError(f"No base_url for provider '{provider}'")

    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=model_name,
        url=base_url,
        model_config_dict={"temperature": 0.7, "max_tokens": 4096},
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Shock injection
# ---------------------------------------------------------------------------

def get_shocks_for_round(
    shocks: list[dict[str, Any]], round_num: int
) -> list[dict[str, Any]]:
    """Return shocks scheduled for the given round number."""
    return [s for s in shocks if s.get("round_number") == round_num]


async def inject_shock(env: Any, agent_graph: Any, shock: dict[str, Any]) -> None:
    """Inject a macro shock via ManualAction CREATE_POST.

    Content is capped at _IG_CAPTION_LIMIT to match Instagram caption style.
    """
    post_content = shock.get("post_content", "")
    if not post_content:
        return

    agents = agent_graph.get_agents([0])
    if not agents:
        return

    _, agent = agents[0]
    manual = ManualAction(
        action_type=ActionType.CREATE_POST,
        action_args={"content": post_content},
    )
    try:
        await env.step({agent: manual})
        logger.info(
            "Shock '%s' injected at round %d",
            shock.get("shock_type", ""),
            shock.get("round_number", -1),
        )
        emit("post", {
            "platform": "instagram",
            "source": "shock",
            "shock_type": shock.get("shock_type", ""),
            "round": shock.get("round_number", -1),
            "content": post_content[:_IG_CAPTION_LIMIT],
        })
    except Exception as exc:
        logger.error("Shock injection failed: %s", exc)
        emit("error", {
            "platform": "instagram",
            "message": (
                f"Shock injection failed at round "
                f"{shock.get('round_number')}: {exc}"
            ),
        })


# ---------------------------------------------------------------------------
# Main simulation (async)
# ---------------------------------------------------------------------------

_shutdown = False


def _on_signal(signum: int, _frame: Any) -> None:
    global _shutdown
    _shutdown = True
    logger.info("Signal %d — shutting down", signum)


async def run_instagram_simulation(config: dict[str, Any]) -> None:
    """Execute the Instagram OASIS simulation (fully async).

    Instagram maps to the OASIS Twitter (feed/follower) backend — agents
    interact via a follower graph with feed-style content distribution.
    REPOST represents "Share to Story" in the Instagram context.
    """
    global _shutdown

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    session_id = config["session_id"]
    round_count = int(config["round_count"])
    agent_csv = config["agent_csv_path"]
    db_path = config.get("oasis_db_path", f"data/instagram_{session_id}.db")
    shocks = config.get("shocks", [])

    if not Path(agent_csv).is_file():
        raise FileNotFoundError(f"Agent CSV not found: {agent_csv}")

    # Ensure db directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting Instagram simulation — session=%s rounds=%d csv=%s",
        session_id, round_count, agent_csv,
    )
    emit_progress(0, round_count, "Building LLM model")

    model = build_model(config)

    emit_progress(0, round_count, "Generating Instagram agent graph from CSV")

    # Instagram uses Twitter (feed/follower) backend via generate_twitter_agent_graph
    agent_graph = await generate_twitter_agent_graph(
        profile_path=agent_csv,
        model=model,
        available_actions=[
            ActionType.CREATE_POST,
            ActionType.LIKE_POST,
            ActionType.DISLIKE_POST,
            ActionType.FOLLOW,
            ActionType.UNFOLLOW,
            ActionType.REPOST,  # REPOST = Share to Story on Instagram
            ActionType.QUOTE_POST,
            ActionType.CREATE_COMMENT,
            ActionType.DO_NOTHING,
            ActionType.MUTE,
            ActionType.SEARCH_POSTS,
            ActionType.TREND,
        ],
    )

    agent_count = agent_graph.get_num_nodes()
    logger.info("Agent graph: %d agents", agent_count)
    emit_progress(0, round_count, f"Created {agent_count} agents")

    env = oasis.make(
        agent_graph=agent_graph,
        platform=DefaultPlatformType.TWITTER,
        database_path=db_path,
    )

    emit_progress(0, round_count, "Resetting environment")
    await env.reset()

    # All agents perform LLM actions each round
    all_agents_list = agent_graph.get_agents()
    llm_actions = {agent: LLMAction() for _, agent in all_agents_list}

    total_actions = 0
    last_round = 0
    last_post_id = 0
    last_trace_ts = ""

    for round_num in range(1, round_count + 1):
        last_round = round_num

        if _shutdown:
            emit_progress(round_num, round_count, "Shutdown")
            break

        # Shocks first
        for shock in get_shocks_for_round(shocks, round_num):
            await inject_shock(env, agent_graph, shock)

        # Normal LLM round
        try:
            await env.step(llm_actions)
            total_actions += agent_count
            # Emit new agent posts from OASIS DB (content capped to IG style)
            last_post_id = emit_new_posts(db_path, round_num, last_post_id)
            # Emit non-content actions from trace table
            last_trace_ts = emit_new_actions(db_path, round_num, last_trace_ts)
            emit_progress(
                round_num,
                round_count,
                f"Round {round_num}/{round_count} done — {agent_count} actions",
            )
            logger.info("Round %d/%d complete", round_num, round_count)
        except Exception as exc:
            logger.error("Round %d error: %s", round_num, exc)
            emit("error", {
                "platform": "instagram",
                "round": round_num,
                "message": str(exc),
            })

    emit("complete", {
        "platform": "instagram",
        "session_id": session_id,
        "rounds_completed": last_round,
        "total_rounds": round_count,
        "agent_count": agent_count,
        "total_actions": total_actions,
        "db_path": db_path,
    })
    logger.info(
        "Instagram simulation complete — %d rounds, %d total actions",
        last_round, total_actions,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MurmuraScope Instagram Simulation (OASIS Twitter backend)"
    )
    parser.add_argument("--config", required=True, help="Config JSON path")
    args = parser.parse_args()

    try:
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as exc:
        emit("error", {"platform": "instagram", "message": f"Config load failed: {exc}"})
        sys.exit(1)

    try:
        asyncio.run(run_instagram_simulation(config))
    except Exception as exc:
        emit("error", {"platform": "instagram", "message": f"Fatal: {exc}"})
        logger.exception("Unhandled exception in Instagram simulation")
        sys.exit(1)


if __name__ == "__main__":
    main()
