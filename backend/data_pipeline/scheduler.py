"""Data pipeline scheduler using APScheduler.

Runs data downloads on a cadence appropriate to each data type:
- Daily:   market data (HSI, FX rates)
- Weekly:  economic indicators (HIBOR, prime rate, FRED)
- Monthly: census, property, employment, education, migration

Usage (from backend startup):
    from backend.data_pipeline.scheduler import DataScheduler
    scheduler = DataScheduler()
    scheduler.start()
    # ... on shutdown:
    scheduler.stop()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.scheduler")


@dataclass(frozen=True)
class ScheduledJob:
    """Immutable description of a scheduled pipeline job."""

    name: str
    categories: tuple[str, ...]
    trigger: str  # "cron" trigger type
    hour: int | str
    minute: int
    day_of_week: str | None  # None means every day
    day: str | None  # "1" means first of month


class DataScheduler:
    """Schedules periodic data pipeline downloads using APScheduler.

    Uses AsyncIOScheduler so jobs run inside the same event loop as
    the FastAPI application without spawning extra threads.

    Example::

        scheduler = DataScheduler()
        scheduler.start()
        # app runs ...
        scheduler.stop()
    """

    # Job definitions — immutable tuples
    _JOB_DEFINITIONS: tuple[ScheduledJob, ...] = (
        ScheduledJob(
            name="daily_market",
            categories=("market",),
            trigger="cron",
            hour=8,
            minute=0,
            day_of_week=None,  # every day
            day=None,
        ),
        ScheduledJob(
            name="daily_fred",
            categories=("fred",),
            trigger="cron",
            hour=8,
            minute=30,
            day_of_week=None,
            day=None,
        ),
        ScheduledJob(
            name="weekly_economy",
            categories=("economy",),
            trigger="cron",
            hour=9,
            minute=0,
            day_of_week="mon",  # every Monday
            day=None,
        ),
        ScheduledJob(
            name="weekly_social",
            categories=("social",),
            trigger="cron",
            hour=6,
            minute=0,
            day_of_week="sun",  # every Sunday
            day=None,
        ),
        ScheduledJob(
            name="monthly_census_property",
            categories=("census", "property", "employment", "education", "migration"),
            trigger="cron",
            hour=2,
            minute=0,
            day_of_week=None,
            day="1",  # 1st of each month
        ),
        ScheduledJob(
            name="monthly_china_macro",
            categories=("china_macro", "retail_tourism", "trade"),
            trigger="cron",
            hour=3,
            minute=0,
            day_of_week=None,
            day="2",  # 2nd of each month
        ),
        ScheduledJob(
            name="weekly_calibration",
            categories=(),  # empty = calibration pipeline, not download
            trigger="cron",
            hour=4,
            minute=0,
            day_of_week="sun",
            day=None,
        ),
    )

    def __init__(self, normalize: bool = True) -> None:
        """Initialise the scheduler.

        Args:
            normalize: Whether to normalise downloaded data into DB.
                Defaults to True for production use.
        """
        self._normalize = normalize
        self._scheduler: Any = None  # APScheduler instance (lazy import)

    def _get_scheduler(self) -> Any:
        """Lazily import and return APScheduler instance."""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import]

                self._scheduler = AsyncIOScheduler(timezone="Asia/Hong_Kong")
            except ImportError as exc:
                raise RuntimeError(
                    "APScheduler is required for the data scheduler. Install with: pip install 'apscheduler>=3.10'"
                ) from exc
        return self._scheduler

    def _make_job_func(self, categories: tuple[str, ...], normalize: bool):
        """Return an async job function for the given categories.

        When *categories* is empty, runs the calibration pipeline instead
        of a data download.
        """
        if not categories:
            # Calibration-only job
            async def _calibration_job() -> None:
                try:
                    from backend.data_pipeline.calibration import CalibrationPipeline

                    logger.info("Scheduler: starting calibration pipeline")
                    pipeline = CalibrationPipeline()
                    await pipeline.run_calibration()
                    logger.info("Scheduler: calibration complete")
                except Exception:
                    logger.exception("Scheduler calibration job failed")

            return _calibration_job

        async def _job() -> None:
            try:
                from backend.data_pipeline.download_all import run_pipeline  # avoid circular at module level

                logger.info("Scheduler: starting download for %s", categories)
                summaries = await run_pipeline(categories=categories, normalize=normalize)
                total = sum(s.total_records for s in summaries)
                errors = [s for s in summaries if s.error]
                logger.info(
                    "Scheduler: completed %s — %d records, %d errors",
                    categories,
                    total,
                    len(errors),
                )
            except Exception:
                logger.exception("Scheduler job failed for categories: %s", categories)

        return _job

    def _build_cron_kwargs(self, job_def: ScheduledJob) -> dict[str, Any]:
        """Build APScheduler cron trigger kwargs from a ScheduledJob."""
        kwargs: dict[str, Any] = {
            "hour": job_def.hour,
            "minute": job_def.minute,
        }
        if job_def.day_of_week is not None:
            kwargs["day_of_week"] = job_def.day_of_week
        if job_def.day is not None:
            kwargs["day"] = job_def.day
        return kwargs

    def start(self) -> None:
        """Register all jobs and start the scheduler.

        Safe to call from within a running event loop (FastAPI startup).
        Raises RuntimeError if APScheduler is not installed.
        """
        scheduler = self._get_scheduler()

        for job_def in self._JOB_DEFINITIONS:
            cron_kwargs = self._build_cron_kwargs(job_def)
            job_func = self._make_job_func(job_def.categories, self._normalize)

            scheduler.add_job(
                job_func,
                trigger="cron",
                id=job_def.name,
                replace_existing=True,
                misfire_grace_time=3600,  # allow 1-hour late execution
                **cron_kwargs,
            )
            logger.info(
                "Scheduled job '%s': categories=%s, trigger=%s",
                job_def.name,
                job_def.categories,
                cron_kwargs,
            )

        scheduler.start()
        logger.info("DataScheduler started with %d jobs", len(self._JOB_DEFINITIONS))

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("DataScheduler stopped")

    def run_job_now(self, job_name: str) -> None:
        """Trigger a job immediately (useful for manual backfill).

        Args:
            job_name: The job name as defined in _JOB_DEFINITIONS.

        Raises:
            ValueError: If job_name is not found.
        """
        scheduler = self._get_scheduler()
        job = scheduler.get_job(job_name)
        if job is None:
            raise ValueError(f"Job '{job_name}' not found. Available: {self.job_names}")
        job.modify(next_run_time=__import__("datetime").datetime.now())
        logger.info("Triggered immediate run for job '%s'", job_name)

    @property
    def job_names(self) -> list[str]:
        """Return list of registered job names."""
        return [j.name for j in self._JOB_DEFINITIONS]

    @property
    def is_running(self) -> bool:
        """Return True if the scheduler is currently running."""
        return self._scheduler is not None and self._scheduler.running


def _standalone_demo() -> None:
    """Run scheduler demo (does not download — just shows job registration)."""

    scheduler = DataScheduler(normalize=False)
    logger.info("Registered jobs: %s", scheduler.job_names)
    # In a real app, call scheduler.start() inside an asyncio event loop.
    logger.info("DataScheduler ready. Call .start() from within an async context.")


if __name__ == "__main__":
    _standalone_demo()
