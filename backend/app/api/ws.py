"""WebSocket endpoint for real-time simulation progress."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger("api.ws")

router = APIRouter(prefix="/ws", tags=["websocket"])

# ---------------------------------------------------------------------------
# Global progress store: session_id -> list of buffered updates
# session_id -> asyncio.Queue of live updates
# ---------------------------------------------------------------------------
_progress_store: dict[str, list[dict]] = defaultdict(list)
_progress_queues: dict[str, asyncio.Queue] = {}
_store_timestamps: dict[str, float] = {}

# Cap buffered entries per session to prevent unbounded memory growth
_MAX_BUFFERED_ENTRIES = 500

# Max idle pings before breaking the WS loop (60 pings * 30s = 30min)
_MAX_IDLE_PINGS = 60


def _cleanup_stale_progress() -> None:
    """Remove progress store entries older than 1 hour."""
    now = time.monotonic()
    stale = [sid for sid, ts in _store_timestamps.items() if now - ts > 3600.0]
    for sid in stale:
        _progress_store.pop(sid, None)
        _progress_queues.pop(sid, None)
        _store_timestamps.pop(sid, None)
    if stale:
        logger.debug("Cleaned up %d stale progress entries", len(stale))


def get_progress_queue(session_id: str) -> asyncio.Queue:
    """Return (or create) the asyncio.Queue for *session_id*."""
    if session_id not in _progress_queues:
        _progress_queues[session_id] = asyncio.Queue()
    return _progress_queues[session_id]


async def push_progress(session_id: str, update: dict) -> None:
    """Push a progress update from SimulationRunner to the WS queue.

    Called by the background simulation task to broadcast updates to any
    connected WebSocket clients.  Updates are also buffered so that clients
    connecting after the simulation has started receive previous progress.
    """
    q = get_progress_queue(session_id)
    await q.put(update)
    buf = _progress_store[session_id]
    buf.append(update)
    # Cap buffer size to prevent memory leak
    if len(buf) > _MAX_BUFFERED_ENTRIES:
        _progress_store[session_id] = buf[-_MAX_BUFFERED_ENTRIES:]
    _store_timestamps[session_id] = time.monotonic()


def clear_progress(session_id: str) -> None:
    """Remove buffered progress data for a completed or failed session."""
    _progress_store.pop(session_id, None)
    _progress_queues.pop(session_id, None)
    _store_timestamps.pop(session_id, None)


@router.websocket("/progress/{session_id}")
async def simulation_progress(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    """Stream real-time simulation progress updates via WebSocket.

    1. Validate JWT token (optional but logged when missing).
    2. Accept connection.
    3. Replay any already-buffered progress updates (catch-up for late clients).
    4. Forward live updates from the asyncio.Queue until the simulation
       signals "complete" or "error", or the client disconnects.
    5. Send a periodic ping every 30 s of inactivity to keep the connection
       alive through proxies.
    """
    # Authenticate: reject if token is provided but invalid; allow anonymous
    # for backward compatibility but log a warning.
    if token:
        try:
            from backend.app.api.auth import _decode_token  # noqa: PLC0415

            _decode_token(token)
        except Exception:
            await websocket.close(code=4003, reason="Invalid or expired token")
            return
    else:
        logger.warning("WS connection without token for session=%s", session_id)

    await websocket.accept()

    # Clean up stale entries from other sessions on each new connection
    _cleanup_stale_progress()

    q = get_progress_queue(session_id)

    # Replay buffered history so late-connecting clients don't miss events.
    # Only replay structural events, not individual posts/shocks which would
    # flood the client on reconnect.
    for item in list(_progress_store.get(session_id, [])):
        if item.get("type") in ("progress", "complete", "error"):
            try:
                await websocket.send_json(item)
            except Exception:
                logger.debug("Failed to replay progress for session %s", session_id)
                await websocket.close()
                return

    # Stream live updates.
    idle_ping_count = 0
    try:
        while True:
            try:
                update = await asyncio.wait_for(q.get(), timeout=30.0)
                idle_ping_count = 0  # reset on real message
                await websocket.send_json(update)
                if update.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                idle_ping_count += 1
                if idle_ping_count >= _MAX_IDLE_PINGS:
                    logger.info(
                        "WebSocket idle limit reached for session %s (%d pings), closing",
                        session_id,
                        idle_ping_count,
                    )
                    break
                # Send a ping to keep the connection alive.
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected for session %s", session_id)
    except Exception:
        logger.debug("WebSocket error for session %s", session_id, exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            logger.debug("WebSocket close failed for session %s", session_id)
