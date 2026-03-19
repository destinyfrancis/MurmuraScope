"""HK data dashboard endpoints."""

from fastapi import APIRouter, Query

from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db

router = APIRouter(prefix="/data", tags=["data"])

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
    except Exception as e:
        return APIResponse(success=False, data=None, error=str(e))

    return APIResponse(
        success=True,
        data={**result, "latest_update": latest_update or None},
    )


@router.get("/snapshots", response_model=APIResponse)
async def query_snapshots(
    metric: str = Query(default="cci_index", description="Metric name to query"),
    start_date: str | None = Query(default=None, description="Start date (ISO 8601)"),
    end_date: str | None = Query(default=None, description="End date (ISO 8601)"),
    limit: int = Query(default=30, ge=1, le=365, description="Max records to return"),
) -> APIResponse:
    """Query hk_data_snapshots for time-series macro data."""
    # TODO: Replace with real data service call
    # snapshots = await data_service.query_snapshots(metric, start_date, end_date, limit)
    mock_snapshots = [
        {"date": "2026-03-01", "metric": metric, "value": 152.3},
        {"date": "2026-02-01", "metric": metric, "value": 153.1},
        {"date": "2026-01-01", "metric": metric, "value": 154.0},
    ]
    return APIResponse(
        success=True,
        data=mock_snapshots,
        meta={
            "metric": metric,
            "start_date": start_date,
            "end_date": end_date,
            "count": len(mock_snapshots),
        },
    )
