"""Tests verifying the "real data upgrade" — no synthetic data enters the pipeline.

Covers:
- File-level checks: no hardcoded fallback constants in downloaders
- Model-level checks: required data-quality fields on result dataclasses
- Functional checks: forecaster refuses insufficient data, proxy tagging
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PIPELINE_DIR = Path(__file__).resolve().parent.parent / "data_pipeline"
_SERVICES_DIR = Path(__file__).resolve().parent.parent / "app" / "services"


def _has_dataclass_field(cls: type, field_name: str) -> bool:
    """Check whether a frozen dataclass has a field by name.

    Required (no-default) fields on frozen dataclasses do not appear as
    class attributes, so ``hasattr(cls, name)`` returns False.  This
    helper inspects ``__dataclass_fields__`` instead.
    """
    fields = getattr(cls, "__dataclass_fields__", {})
    if field_name in fields:
        return True
    # Fallback for non-dataclass or Pydantic models
    return hasattr(cls, field_name)


# ===================================================================
# File-content checks — no hardcoded fallback data in downloaders
# ===================================================================


class TestNoHardcodedFallbacks:
    """Verify that downloader modules do not contain hardcoded fallback data."""

    def test_no_hardcoded_fallback_in_economy_downloader(self) -> None:
        source = (_PIPELINE_DIR / "economy_downloader.py").read_text(encoding="utf-8")
        assert "_FALLBACK" not in source, (
            "economy_downloader.py must not contain _FALLBACK constants — "
            "use live API with proper error handling instead"
        )

    def test_no_hardcoded_fallback_in_fred_downloader(self) -> None:
        source = (_PIPELINE_DIR / "fred_downloader.py").read_text(encoding="utf-8")
        assert "_FALLBACK_VALUES" not in source, (
            "fred_downloader.py must not contain _FALLBACK_VALUES — use FRED API with proper error handling instead"
        )

    def test_no_hardcoded_fallback_in_china_macro_downloader(self) -> None:
        source = (_PIPELINE_DIR / "china_macro_downloader.py").read_text(encoding="utf-8")
        assert "_FALLBACK_VALUES" not in source, (
            "china_macro_downloader.py must not contain _FALLBACK_VALUES — "
            "use World Bank API with proper error handling instead"
        )

    def test_no_hardcoded_fallback_in_trade_downloader(self) -> None:
        source = (_PIPELINE_DIR / "trade_downloader.py").read_text(encoding="utf-8")
        assert "_FALLBACK_TRADE_DATA" not in source, (
            "trade_downloader.py must not contain _FALLBACK_TRADE_DATA — "
            "use data.gov.hk API with proper error handling instead"
        )

    def test_no_hardcoded_fallback_in_rvd_downloader(self) -> None:
        source = (_PIPELINE_DIR / "rvd_downloader.py").read_text(encoding="utf-8")
        assert "_PRICE_INDEX_FALLBACK" not in source, (
            "rvd_downloader.py must not contain _PRICE_INDEX_FALLBACK — "
            "use RVD XLS parser with proper error handling instead"
        )

    def test_no_hardcoded_fallback_in_market_downloader(self) -> None:
        source = (_PIPELINE_DIR / "market_downloader.py").read_text(encoding="utf-8")
        assert "_HSI_MONTHLY" not in source, "market_downloader.py must not contain _HSI_MONTHLY hardcoded list"
        assert "hsi_monthly =" not in source, "market_downloader.py must not contain hsi_monthly = hardcoded assignment"


# ===================================================================
# Module-level checks — reference data separation
# ===================================================================


class TestReferenceDataSeparation:
    """Verify hk_reference_data only contains census, not historical seeds."""

    def test_hk_reference_data_has_only_census(self) -> None:
        from backend.data_pipeline import hk_reference_data

        assert hasattr(hk_reference_data, "seed_population_data"), (
            "hk_reference_data must export seed_population_data (census data)"
        )
        assert not hasattr(hk_reference_data, "seed_historical_data"), (
            "hk_reference_data must NOT export seed_historical_data — "
            "historical time series belong in hk_historical_seeder"
        )


# ===================================================================
# Forecaster integrity — no synthetic bootstrap
# ===================================================================


class TestForecasterIntegrity:
    """Verify TimeSeriesForecaster has no hardcoded baseline method."""

    def test_forecaster_no_hardcoded_baseline(self) -> None:
        from backend.app.services.time_series_forecaster import TimeSeriesForecaster

        assert not hasattr(TimeSeriesForecaster, "_hardcoded_baseline"), (
            "TimeSeriesForecaster must not have _hardcoded_baseline — all data must come from the database"
        )

    @pytest.mark.asyncio
    async def test_forecaster_refuses_insufficient_data(self, test_db) -> None:
        """Forecaster returns insufficient/no_data when <8 points in DB."""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        from backend.app.services.time_series_forecaster import TimeSeriesForecaster

        forecaster = TimeSeriesForecaster()

        # Insert fewer than 8 data points for a REAL metric (gdp_growth)
        # so the metric validation passes but the data threshold check triggers.
        for i in range(5):
            await test_db.execute(
                "INSERT INTO hk_data_snapshots "
                "(category, metric, value, source, period, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                ("gdp", "gdp_growth_rate", float(2.0 + i * 0.1), "test", f"2024-Q{i + 1}"),
            )
        await test_db.commit()

        # Patch get_db to return an async context manager yielding our test DB
        @asynccontextmanager
        async def _get_test_db():
            yield test_db

        with patch("backend.app.services.time_series_forecaster.get_db", _get_test_db):
            result = await forecaster.forecast("gdp_growth", horizon=4)

        assert result.data_quality in ("insufficient", "no_data"), (
            f"Expected data_quality='insufficient' or 'no_data' with <8 points, got '{result.data_quality}'"
        )
        assert len(result.points) == 0, "Forecaster must return empty points when data is insufficient"


# ===================================================================
# Result dataclass field checks — data quality metadata
# ===================================================================


class TestBacktestResultFields:
    """Verify BacktestResult carries required data-quality metadata."""

    def test_backtest_result_has_theils_u(self) -> None:
        from backend.app.services.backtester import BacktestResult

        assert _has_dataclass_field(BacktestResult, "theils_u"), (
            "BacktestResult must have theils_u field for relative accuracy measure"
        )

    def test_backtest_result_has_data_quality_flag(self) -> None:
        from backend.app.services.backtester import BacktestResult

        assert _has_dataclass_field(BacktestResult, "data_quality_flag"), (
            "BacktestResult must have data_quality_flag field (real_data | partial_real | insufficient)"
        )


class TestEnsembleResultFields:
    """Verify EnsembleResult carries data integrity scoring."""

    def test_ensemble_result_has_data_integrity_score(self) -> None:
        from backend.app.models.ensemble import EnsembleResult

        assert _has_dataclass_field(EnsembleResult, "data_integrity_score"), (
            "EnsembleResult must have data_integrity_score field (0.0 = all synthetic, 1.0 = all real data)"
        )


class TestForecastResultFields:
    """Verify ForecastResult carries data quality classification."""

    def test_forecast_result_has_data_quality(self) -> None:
        from backend.app.models.forecast import ForecastResult

        assert _has_dataclass_field(ForecastResult, "data_quality"), (
            "ForecastResult must have data_quality field (real_data | partial_real | insufficient | no_data)"
        )


# ===================================================================
# Consumer confidence proxy — derived data tagged correctly
# ===================================================================


class TestConsumerConfidenceProxy:
    """Verify censtatd_downloader tags derived data as 'derived_proxy'."""

    def test_consumer_confidence_tagged_derived_proxy(self) -> None:
        from backend.data_pipeline.censtatd_downloader import (
            CenstatdRecord,
            compute_consumer_confidence_proxy,
        )

        # Build minimal real-looking input records spanning 2 years
        # so that YoY retail calculation has at least 1 overlapping period.
        retail = tuple(
            CenstatdRecord(
                period=f"{year}-Q1",
                metric="retail_sales_index",
                value=100.0 + (year - 2023) * 5.0,
                unit="index",
                source="censtatd",
                source_url="https://example.com",
            )
            for year in (2023, 2024)
        )
        unemp = tuple(
            CenstatdRecord(
                period=f"{year}-Q1",
                metric="unemployment_rate",
                value=3.0,
                unit="percent",
                source="censtatd",
                source_url="https://example.com",
            )
            for year in (2023, 2024)
        )
        hsi = tuple(
            CenstatdRecord(
                period=f"{year}-Q1",
                metric="hsi_level",
                value=20000.0 + (year - 2023) * 1000.0,
                unit="index",
                source="hkma",
                source_url="https://example.com",
            )
            for year in (2023, 2024)
        )

        result = compute_consumer_confidence_proxy(retail, unemp, hsi)

        # Must produce at least 1 record for the overlapping period
        assert result.row_count > 0, (
            "compute_consumer_confidence_proxy should produce records when given overlapping quarterly data"
        )

        # Every output record must be tagged as derived_proxy
        for record in result.records:
            assert record.source == "derived_proxy", (
                f"Consumer confidence proxy record has source='{record.source}', expected 'derived_proxy'"
            )
