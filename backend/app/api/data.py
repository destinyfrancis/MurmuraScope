"""HK data dashboard endpoints."""

from fastapi import APIRouter, Query

from backend.app.models.response import APIResponse, DataDashboardResponse

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/dashboard", response_model=APIResponse)
async def get_dashboard() -> APIResponse:
    """Get the latest HK macro data dashboard."""
    # TODO: Replace with real data service call
    # dashboard = await data_service.get_dashboard()
    mock = DataDashboardResponse(
        population={
            "total": 7_500_000,
            "growth_rate": -0.3,
            "median_age": 46.2,
            "net_migration": -12000,
        },
        economy={
            "gdp_growth": 2.5,
            "inflation_rate": 2.1,
            "base_rate": 5.25,
            "hsi_index": 17800,
        },
        property_market={
            "cci_index": 152.3,
            "avg_price_psf": 12500,
            "transaction_volume": 4200,
            "rental_yield": 2.8,
        },
        employment={
            "unemployment_rate": 3.0,
            "median_income": 20000,
            "labor_force_participation": 58.2,
        },
        latest_update="2026-03-10T00:00:00Z",
    )
    return APIResponse(success=True, data=mock.model_dump())


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
