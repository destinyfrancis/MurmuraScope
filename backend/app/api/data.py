"""HK data dashboard endpoints."""

from fastapi import APIRouter, HTTPException, Query

from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("api.data")

router = APIRouter(prefix="/data", tags=["data"])

_ALLOWED_SNAPSHOT_METRICS = frozenset(
    {
        "ccl_index",
        "hsi_level",
        "gdp_growth",
        "unemployment_rate",
        "consumer_confidence",
        "inflation_rate",
        "median_income",
        "avg_price_psf",
        "rental_yield",
    }
)

# Metrics to surface per category.  Extend this dict as new metrics are stored.
_DASHBOARD_METRICS: dict[str, list[str]] = {
    "economy": ["gdp_growth", "inflation_rate", "hsi_level"],
    "employment": ["unemployment_rate", "median_income"],
    "property_market": ["ccl_index", "avg_price_psf", "rental_yield"],
}


@router.get("/dashboard", response_model=APIResponse)
async def get_dashboard() -> APIResponse:
    """Get the latest HK macro data dashboard from hk_data_snapshots."""
    result: dict[str, dict[str, float]] = {cat: {} for cat in _DASHBOARD_METRICS}
    latest_update: str = ""

    try:
        async with get_db() as db:
            for category, metrics in _DASHBOARD_METRICS.items():
                for metric in metrics:
                    cursor = await db.execute(
                        "SELECT value, period FROM hk_data_snapshots "
                        "WHERE category = ? AND metric = ? "
                        "ORDER BY period DESC LIMIT 1",
                        (category, metric),
                    )
                    row = await cursor.fetchone()
                    result[category][metric] = float(row["value"]) if row else 0.0
                    if row and row["period"] > latest_update:
                        latest_update = row["period"]
    except Exception:
        logger.exception("Failed to fetch dashboard data")
        return APIResponse(success=False, data=None, error="Failed to fetch dashboard data")

    return APIResponse(
        success=True,
        data={**result, "latest_update": latest_update or None},
    )


@router.get("/snapshots", response_model=APIResponse)
async def get_snapshots(
    metric: str = Query(default="ccl_index", description="Metric name to query"),
    start_date: str | None = Query(default=None, description="Start date (ISO 8601)"),
    end_date: str | None = Query(default=None, description="End date (ISO 8601)"),
    limit: int = Query(default=30, ge=1, le=365, description="Max records to return"),
) -> APIResponse:
    """Query hk_data_snapshots for time-series macro data."""
    if metric not in _ALLOWED_SNAPSHOT_METRICS:
        raise HTTPException(status_code=400, detail=f"Unknown metric: {metric!r}")

    conditions = ["metric = ?"]
    params: list = [metric]
    if start_date:
        conditions.append("period >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("period <= ?")
        params.append(end_date)
    params.append(limit)

    sql = (
        "SELECT period AS date, value FROM hk_data_snapshots "
        "WHERE " + " AND ".join(conditions) + " "
        "ORDER BY period DESC LIMIT ?"
    )
    try:
        async with get_db() as db:
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
    except Exception:
        logger.exception("Failed to fetch snapshots for metric=%s", metric)
        return APIResponse(success=False, data=None, error="Failed to fetch snapshot data")

    snapshots = [{"date": r["date"], "value": r["value"]} for r in rows]
    return APIResponse(
        success=True,
        data=snapshots,
        meta={
            "metric": metric,
            "start_date": start_date,
            "end_date": end_date,
            "count": len(snapshots),
        },
    )
