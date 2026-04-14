"""Simulation Job Worker — manages persistent simulation execution queue.

Ensures at most N simulations run concurrently and handles job status transitions.
The worker runs as a background task in the FastAPI process.
"""

from __future__ import annotations

import asyncio
import os
import logging
from datetime import datetime

from backend.app.utils.db import get_db
from backend.app.services.simulation_manager import get_simulation_manager

logger = logging.getLogger("simulation_worker")

class SimulationWorker:
    """Background worker for processing the simulation job queue."""

    def __init__(self, max_concurrent: int | None = None) -> None:
        self._max_concurrent = max_concurrent or int(os.environ.get("MAX_CONCURRENT_SIMULATIONS", "3"))
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._poll_interval = 5.0  # seconds

    async def start(self) -> None:
        """Start the background worker loop."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._main_loop(), name="simulation-job-worker")
        logger.info("SimulationWorker started with max_concurrent=%d", self._max_concurrent)

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("SimulationWorker stopped")

    async def _main_loop(self) -> None:
        """Continuous loop polling for pending jobs."""
        while self._running:
            try:
                await self._process_queue()
            except Exception:
                logger.exception("SimulationWorker loop encountered error")
            
            await asyncio.sleep(self._poll_interval)

    async def _process_queue(self) -> None:
        """Check active jobs and start pending ones if capacity exists."""
        async with get_db() as db:
            # 1. Count currently running jobs
            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM simulation_jobs WHERE status = 'running'"
            )
            row = await cursor.fetchone()
            running_count = row["c"] if row else 0

            if running_count >= self._max_concurrent:
                logger.debug("At capacity (%d/%d running). Skipping queue poll.", running_count, self._max_concurrent)
                return

            # 2. Find next pending jobs
            slots_available = self._max_concurrent - running_count
            cursor = await db.execute(
                "SELECT id, session_id FROM simulation_jobs WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (slots_available,)
            )
            pending_jobs = await cursor.fetchall()

        if not pending_jobs:
            return

        logger.info("SimulationWorker: Picking up %d pending job(s)", len(pending_jobs))
        
        manager = get_simulation_manager()
        for job in pending_jobs:
            job_id = job["id"]
            session_id = job["session_id"]
            
            try:
                # Discard the task object; SimulationManager tracks its own tasks
                # and handles status updates from 'running' onwards.
                await manager.start_session_from_job(session_id, job_id)
            except Exception as e:
                logger.error("Failed to start queued job %d (session=%s): %s", job_id, session_id, e)
                async with get_db() as db:
                    await db.execute(
                        "UPDATE simulation_jobs SET status = 'failed', error_message = ?, updated_at = datetime('now') "
                        "WHERE id = ?",
                        (str(e), job_id)
                    )
                    await db.commit()

# --- Singleton access ---
_worker_instance: SimulationWorker | None = None

async def get_simulation_worker() -> SimulationWorker:
    """Return the global SimulationWorker singleton."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = SimulationWorker()
    return _worker_instance
