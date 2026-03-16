"""WebSocket endpoint for real-time simulation progress."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("api.ws")

router = APIRouter(prefix="/ws", tags=["websocket"])

# ---------------------------------------------------------------------------
# Global progress store: session_id -> list of buffered updates
# session_id -> asyncio.Queue of live updates
# ---------------------------------------------------------------------------
_progress_store: dict[str, list[dict]] = defaultdict(list)
_progress_queues: dict[str, asyncio.Queue] = {}


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
    _progress_store[session_id].append(update)


def clear_progress(session_id: str) -> None:
    """Remove buffered progress data for a completed or failed session."""
    _progress_store.pop(session_id, None)
    _progress_queues.pop(session_id, None)


@router.websocket("/progress/{session_id}")
async def simulation_progress(websocket: WebSocket, session_id: str) -> None:
    """Stream real-time simulation progress updates via WebSocket.

    1. Accept connection.
    2. Replay any already-buffered progress updates (catch-up for late clients).
    3. Forward live updates from the asyncio.Queue until the simulation
       signals "complete" or "error", or the client disconnects.
    4. Send a periodic ping every 30 s of inactivity to keep the connection
       alive through proxies.
    """
    await websocket.accept()

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
    try:
        while True:
            try:
                update = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_json(update)
                if update.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
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
