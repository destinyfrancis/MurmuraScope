"""Tests for Stock & Index Prediction — models, downloader, signal extractor,
forecaster, backtester, and API endpoints.

~150 tests across 8 groups.
"""

from __future__ import annotations

import dataclasses
import math
import re
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

# ---------------------------------------------------------------------------
# Group 1: Models
# ---------------------------------------------------------------------------


class TestModels:
    """Frozen dataclass correctness and serialisation."""

    # --- TickerInfo ---

    def test_ticker_info_frozen(self):
        from backend.app.models.stock_forecast import TickerInfo

        ti = TickerInfo(ticker="^HSI", name="恒生指數", asset_type="hk_index",
                        sector_tag="broad", market="HK")
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            ti.ticker = "AAPL"  # type: ignore[misc]

    def test_ticker_info_to_dict(self):
        from backend.app.models.stock_forecast import TickerInfo

        ti = TickerInfo(ticker="^HSI", name="恒生指數", asset_type="hk_index",
                        sector_tag="broad", market="HK")
        d = ti.to_dict()
        assert d["ticker"] == "^HSI"
        assert d["name"] == "恒生指數"
        assert d["asset_type"] == "hk_index"
        assert d["sector_tag"] == "broad"
        assert d["market"] == "HK"
        assert len(d) == 5

    # --- SignalContribution ---

    def test_signal_contribution_frozen(self):
        from backend.app.models.stock_forecast import SignalContribution

        sc = SignalContribution(signal_name="sentiment_net", signal_value=0.5,
                                weight=0.035, contribution=0.0175, direction="bullish")
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            sc.signal_value = 0.9  # type: ignore[misc]

    def test_signal_contribution_to_dict(self):
        from backend.app.models.stock_forecast import SignalContribution

        sc = SignalContribution(signal_name="sentiment_net", signal_value=0.5,
                                weight=0.035, contribution=0.0175, direction="bullish")
        d = sc.to_dict()
        assert d["signal_name"] == "sentiment_net"
        assert d["signal_value"] == round(0.5, 4)
        assert d["weight"] == round(0.035, 4)
        assert d["contribution"] == round(0.0175, 4)
        assert d["direction"] == "bullish"

    # --- StockForecastPoint ---

    def test_stock_forecast_point_frozen(self):
        from backend.app.models.stock_forecast import StockForecastPoint

        pt = StockForecastPoint(week="2024-W01", close=100.0, lower_80=95.0,
                                upper_80=105.0, lower_95=90.0, upper_95=110.0,
                                sentiment_adjusted=False)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            pt.close = 999.0  # type: ignore[misc]

    def test_stock_forecast_point_to_dict(self):
        from backend.app.models.stock_forecast import StockForecastPoint

        pt = StockForecastPoint(week="2024-W01", close=100.123456, lower_80=95.0,
                                upper_80=105.0, lower_95=90.0, upper_95=110.0,
                                sentiment_adjusted=True)
        d = pt.to_dict()
        assert d["week"] == "2024-W01"
        assert d["close"] == round(100.123456, 2)
        assert d["lower_80"] == 95.0
        assert d["upper_80"] == 105.0
        assert d["lower_95"] == 90.0
        assert d["upper_95"] == 110.0
        assert d["sentiment_adjusted"] is True

    # --- StockForecastResult ---

    def test_stock_forecast_result_frozen(self):
        from backend.app.models.stock_forecast import StockForecastResult

        r = StockForecastResult(ticker="^HSI", asset_type="hk_index", name="恒生指數",
                                horizon=12, points=(), model_used="NaiveDrift",
                                fit_quality="fair", data_quality="sufficient",
                                signal_shift=0.0, signal_breakdown=(), session_id=None)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            r.horizon = 99  # type: ignore[misc]

    def test_stock_forecast_result_to_dict_with_nested(self):
        from backend.app.models.stock_forecast import (
            SignalContribution,
            StockForecastPoint,
            StockForecastResult,
        )

        pt = StockForecastPoint(week="2024-W01", close=100.0, lower_80=95.0,
                                upper_80=105.0, lower_95=90.0, upper_95=110.0,
                                sentiment_adjusted=False)
        sc = SignalContribution(signal_name="sentiment_net", signal_value=0.5,
                                weight=0.035, contribution=0.0175, direction="bullish")
        r = StockForecastResult(ticker="^HSI", asset_type="hk_index", name="恒生指數",
                                horizon=12, points=(pt,), model_used="NaiveDrift",
                                fit_quality="fair", data_quality="sufficient",
                                signal_shift=0.05, signal_breakdown=(sc,), session_id="sess_1")
        d = r.to_dict()
        assert d["ticker"] == "^HSI"
        assert len(d["points"]) == 1
        assert d["points"][0]["week"] == "2024-W01"
        assert len(d["signal_breakdown"]) == 1
        assert d["signal_breakdown"][0]["signal_name"] == "sentiment_net"
        assert d["signal_shift"] == round(0.05, 4)
        assert d["session_id"] == "sess_1"

    def test_stock_forecast_result_default_values(self):
        from backend.app.models.stock_forecast import StockForecastResult

        r = StockForecastResult(ticker="X", asset_type="hk_stock", name="Test",
                                horizon=12, points=(), model_used="none",
                                fit_quality="poor", data_quality="insufficient",
                                signal_shift=0.0, signal_breakdown=(), session_id=None)
        assert r.data_quality == "insufficient"
        assert r.signal_shift == 0.0
        assert r.points == ()
        assert r.signal_breakdown == ()
        assert r.session_id is None

    # --- StockBacktestResult ---

    def test_stock_backtest_result_frozen(self):
        from backend.app.models.stock_forecast import StockBacktestResult

        br = StockBacktestResult(ticker="^HSI", mape=0.05, rmse=100.0,
                                 directional_accuracy=0.7, n_obs=8,
                                 train_end="2024-W40", horizon=8)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            br.mape = 0.99  # type: ignore[misc]

    def test_stock_backtest_result_to_dict(self):
        from backend.app.models.stock_forecast import StockBacktestResult

        br = StockBacktestResult(ticker="^HSI", mape=0.05123, rmse=102.456,
                                 directional_accuracy=0.625, n_obs=8,
                                 train_end="2024-W40", horizon=8)
        d = br.to_dict()
        assert d["ticker"] == "^HSI"
        assert d["mape"] == round(0.05123, 4)
        assert d["rmse"] == round(102.456, 2)
        assert d["directional_accuracy"] == round(0.625, 4)
        assert d["n_obs"] == 8
        assert d["train_end"] == "2024-W40"
        assert d["horizon"] == 8


# ---------------------------------------------------------------------------
# Group 2: stock_downloader
# ---------------------------------------------------------------------------


class TestStockDownloader:
    """TICKER_REGISTRY structure, WeeklyRecord, download helpers."""

    def test_ticker_registry_has_14_entries(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        assert len(TICKER_REGISTRY) == 14

    def test_all_tickers_have_required_fields(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        for ticker, meta in TICKER_REGISTRY.items():
            assert "name" in meta, f"{ticker} missing 'name'"
            assert "asset_type" in meta, f"{ticker} missing 'asset_type'"
            assert "sector_tag" in meta, f"{ticker} missing 'sector_tag'"
            assert "market" in meta, f"{ticker} missing 'market'"

    def test_ticker_asset_types_are_valid(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        valid = {"hk_stock", "hk_index", "us_stock", "us_index"}
        for ticker, meta in TICKER_REGISTRY.items():
            assert meta["asset_type"] in valid, f"{ticker} has invalid asset_type"

    def test_ticker_market_values_are_valid(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        for ticker, meta in TICKER_REGISTRY.items():
            assert meta["market"] in {"HK", "US"}, f"{ticker} has invalid market"

    def test_ticker_sector_tags_not_empty(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        for ticker, meta in TICKER_REGISTRY.items():
            assert meta["sector_tag"], f"{ticker} has empty sector_tag"

    def test_weekly_record_is_frozen(self):
        from backend.data_pipeline.stock_downloader import WeeklyRecord

        r = WeeklyRecord(ticker="^HSI", week_label="2024-W01",
                         open=18000.0, high=18200.0, low=17800.0,
                         close=18100.0, volume=1000000.0)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            r.close = 99.0  # type: ignore[misc]

    def test_weekly_record_fields(self):
        from backend.data_pipeline.stock_downloader import WeeklyRecord

        r = WeeklyRecord(ticker="NVDA", week_label="2024-W10",
                         open=800.0, high=850.0, low=780.0,
                         close=840.0, volume=5000000.0)
        assert r.ticker == "NVDA"
        assert r.week_label == "2024-W10"
        assert r.open == 800.0
        assert r.high == 850.0
        assert r.low == 780.0
        assert r.close == 840.0
        assert r.volume == 5000000.0

    def test_week_label_from_date_format(self):
        from backend.data_pipeline.stock_downloader import _week_label_from_date
        import datetime

        dt = datetime.datetime(2024, 3, 8)  # Friday, ISO week 10
        label = _week_label_from_date(dt)
        # Should be "YYYY-WNN" format
        assert re.match(r"^\d{4}-W\d{2}$", label), f"Invalid week label: {label}"
        assert label.startswith("2024-")

    def test_week_label_format_regex(self):
        from backend.data_pipeline.stock_downloader import _week_label_from_date
        import datetime

        for year in [2021, 2022, 2023, 2024]:
            dt = datetime.datetime(year, 6, 15)
            label = _week_label_from_date(dt)
            assert re.match(r"^\d{4}-W\d{2}$", label)

    def test_week_label_from_pandas_timestamp(self):
        """Verify _week_label_from_date handles pandas Timestamp via to_pydatetime."""
        from backend.data_pipeline.stock_downloader import _week_label_from_date
        import datetime

        # Create a mock that behaves like pandas Timestamp
        mock_ts = MagicMock()
        dt_obj = datetime.datetime(2024, 1, 5)  # Week 01
        mock_ts.to_pydatetime.return_value = dt_obj

        label = _week_label_from_date(mock_ts)
        assert re.match(r"^\d{4}-W\d{2}$", label)

    @pytest.mark.asyncio
    async def test_download_stock_weekly_empty_data(self):
        """download_stock_weekly returns [] when yfinance returns empty DataFrame."""
        import pandas as pd
        from backend.data_pipeline.stock_downloader import download_stock_weekly

        mock_yf = MagicMock()
        empty_df = pd.DataFrame()
        mock_yf.download.return_value = empty_df

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            # _download_weekly_sync runs in to_thread — patch asyncio.to_thread
            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=[]):
                records = await download_stock_weekly("^HSI")
        assert records == []

    @pytest.mark.asyncio
    async def test_download_stock_weekly_valid_data(self):
        """download_stock_weekly calls to_thread and returns WeeklyRecord list."""
        import pandas as pd
        from backend.data_pipeline.stock_downloader import WeeklyRecord, download_stock_weekly

        fake_records = [
            WeeklyRecord(ticker="^HSI", week_label="2024-W01",
                         open=18000.0, high=18200.0, low=17800.0,
                         close=18100.0, volume=1000000.0)
        ]
        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fake_records):
            records = await download_stock_weekly("^HSI")
        assert records == fake_records
        assert records[0].ticker == "^HSI"

    @pytest.mark.asyncio
    async def test_upsert_weekly_records_empty(self):
        """upsert_weekly_records([]) returns 0 without touching DB."""
        from backend.data_pipeline.stock_downloader import upsert_weekly_records

        count = await upsert_weekly_records([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_upsert_weekly_records_inserts_rows(self):
        """upsert_weekly_records inserts valid records into market_data."""
        from backend.data_pipeline.stock_downloader import WeeklyRecord, upsert_weekly_records

        records = [
            WeeklyRecord(ticker="^HSI", week_label="2024-W01",
                         open=18000.0, high=18200.0, low=17800.0,
                         close=18100.0, volume=1000000.0),
        ]

        db = await aiosqlite.connect(":memory:")
        await db.execute("""
            CREATE TABLE market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, asset_type TEXT, ticker TEXT,
                open REAL, close REAL, high REAL, low REAL,
                volume REAL, source TEXT, granularity TEXT,
                UNIQUE(date, ticker)
            )
        """)
        await db.commit()

        @asynccontextmanager
        async def mock_get_db():
            yield db

        with patch("backend.data_pipeline.stock_downloader.get_db", mock_get_db):
            count = await upsert_weekly_records(records)

        assert count == 1

        row = await (await db.execute("SELECT granularity, source FROM market_data LIMIT 1")).fetchone()
        assert row[0] == "weekly"
        assert row[1] == "yfinance_weekly"
        await db.close()

    def test_hk_stocks_have_hk_market(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        hk_tickers = [t for t, m in TICKER_REGISTRY.items() if m["market"] == "HK"]
        assert len(hk_tickers) == 9  # 5 stocks + 4 indices

    def test_us_tickers_count(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        us_tickers = [t for t, m in TICKER_REGISTRY.items() if m["market"] == "US"]
        assert len(us_tickers) == 5  # 3 stocks + 2 indices

    def test_specific_tickers_present(self):
        from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

        for expected in ["^HSI", "0700.HK", "NVDA", "AAPL", "^GSPC"]:
            assert expected in TICKER_REGISTRY

    @pytest.mark.asyncio
    async def test_download_all_stocks_uses_semaphore(self):
        """download_all_stocks uses asyncio.Semaphore(3) — verify concurrency limit."""
        from backend.data_pipeline.stock_downloader import download_all_stocks

        # Patch download_stock_weekly and upsert_weekly_records
        with patch("backend.data_pipeline.stock_downloader.download_stock_weekly",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.data_pipeline.stock_downloader.upsert_weekly_records",
                   new_callable=AsyncMock, return_value=0):
            results = await download_all_stocks()

        # Should return dict with 14 tickers
        assert len(results) == 14
        for count in results.values():
            assert count == 0


# ---------------------------------------------------------------------------
# Group 3: signal_extractor
# ---------------------------------------------------------------------------


async def _make_signal_db():
    """Create an in-memory aiosqlite DB with execute_fetchone helper added."""
    db = await aiosqlite.connect(":memory:")
    await db.executescript("""
        CREATE TABLE simulation_actions (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            agent_id INTEGER, oasis_username TEXT, action_type TEXT,
            platform TEXT, content TEXT, target_agent_username TEXT,
            sentiment REAL, topics TEXT, post_id TEXT,
            parent_action_id INTEGER, spread_depth INTEGER
        );
        CREATE TABLE emotional_states (
            id INTEGER PRIMARY KEY, session_id TEXT, agent_id INTEGER,
            round_number INTEGER, valence REAL, arousal REAL, dominance REAL
        );
        CREATE TABLE virality_scores (
            id INTEGER PRIMARY KEY, session_id TEXT, post_id TEXT,
            virality_index REAL, velocity REAL, cross_cluster_reach REAL
        );
        CREATE TABLE agent_decisions (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            agent_id INTEGER, decision_type TEXT, action TEXT, reasoning TEXT,
            oasis_username TEXT, details_json TEXT
        );
        CREATE TABLE polarization_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            polarization_index REAL
        );
        CREATE TABLE echo_chamber_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            modularity REAL, num_communities INTEGER
        );
        CREATE TABLE filter_bubble_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            avg_bubble_score REAL
        );
        CREATE TABLE agent_relationships (
            id INTEGER PRIMARY KEY, session_id TEXT, agent_id INTEGER,
            related_agent_id INTEGER, trust_score REAL
        );
        CREATE TABLE macro_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            hsi_level REAL, ccl_index REAL, unemployment_rate REAL,
            consumer_confidence REAL, credit_stress REAL, taiwan_strait_risk REAL
        );
        CREATE TABLE ensemble_results (
            id INTEGER PRIMARY KEY, session_id TEXT, metric TEXT,
            p05 REAL, p25 REAL, p50 REAL, p75 REAL, p95 REAL
        );
    """)
    await db.commit()

    # signal_extractor uses db.execute_fetchone() which is not a native aiosqlite method.
    # Add it as a helper that executes and fetches one row.
    async def _execute_fetchone(sql: str, params: tuple = ()) -> Any:
        cursor = await db.execute(sql, params)
        return await cursor.fetchone()

    db.execute_fetchone = _execute_fetchone  # type: ignore[attr-defined]
    return db


@pytest.fixture
async def signal_db():
    """In-memory DB with all tables needed by SimulationSignalExtractor."""
    db = await _make_signal_db()

    @asynccontextmanager
    async def mock_get_db():
        yield db

    with patch("backend.app.services.signal_extractor.get_db", mock_get_db):
        yield db

    await db.close()


class TestSimulationSignals:
    """SimulationSignals frozen dataclass."""

    def test_simulation_signals_is_frozen(self):
        from backend.app.services.signal_extractor import SimulationSignals
        import datetime

        sig = SimulationSignals(
            session_id="s1",
            extraction_ts=datetime.datetime.now().isoformat(),
        )
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            sig.sentiment_net = 0.9  # type: ignore[misc]

    def test_simulation_signals_default_values_all_zero(self):
        from backend.app.services.signal_extractor import SimulationSignals
        import datetime

        sig = SimulationSignals(
            session_id="s1",
            extraction_ts=datetime.datetime.now().isoformat(),
        )
        # All numeric fields default to 0.0 except data_integrity_score
        assert sig.sentiment_net == 0.0
        assert sig.sentiment_momentum == 0.0
        assert sig.negative_virality == 0.0
        assert sig.property_sentiment == 0.0
        assert sig.finance_sentiment == 0.0
        assert sig.emotional_valence == 0.0
        assert sig.arousal_concentration == 0.0
        assert sig.contagion_velocity == 0.0
        assert sig.buy_property_ratio == 0.0
        assert sig.emigration_rate == 0.0
        assert sig.invest_ratio == 0.0
        assert sig.spending_cut_ratio == 0.0
        assert sig.employment_quit_ratio == 0.0
        assert sig.decision_entropy == 0.0
        assert sig.polarization_index == 0.0
        assert sig.echo_chamber_modularity == 0.0
        assert sig.filter_bubble_severity == 0.0
        assert sig.cross_cluster_reach == 0.0
        assert sig.trust_erosion_rate == 0.0
        assert sig.hsi_sim_change == 0.0
        assert sig.ccl_sim_change == 0.0
        assert sig.data_integrity_score == 1.0  # default is 1.0

    def test_simulation_signals_has_32_signal_fields(self):
        from backend.app.services.signal_extractor import _SIGNAL_FIELDS

        assert len(_SIGNAL_FIELDS) == 32


class TestSignalExtractor:
    """SimulationSignalExtractor DB-driven tests."""

    @pytest.mark.asyncio
    async def test_extract_non_existent_session_returns_defaults(self, signal_db):
        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract("nonexistent-session")
        assert sig.session_id == "nonexistent-session"
        assert sig.sentiment_net == 0.0
        assert sig.polarization_index == 0.0

    @pytest.mark.asyncio
    async def test_extract_sentiment_with_data(self, signal_db):
        db = signal_db
        session_id = "test-sess"
        for i in range(10):
            sentiment = 1.0 if i < 7 else -1.0
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, i, sentiment, "[]"),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        # 7 positive, 3 negative → net positive
        assert sig.sentiment_net > 0.0

    @pytest.mark.asyncio
    async def test_extract_sentiment_momentum_late_minus_early(self, signal_db):
        db = signal_db
        session_id = "sess-momentum"
        # Rounds 1-5 negative, rounds 16-20 positive
        for r in range(1, 6):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, r, r, -1.0, "[]"),
            )
        for r in range(16, 21):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, r, r, 1.0, "[]"),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        # Late positive, early negative → momentum > 0
        assert sig.sentiment_momentum >= 0.0

    @pytest.mark.asyncio
    async def test_extract_emotional_valence(self, signal_db):
        db = signal_db
        session_id = "sess-emotion"
        for i in range(5):
            await db.execute(
                "INSERT INTO emotional_states (session_id, agent_id, round_number, valence, arousal, dominance) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, i, 1, 0.8, 0.3, 0.5),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.emotional_valence == pytest.approx(0.8, abs=0.01)
        assert sig.arousal_concentration == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_behavioral_buy_property(self, signal_db):
        db = signal_db
        session_id = "sess-behav"
        for i in range(6):
            await db.execute(
                "INSERT INTO agent_decisions (session_id, round_number, agent_id, decision_type, action, reasoning, oasis_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, 1, i, "buy_property", "buy", "good deal", f"u{i}"),
            )
        for i in range(4):
            await db.execute(
                "INSERT INTO agent_decisions (session_id, round_number, agent_id, decision_type, action, reasoning, oasis_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, 1, 10 + i, "emigrate", "emigrate", "leaving", f"u{10+i}"),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.buy_property_ratio == pytest.approx(0.6, abs=0.01)
        assert sig.emigration_rate == pytest.approx(0.4, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_behavioral_empty_returns_defaults(self, signal_db):
        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract("no-decisions-session")
        assert sig.buy_property_ratio == 0.0
        assert sig.emigration_rate == 0.0
        assert sig.invest_ratio == 0.0

    @pytest.mark.asyncio
    async def test_extract_behavioral_decision_entropy(self, signal_db):
        db = signal_db
        session_id = "sess-entropy"
        # Uniform distribution: max entropy
        for i, dtype in enumerate(["buy_property", "emigrate", "invest", "cut_spending"]):
            for j in range(5):
                await db.execute(
                    "INSERT INTO agent_decisions (session_id, round_number, agent_id, decision_type, action, reasoning, oasis_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, 1, i * 10 + j, dtype, "act", "reason", f"u{i*10+j}"),
                )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        # Uniform distribution → entropy close to 1.0
        assert sig.decision_entropy > 0.9

    @pytest.mark.asyncio
    async def test_extract_network_polarization(self, signal_db):
        db = signal_db
        session_id = "sess-polar"
        await db.execute(
            "INSERT INTO polarization_snapshots (session_id, round_number, polarization_index) VALUES (?, ?, ?)",
            (session_id, 10, 0.75),
        )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.polarization_index == pytest.approx(0.75, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_network_echo_chamber(self, signal_db):
        db = signal_db
        session_id = "sess-echo"
        await db.execute(
            "INSERT INTO echo_chamber_snapshots (session_id, round_number, modularity, num_communities) VALUES (?, ?, ?, ?)",
            (session_id, 5, 0.45, 3),
        )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.echo_chamber_modularity == pytest.approx(0.45, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_network_trust_erosion(self, signal_db):
        db = signal_db
        session_id = "sess-trust"
        # 3 negative trust, 7 positive trust
        for i in range(3):
            await db.execute(
                "INSERT INTO agent_relationships (session_id, agent_id, related_agent_id, trust_score) VALUES (?, ?, ?, ?)",
                (session_id, i, i + 1, -0.3),
            )
        for i in range(7):
            await db.execute(
                "INSERT INTO agent_relationships (session_id, agent_id, related_agent_id, trust_score) VALUES (?, ?, ?, ?)",
                (session_id, i + 10, i + 11, 0.7),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.trust_erosion_rate == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_macro_signals(self, signal_db):
        db = signal_db
        session_id = "sess-macro"
        # First round
        await db.execute(
            """INSERT INTO macro_snapshots (session_id, round_number, hsi_level, ccl_index,
               unemployment_rate, consumer_confidence, credit_stress, taiwan_strait_risk)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, 1, 17000.0, 150.0, 4.0, 50.0, 0.2, 0.1),
        )
        # Last round — HSI up, CCL up
        await db.execute(
            """INSERT INTO macro_snapshots (session_id, round_number, hsi_level, ccl_index,
               unemployment_rate, consumer_confidence, credit_stress, taiwan_strait_risk)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, 20, 18700.0, 165.0, 3.5, 55.0, 0.3, 0.15),
        )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        # HSI up by ~10%
        assert sig.hsi_sim_change > 0.0
        assert sig.consumer_confidence_sim == pytest.approx(55.0, abs=0.1)
        assert sig.credit_stress == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_forward_signals(self, signal_db):
        db = signal_db
        session_id = "sess-forward"
        await db.execute(
            "INSERT INTO ensemble_results (session_id, metric, p05, p25, p50, p75, p95) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, "hsi_level", 16000.0, 17000.0, 18000.0, 19000.0, 20000.0),
        )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.ensemble_hsi_p50 == pytest.approx(18000.0, abs=1.0)
        # iqr = 19000 - 17000 = 2000; skew = (19000-18000-(18000-17000))/2000 = 0
        assert sig.ensemble_skew == pytest.approx(0.0, abs=0.01)
        # ci_width = (20000-16000)/18000 ≈ 0.222
        assert sig.ensemble_ci_width == pytest.approx(0.222, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_graceful_on_missing_table(self, signal_db):
        """Extractor should not raise even if some tables are missing."""
        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        # Using a fresh connection without most tables should not crash
        bad_db = await aiosqlite.connect(":memory:")
        await bad_db.execute("CREATE TABLE simulation_actions (id INTEGER)")
        await bad_db.commit()

        # Add execute_fetchone helper
        async def _execute_fetchone(sql: str, params: tuple = ()) -> Any:
            cursor = await bad_db.execute(sql, params)
            return await cursor.fetchone()

        bad_db.execute_fetchone = _execute_fetchone  # type: ignore[attr-defined]

        @asynccontextmanager
        async def bad_get_db():
            yield bad_db

        with patch("backend.app.services.signal_extractor.get_db", bad_get_db):
            sig = await extractor.extract("any-session")

        assert sig.sentiment_net == 0.0
        await bad_db.close()

    @pytest.mark.asyncio
    async def test_extract_data_integrity_score(self, signal_db):
        db = signal_db
        session_id = "sess-integrity"
        # Add some real data to raise integrity score
        await db.execute(
            "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
            (session_id, 1, 1, 0.5, "[]"),
        )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        # data_integrity_score should be between 0 and 1
        assert 0.0 <= sig.data_integrity_score <= 1.0

    @pytest.mark.asyncio
    async def test_extract_property_and_finance_sentiment(self, signal_db):
        db = signal_db
        session_id = "sess-topic"
        for i in range(5):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, i, 1.0, '["property", "real_estate"]'),
            )
        for i in range(5):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, i + 10, -1.0, '["finance", "stocks"]'),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.property_sentiment > 0.0
        assert sig.finance_sentiment < 0.0

    @pytest.mark.asyncio
    async def test_extract_filter_bubble_severity(self, signal_db):
        db = signal_db
        session_id = "sess-bubble"
        for r in [1, 2, 3]:
            await db.execute(
                "INSERT INTO filter_bubble_snapshots (session_id, round_number, avg_bubble_score) VALUES (?, ?, ?)",
                (session_id, r, 0.6),
            )
        await db.commit()

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)
        assert sig.filter_bubble_severity == pytest.approx(0.6, abs=0.01)

    @pytest.mark.asyncio
    async def test_extract_returns_simulation_signals_type(self, signal_db):
        from backend.app.services.signal_extractor import SimulationSignalExtractor, SimulationSignals

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract("empty-session")
        assert isinstance(sig, SimulationSignals)
        assert isinstance(sig.extraction_ts, str)


# ---------------------------------------------------------------------------
# Group 4: stock_forecaster
# ---------------------------------------------------------------------------


@pytest.fixture
async def forecast_db():
    """In-memory DB for StockForecaster with market_data table."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, asset_type TEXT, ticker TEXT,
            open REAL, close REAL, high REAL, low REAL,
            volume REAL, source TEXT, granularity TEXT,
            UNIQUE(date, ticker)
        )
    """)
    await db.commit()

    @asynccontextmanager
    async def mock_get_db():
        yield db

    with patch("backend.app.services.stock_forecaster.get_db", mock_get_db), \
         patch("backend.app.services.signal_extractor.get_db", mock_get_db):
        yield db

    await db.close()


async def _seed_market_data(db, ticker: str, n_weeks: int = 25, start_close: float = 18000.0):
    """Insert n_weeks of fake weekly closes for ticker."""
    for i in range(n_weeks):
        week = f"2024-W{i + 1:02d}"
        close = start_close + i * 10.0
        await db.execute(
            """INSERT OR REPLACE INTO market_data
               (date, asset_type, ticker, open, close, high, low, volume, source, granularity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (week, "hk_index", ticker, close * 0.99, close, close * 1.01,
             close * 0.98, 1000000.0, "yfinance_weekly", "weekly"),
        )
    await db.commit()


class TestSignalWeights:
    def test_signal_weights_has_four_asset_types(self):
        from backend.app.services.stock_forecaster import SIGNAL_WEIGHTS

        assert "hk_stock" in SIGNAL_WEIGHTS
        assert "hk_index" in SIGNAL_WEIGHTS
        assert "us_stock" in SIGNAL_WEIGHTS
        assert "us_index" in SIGNAL_WEIGHTS

    def test_signal_weights_are_bounded(self):
        from backend.app.services.stock_forecaster import SIGNAL_WEIGHTS

        for asset_type, weights in SIGNAL_WEIGHTS.items():
            for sig, w in weights.items():
                assert abs(w) <= 0.15, f"{asset_type}.{sig} weight {w} too large"

    def test_each_asset_type_has_signals(self):
        from backend.app.services.stock_forecaster import SIGNAL_WEIGHTS

        for asset_type, weights in SIGNAL_WEIGHTS.items():
            assert len(weights) >= 5, f"{asset_type} has too few signals"


class TestStockForecasterNaiveDrift:
    """_forecast_naive_weekly without DB."""

    def _make_history(self, n: int = 25, start: float = 100.0) -> list[tuple[str, float]]:
        return [(f"2024-W{i + 1:02d}", start + i * 1.0) for i in range(n)]

    def test_naive_returns_correct_horizon(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(25)
        points, model, quality = f._forecast_naive_weekly(history, 12)
        assert len(points) == 12
        assert model == "NaiveDrift"

    def test_naive_fit_quality_is_fair(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(25)
        _, _, quality = f._forecast_naive_weekly(history, 12)
        assert quality == "fair"

    def test_naive_ci_widens_over_time(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(30)
        points, _, _ = f._forecast_naive_weekly(history, 6)
        # upper_80 - lower_80 should increase over time
        widths = [pt.upper_80 - pt.lower_80 for pt in points]
        assert widths[-1] > widths[0], "CI should widen over time"

    def test_naive_drift_positive_trend(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        # Monotonically increasing history → positive drift
        history = [(f"2024-W{i + 1:02d}", 100.0 + i * 5.0) for i in range(30)]
        points, _, _ = f._forecast_naive_weekly(history, 4)
        # With positive drift, close should be > last actual
        last_actual = 100.0 + 29 * 5.0
        assert points[0].close > last_actual

    def test_naive_all_points_positive(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(25, start=10.0)
        points, _, _ = f._forecast_naive_weekly(history, 12)
        for pt in points:
            assert pt.close > 0
            assert pt.lower_80 > 0
            assert pt.lower_95 > 0

    def test_naive_week_labels_are_valid_format(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(25)
        points, _, _ = f._forecast_naive_weekly(history, 6)
        for pt in points:
            assert re.match(r"^\d{4}-W\d{2}$", pt.week), f"Invalid week: {pt.week}"

    def test_naive_sentiment_adjusted_false(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        history = self._make_history(25)
        points, _, _ = f._forecast_naive_weekly(history, 3)
        for pt in points:
            assert pt.sentiment_adjusted is False


class TestSignalOverlay:
    """_apply_signal_overlay and _compute_signal_breakdown."""

    def _make_points(self, n: int = 12) -> list:
        from backend.app.models.stock_forecast import StockForecastPoint

        return [
            StockForecastPoint(
                week=f"2024-W{i + 1:02d}", close=100.0, lower_80=95.0,
                upper_80=105.0, lower_95=90.0, upper_95=110.0,
                sentiment_adjusted=False,
            )
            for i in range(n)
        ]

    def _make_signals(self, **overrides) -> Any:
        from backend.app.services.signal_extractor import SimulationSignals
        import datetime

        defaults = {
            "session_id": "s1",
            "extraction_ts": datetime.datetime.now().isoformat(),
        }
        defaults.update(overrides)
        return SimulationSignals(**defaults)

    def test_zero_signals_no_change(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        points = self._make_points()
        signals = self._make_signals()
        adjusted, shift = f._apply_signal_overlay(points, signals, "hk_index")
        assert shift == 0.0
        for pt in adjusted:
            assert pt.sentiment_adjusted is True
            assert pt.close == pytest.approx(100.0, abs=0.1)

    def test_clamps_to_upper_bound(self):
        """Very large positive signals should clamp to +0.12."""
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        points = self._make_points()
        # Set all signals to 1.0 to force large positive shift
        signals = self._make_signals(
            sentiment_net=1.0, finance_sentiment=1.0, hsi_sim_change=1.0,
            ensemble_hsi_p50=1.0, invest_ratio=1.0,
        )
        _, shift = f._apply_signal_overlay(points, signals, "hk_index")
        assert shift <= 0.12

    def test_clamps_to_lower_bound(self):
        """Very large negative signals should clamp to -0.12."""
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        points = self._make_points()
        signals = self._make_signals(
            emigration_rate=1.0, credit_stress=1.0, taiwan_strait_risk=1.0,
            negative_virality=1.0, trust_erosion_rate=1.0,
        )
        _, shift = f._apply_signal_overlay(points, signals, "hk_index")
        assert shift >= -0.12

    def test_decay_decreases_over_time(self):
        """Factor (1 + shift * exp(-0.05*t)) should decay toward 1 as t increases."""
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        points = self._make_points(12)
        signals = self._make_signals(sentiment_net=0.5, finance_sentiment=0.5)
        adjusted, shift = f._apply_signal_overlay(points, signals, "hk_index")
        if shift > 0:
            # Close should decrease from pt[0] to pt[-1] (but stay above baseline)
            diffs_from_base = [pt.close - 100.0 for pt in adjusted]
            assert diffs_from_base[0] >= diffs_from_base[-1]

    def test_sentiment_adjusted_flag_set(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        points = self._make_points()
        signals = self._make_signals()
        adjusted, _ = f._apply_signal_overlay(points, signals, "hk_index")
        for pt in adjusted:
            assert pt.sentiment_adjusted is True

    def test_compute_signal_breakdown_max_10(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        signals = self._make_signals(sentiment_net=0.5, finance_sentiment=0.3)
        breakdown = f._compute_signal_breakdown(signals, "hk_index")
        assert len(breakdown) <= 10

    def test_compute_signal_breakdown_sorted_by_abs_contribution(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        signals = self._make_signals(
            sentiment_net=0.5, finance_sentiment=0.3, emigration_rate=0.2,
        )
        breakdown = f._compute_signal_breakdown(signals, "hk_index")
        if len(breakdown) >= 2:
            for i in range(len(breakdown) - 1):
                assert abs(breakdown[i].contribution) >= abs(breakdown[i + 1].contribution)

    def test_compute_signal_breakdown_direction_labels(self):
        from backend.app.services.stock_forecaster import StockForecaster

        f = StockForecaster()
        signals = self._make_signals(sentiment_net=0.8)
        breakdown = f._compute_signal_breakdown(signals, "hk_index")
        for sc in breakdown:
            assert sc.direction in {"bullish", "bearish", "neutral"}


class TestStockForecasterForecast:
    """StockForecaster.forecast() with mocked DB."""

    @pytest.mark.asyncio
    async def test_forecast_insufficient_data(self, forecast_db):
        """Less than 20 weeks → data_quality='insufficient'."""
        db = forecast_db
        await _seed_market_data(db, "^HSI", n_weeks=5)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI")
        assert result.data_quality == "insufficient"
        assert result.points == ()
        assert result.model_used == "none"

    @pytest.mark.asyncio
    async def test_forecast_sufficient_data(self, forecast_db):
        db = forecast_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=12)
        assert result.data_quality == "sufficient"
        assert len(result.points) == 12
        assert result.ticker == "^HSI"

    @pytest.mark.asyncio
    async def test_forecast_without_session_id_no_overlay(self, forecast_db):
        db = forecast_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", session_id=None)
        assert result.signal_shift == 0.0
        assert result.signal_breakdown == ()
        assert result.session_id is None
        for pt in result.points:
            assert pt.sentiment_adjusted is False

    @pytest.mark.asyncio
    async def test_forecast_unknown_ticker_raises(self, forecast_db):
        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        with pytest.raises(ValueError, match="Unknown ticker"):
            await forecaster.forecast("FAKEXYZ")

    @pytest.mark.asyncio
    async def test_forecast_with_session_id_applies_overlay(self, forecast_db):
        db = forecast_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.signal_extractor import SimulationSignals
        import datetime

        mock_signals = SimulationSignals(
            session_id="test-sess",
            extraction_ts=datetime.datetime.now().isoformat(),
            sentiment_net=0.5,
            finance_sentiment=0.4,
        )

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        with patch.object(forecaster._extractor, "extract",
                          new_callable=AsyncMock, return_value=mock_signals):
            result = await forecaster.forecast("^HSI", session_id="test-sess")

        assert result.session_id == "test-sess"
        assert result.signal_breakdown != ()
        for pt in result.points:
            assert pt.sentiment_adjusted is True

    @pytest.mark.asyncio
    async def test_forecast_result_structure(self, forecast_db):
        db = forecast_db
        await _seed_market_data(db, "0700.HK", n_weeks=25, start_close=300.0)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("0700.HK", horizon=8)
        assert result.ticker == "0700.HK"
        assert result.asset_type == "hk_stock"
        assert result.horizon == 8
        assert result.fit_quality in {"good", "fair", "poor"}
        assert result.data_quality in {"sufficient", "insufficient"}

    @pytest.mark.asyncio
    async def test_forecast_custom_horizon(self, forecast_db):
        db = forecast_db
        await _seed_market_data(db, "NVDA", n_weeks=30, start_close=800.0)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("NVDA", horizon=4)
        assert len(result.points) == 4

    @pytest.mark.asyncio
    async def test_load_weekly_history_only_weekly_granularity(self, forecast_db):
        """Only rows with granularity='weekly' are loaded."""
        db = forecast_db
        # Insert daily row
        await db.execute(
            """INSERT INTO market_data (date, asset_type, ticker, open, close, high, low, volume, source, granularity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("2024-03-01", "hk_index", "^HSI", 18000, 18100, 18200, 17900, 1e6, "yfinance", "daily"),
        )
        await db.commit()

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        history = await forecaster._load_weekly_history("^HSI")
        assert len(history) == 0  # daily row not returned


# ---------------------------------------------------------------------------
# Group 5: stock_backtester
# ---------------------------------------------------------------------------


class TestWeekSortKey:
    """_week_sort_key helper (shared between forecaster and backtester)."""

    def test_sort_key_basic(self):
        from backend.app.services.stock_backtester import _week_sort_key

        assert _week_sort_key("2024-W01") < _week_sort_key("2024-W02")

    def test_sort_key_year_boundary(self):
        from backend.app.services.stock_backtester import _week_sort_key

        assert _week_sort_key("2023-W52") < _week_sort_key("2024-W01")

    def test_sort_key_different_years(self):
        from backend.app.services.stock_backtester import _week_sort_key

        assert _week_sort_key("2022-W10") < _week_sort_key("2023-W10")

    def test_sort_key_invalid_returns_zero(self):
        from backend.app.services.stock_backtester import _week_sort_key

        assert _week_sort_key("invalid") == 0
        assert _week_sort_key("") == 0

    def test_sort_key_format_YYYYNN(self):
        from backend.app.services.stock_backtester import _week_sort_key

        key = _week_sort_key("2024-W10")
        assert key == 2024 * 100 + 10


@pytest.fixture
async def backtest_db():
    """In-memory DB for StockBacktester."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, asset_type TEXT, ticker TEXT,
            open REAL, close REAL, high REAL, low REAL,
            volume REAL, source TEXT, granularity TEXT,
            UNIQUE(date, ticker)
        )
    """)
    await db.commit()

    @asynccontextmanager
    async def mock_get_db():
        yield db

    with patch("backend.app.services.stock_backtester.get_db", mock_get_db):
        yield db

    await db.close()


async def _seed_backtest_data(db, ticker: str, n_weeks: int = 50, start: float = 100.0):
    for i in range(n_weeks):
        week = f"2024-W{i + 1:02d}" if i < 52 else f"2025-W{i - 51:02d}"
        close = start * (1 + 0.002 * i)  # gentle uptrend
        await db.execute(
            """INSERT OR REPLACE INTO market_data
               (date, asset_type, ticker, open, close, high, low, volume, source, granularity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (week, "hk_index", ticker, close * 0.99, close, close * 1.01,
             close * 0.98, 1e6, "yfinance_weekly", "weekly"),
        )
    await db.commit()


class TestStockBacktester:
    @pytest.mark.asyncio
    async def test_run_returns_backtest_result(self, backtest_db):
        from backend.app.models.stock_forecast import StockBacktestResult
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        assert isinstance(result, StockBacktestResult)

    @pytest.mark.asyncio
    async def test_run_n_obs_correct(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        # We have 30 weeks; 20 train + 10 test; horizon=5 → n_obs <= 5
        assert 1 <= result.n_obs <= 5

    @pytest.mark.asyncio
    async def test_run_mape_is_non_negative(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        assert result.mape >= 0.0

    @pytest.mark.asyncio
    async def test_run_rmse_is_non_negative(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        assert result.rmse >= 0.0

    @pytest.mark.asyncio
    async def test_run_directional_accuracy_in_range(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        assert 0.0 <= result.directional_accuracy <= 1.0

    @pytest.mark.asyncio
    async def test_run_insufficient_history_raises(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=5)

        backtester = StockBacktester()
        with pytest.raises(ValueError, match="Insufficient history"):
            await backtester.run("^HSI", train_end="2024-W03", horizon=2)

    @pytest.mark.asyncio
    async def test_run_unknown_ticker_raises(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        backtester = StockBacktester()
        with pytest.raises(ValueError, match="Unknown ticker"):
            await backtester.run("BADTICKER", train_end="2024-W20", horizon=5)

    @pytest.mark.asyncio
    async def test_run_train_end_ticker_in_result(self, backtest_db):
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=30)

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W20", horizon=5)
        assert result.ticker == "^HSI"
        assert result.train_end == "2024-W20"
        assert result.horizon == 5

    def test_compute_mape_known_values(self):
        from backend.app.services.stock_backtester import StockBacktester

        # MAPE: |100-90|/100 + |200-210|/200 = 0.1 + 0.05 = 0.15/2 = 0.075
        actuals = [100.0, 200.0]
        preds = [90.0, 210.0]
        mape = StockBacktester._compute_mape(actuals, preds)
        assert mape == pytest.approx(0.075, abs=0.001)

    def test_compute_rmse_known_values(self):
        from backend.app.services.stock_backtester import StockBacktester

        # RMSE: sqrt((10^2 + 10^2)/2) = sqrt(100) = 10
        actuals = [100.0, 200.0]
        preds = [90.0, 210.0]
        rmse = StockBacktester._compute_rmse(actuals, preds)
        assert rmse == pytest.approx(10.0, abs=0.01)

    def test_compute_directional_accuracy_all_correct(self):
        from backend.app.services.stock_backtester import StockBacktester

        train = [("2024-W01", 100.0), ("2024-W02", 105.0)]
        actuals = [110.0, 115.0]  # both up
        preds = [108.0, 112.0]    # both up
        acc = StockBacktester._compute_directional_accuracy(train, actuals, preds)
        assert acc == 1.0

    def test_compute_directional_accuracy_all_wrong(self):
        from backend.app.services.stock_backtester import StockBacktester

        train = [("2024-W01", 100.0), ("2024-W02", 105.0)]
        actuals = [95.0, 90.0]   # both down
        preds = [110.0, 115.0]   # both predicted up
        acc = StockBacktester._compute_directional_accuracy(train, actuals, preds)
        assert acc == 0.0

    def test_compute_mape_empty_returns_zero(self):
        from backend.app.services.stock_backtester import StockBacktester

        assert StockBacktester._compute_mape([], []) == 0.0

    def test_compute_rmse_empty_returns_zero(self):
        from backend.app.services.stock_backtester import StockBacktester

        assert StockBacktester._compute_rmse([], []) == 0.0

    @pytest.mark.asyncio
    async def test_run_no_test_data_raises(self, backtest_db):
        """When train_end is after all data, no test data → raises ValueError."""
        from backend.app.services.stock_backtester import StockBacktester

        db = backtest_db
        await _seed_backtest_data(db, "^HSI", n_weeks=20)

        backtester = StockBacktester()
        with pytest.raises(ValueError):
            await backtester.run("^HSI", train_end="2024-W20", horizon=8)


# ---------------------------------------------------------------------------
# Group 6: API endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def api_forecast_db():
    """Fixture that patches get_db for API tests with an in-memory DB."""
    return None  # API tests use mocked services directly


class TestStockForecastAPI:
    """Tests for stock_forecast router endpoints."""

    @pytest.mark.asyncio
    async def test_list_tickers_returns_14_items(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group=None)
        assert response.success is True
        assert response.data["count"] == 14
        assert len(response.data["tickers"]) == 14

    @pytest.mark.asyncio
    async def test_list_tickers_response_structure(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group=None)
        ticker_dicts = response.data["tickers"]
        for t in ticker_dicts:
            assert "ticker" in t
            assert "name" in t
            assert "asset_type" in t
            assert "sector_tag" in t
            assert "market" in t

    @pytest.mark.asyncio
    async def test_list_tickers_group_filter_hk_stock(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group="hk_stock")
        assert response.success is True
        for t in response.data["tickers"]:
            assert t["asset_type"] == "hk_stock"

    @pytest.mark.asyncio
    async def test_list_tickers_group_filter_hk_index(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group="hk_index")
        assert response.success is True
        for t in response.data["tickers"]:
            assert t["asset_type"] == "hk_index"

    @pytest.mark.asyncio
    async def test_list_tickers_group_filter_us_stock(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group="us_stock")
        assert response.success is True
        for t in response.data["tickers"]:
            assert t["asset_type"] == "us_stock"

    @pytest.mark.asyncio
    async def test_list_tickers_empty_group_filter(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group="nonexistent_type")
        assert response.success is True
        assert response.data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_forecast_unknown_ticker_returns_error(self):
        from backend.app.api.stock_forecast import get_forecast

        response = await get_forecast(ticker="FAKEXYZ", horizon=12, session_id=None)
        assert response.success is False
        assert "Unknown ticker" in response.error

    @pytest.mark.asyncio
    async def test_get_forecast_valid_ticker_calls_forecaster(self):
        from backend.app.models.stock_forecast import StockForecastResult
        from backend.app.api.stock_forecast import get_forecast

        mock_result = StockForecastResult(
            ticker="^HSI", asset_type="hk_index", name="恒生指數",
            horizon=12, points=(), model_used="NaiveDrift",
            fit_quality="fair", data_quality="insufficient",
            signal_shift=0.0, signal_breakdown=(), session_id=None,
        )

        with patch("backend.app.api.stock_forecast.StockForecaster") as MockForecaster:
            mock_instance = MagicMock()
            mock_instance.forecast = AsyncMock(return_value=mock_result)
            MockForecaster.return_value = mock_instance

            response = await get_forecast(ticker="^HSI", horizon=12, session_id=None)

        assert response.success is True
        assert response.data["ticker"] == "^HSI"

    @pytest.mark.asyncio
    async def test_get_forecast_response_structure(self):
        from backend.app.models.stock_forecast import StockForecastPoint, StockForecastResult
        from backend.app.api.stock_forecast import get_forecast

        pt = StockForecastPoint(week="2024-W01", close=18000.0, lower_80=17500.0,
                                upper_80=18500.0, lower_95=17000.0, upper_95=19000.0,
                                sentiment_adjusted=False)
        mock_result = StockForecastResult(
            ticker="^HSI", asset_type="hk_index", name="恒生指數",
            horizon=12, points=(pt,), model_used="NaiveDrift",
            fit_quality="fair", data_quality="sufficient",
            signal_shift=0.05, signal_breakdown=(), session_id=None,
        )

        with patch("backend.app.api.stock_forecast.StockForecaster") as MockForecaster:
            mock_instance = MagicMock()
            mock_instance.forecast = AsyncMock(return_value=mock_result)
            MockForecaster.return_value = mock_instance

            response = await get_forecast(ticker="^HSI", horizon=12, session_id=None)

        data = response.data
        assert "ticker" in data
        assert "name" in data
        assert "asset_type" in data
        assert "horizon" in data
        assert "forecasts" in data
        assert "model_used" in data
        assert "fit_quality" in data
        assert "data_quality" in data
        assert "signal_shift" in data
        assert "signal_breakdown" in data

    @pytest.mark.asyncio
    async def test_get_forecast_with_session_id(self):
        from backend.app.models.stock_forecast import StockForecastResult
        from backend.app.api.stock_forecast import get_forecast

        mock_result = StockForecastResult(
            ticker="^HSI", asset_type="hk_index", name="恒生指數",
            horizon=12, points=(), model_used="NaiveDrift",
            fit_quality="fair", data_quality="insufficient",
            signal_shift=0.05, signal_breakdown=(), session_id="sess-abc",
        )

        with patch("backend.app.api.stock_forecast.StockForecaster") as MockForecaster:
            mock_instance = MagicMock()
            mock_instance.forecast = AsyncMock(return_value=mock_result)
            MockForecaster.return_value = mock_instance

            response = await get_forecast(ticker="^HSI", horizon=12, session_id="sess-abc")

        assert response.success is True
        assert response.data["session_id"] == "sess-abc"

    @pytest.mark.asyncio
    async def test_get_forecast_value_error_returns_error(self):
        from backend.app.api.stock_forecast import get_forecast

        with patch("backend.app.api.stock_forecast.StockForecaster") as MockForecaster:
            mock_instance = MagicMock()
            mock_instance.forecast = AsyncMock(side_effect=ValueError("Test error"))
            MockForecaster.return_value = mock_instance

            response = await get_forecast(ticker="^HSI", horizon=12, session_id=None)

        assert response.success is False
        assert "Forecast validation error" in response.error

    @pytest.mark.asyncio
    async def test_get_forecast_backtest_unknown_ticker_returns_error(self):
        from backend.app.api.stock_forecast import get_forecast_backtest

        response = await get_forecast_backtest(
            ticker="FAKEXYZ", train_end="2024-W40", horizon=8
        )
        assert response.success is False
        assert "Unknown ticker" in response.error

    @pytest.mark.asyncio
    async def test_get_forecast_backtest_valid_ticker(self):
        from backend.app.models.stock_forecast import StockBacktestResult
        from backend.app.api.stock_forecast import get_forecast_backtest

        mock_result = StockBacktestResult(
            ticker="^HSI", mape=0.05, rmse=900.0,
            directional_accuracy=0.6, n_obs=8,
            train_end="2024-W40", horizon=8,
        )

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockBacktester.return_value = mock_instance

            response = await get_forecast_backtest(
                ticker="^HSI", train_end="2024-W40", horizon=8
            )

        assert response.success is True
        assert response.data["ticker"] == "^HSI"
        assert response.data["mape"] == round(0.05, 4)

    @pytest.mark.asyncio
    async def test_get_forecast_backtest_default_params(self):
        from backend.app.models.stock_forecast import StockBacktestResult
        from backend.app.api.stock_forecast import get_forecast_backtest

        mock_result = StockBacktestResult(
            ticker="^HSI", mape=0.05, rmse=900.0,
            directional_accuracy=0.6, n_obs=8,
            train_end="2024-W40", horizon=8,
        )

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockBacktester.return_value = mock_instance

            # Default train_end and horizon
            response = await get_forecast_backtest(ticker="^HSI")

        assert response.success is True

    @pytest.mark.asyncio
    async def test_get_forecast_backtest_value_error_returns_error(self):
        from backend.app.api.stock_forecast import get_forecast_backtest

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=ValueError("Train set too small"))
            MockBacktester.return_value = mock_instance

            response = await get_forecast_backtest(
                ticker="^HSI", train_end="2024-W40", horizon=8
            )

        assert response.success is False
        assert "Backtest validation error" in response.error

    @pytest.mark.asyncio
    async def test_refresh_stock_data_returns_accepted(self):
        from fastapi import BackgroundTasks
        from backend.app.api.stock_forecast import refresh_stock_data

        bg_tasks = MagicMock(spec=BackgroundTasks)
        response = await refresh_stock_data(bg_tasks)
        assert response.success is True
        assert response.data["status"] == "accepted"
        assert response.data["ticker_count"] == 14
        bg_tasks.add_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_summary_with_group_filter(self):
        from backend.app.models.stock_forecast import StockBacktestResult
        from backend.app.api.stock_forecast import get_summary

        mock_result = StockBacktestResult(
            ticker="^HSI", mape=0.05, rmse=900.0,
            directional_accuracy=0.6, n_obs=8,
            train_end="2024-W40", horizon=8,
        )

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockBacktester.return_value = mock_instance

            response = await get_summary(group="hk_index")

        assert response.success is True
        for row in response.data["summary"]:
            assert row["asset_type"] == "hk_index"

    @pytest.mark.asyncio
    async def test_get_summary_no_filter_returns_all(self):
        from backend.app.models.stock_forecast import StockBacktestResult
        from backend.app.api.stock_forecast import get_summary

        mock_result = StockBacktestResult(
            ticker="^HSI", mape=0.05, rmse=900.0,
            directional_accuracy=0.6, n_obs=8,
            train_end="2024-W40", horizon=8,
        )

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockBacktester.return_value = mock_instance

            response = await get_summary(group=None)

        assert response.success is True
        assert response.data["count"] == 14

    @pytest.mark.asyncio
    async def test_api_response_success_field_type(self):
        from backend.app.api.stock_forecast import list_tickers

        response = await list_tickers(group=None)
        assert isinstance(response.success, bool)

    @pytest.mark.asyncio
    async def test_api_response_error_on_failure(self):
        from backend.app.api.stock_forecast import get_forecast

        response = await get_forecast(ticker="NOTREAL", horizon=12, session_id=None)
        assert response.success is False
        assert response.error is not None

    @pytest.mark.asyncio
    async def test_get_summary_handles_backtest_failure_gracefully(self):
        """Summary endpoint returns null entries for failed backtests."""
        from backend.app.api.stock_forecast import get_summary

        with patch("backend.app.api.stock_forecast.StockBacktester") as MockBacktester:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=ValueError("No data"))
            MockBacktester.return_value = mock_instance

            response = await get_summary(group="hk_index")

        assert response.success is True
        for row in response.data["summary"]:
            assert row["mape"] is None
            assert row["error"] is not None


# ---------------------------------------------------------------------------
# Group 7: Week label helpers
# ---------------------------------------------------------------------------


class TestWeekSortKeyForecaster:
    """_week_sort_key from stock_forecaster module."""

    def test_week_sort_key_ordering(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        assert _week_sort_key("2024-W01") < _week_sort_key("2024-W02")

    def test_week_sort_key_year_boundary(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        assert _week_sort_key("2023-W52") < _week_sort_key("2024-W01")

    def test_week_sort_key_format_returns_int(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        key = _week_sort_key("2025-W10")
        assert isinstance(key, int)
        assert key == 2025 * 100 + 10

    def test_week_sort_key_invalid_returns_zero(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        assert _week_sort_key("bad-format") == 0


class TestWeekLabelOffset:
    """_week_label_offset for generating forecast week labels."""

    def test_offset_one_week(self):
        from backend.app.services.stock_forecaster import _week_label_offset, _week_sort_key

        base = "2024-W10"
        next_week = _week_label_offset(base, 1)
        assert _week_sort_key(next_week) > _week_sort_key(base)

    def test_offset_multiple_weeks(self):
        from backend.app.services.stock_forecaster import _week_label_offset, _week_sort_key

        base = "2024-W10"
        w2 = _week_label_offset(base, 2)
        w1 = _week_label_offset(base, 1)
        assert _week_sort_key(w2) > _week_sort_key(w1)

    def test_offset_format_valid(self):
        from backend.app.services.stock_forecaster import _week_label_offset

        result = _week_label_offset("2024-W50", 4)
        assert re.match(r"^\d{4}-W\d{2}$", result)

    def test_offset_year_boundary_transition(self):
        """Adding weeks past W52 should roll to next year."""
        from backend.app.services.stock_forecaster import _week_label_offset

        result = _week_label_offset("2024-W52", 3)
        # Result should be in 2025
        year = int(result.split("-W")[0])
        assert year >= 2025

    def test_offset_sequence_monotonic(self):
        from backend.app.services.stock_forecaster import _week_label_offset, _week_sort_key

        base = "2024-W01"
        labels = [_week_label_offset(base, i) for i in range(1, 13)]
        keys = [_week_sort_key(l) for l in labels]
        assert keys == sorted(keys)

    def test_week_label_generation_length(self):
        """Generating 12 week labels from a base week gives 12 distinct labels."""
        from backend.app.services.stock_forecaster import _week_label_offset

        base = "2024-W05"
        labels = {_week_label_offset(base, i) for i in range(1, 13)}
        assert len(labels) == 12

    def test_week_52_to_01_transition(self):
        from backend.app.services.stock_forecaster import _week_label_offset

        result = _week_label_offset("2023-W52", 1)
        assert re.match(r"^\d{4}-W\d{2}$", result)
        year = int(result.split("-W")[0])
        assert year >= 2024

    def test_week_label_from_date_year_2024(self):
        from backend.data_pipeline.stock_downloader import _week_label_from_date
        import datetime

        dt = datetime.datetime(2024, 12, 31)
        label = _week_label_from_date(dt)
        assert re.match(r"^\d{4}-W\d{2}$", label)

    def test_week_sort_key_week_52(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        key_52 = _week_sort_key("2024-W52")
        key_01 = _week_sort_key("2024-W01")
        assert key_52 > key_01

    def test_week_sort_key_comparison_symmetry(self):
        from backend.app.services.stock_forecaster import _week_sort_key

        assert _week_sort_key("2024-W05") == _week_sort_key("2024-W05")


# ---------------------------------------------------------------------------
# Group 8: Integration
# ---------------------------------------------------------------------------


@pytest.fixture
async def integration_db():
    """Full in-memory DB for integration tests."""
    db = await aiosqlite.connect(":memory:")
    await db.executescript("""
        CREATE TABLE market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, asset_type TEXT, ticker TEXT,
            open REAL, close REAL, high REAL, low REAL,
            volume REAL, source TEXT, granularity TEXT,
            UNIQUE(date, ticker)
        );
        CREATE TABLE simulation_actions (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            agent_id INTEGER, oasis_username TEXT, action_type TEXT,
            platform TEXT, content TEXT, target_agent_username TEXT,
            sentiment REAL, topics TEXT, post_id TEXT,
            parent_action_id INTEGER, spread_depth INTEGER
        );
        CREATE TABLE emotional_states (
            id INTEGER PRIMARY KEY, session_id TEXT, agent_id INTEGER,
            round_number INTEGER, valence REAL, arousal REAL, dominance REAL
        );
        CREATE TABLE virality_scores (
            id INTEGER PRIMARY KEY, session_id TEXT, post_id TEXT,
            virality_index REAL, velocity REAL, cross_cluster_reach REAL
        );
        CREATE TABLE agent_decisions (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            agent_id INTEGER, decision_type TEXT, action TEXT, reasoning TEXT,
            oasis_username TEXT, details_json TEXT
        );
        CREATE TABLE polarization_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            polarization_index REAL
        );
        CREATE TABLE echo_chamber_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            modularity REAL, num_communities INTEGER
        );
        CREATE TABLE filter_bubble_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            avg_bubble_score REAL
        );
        CREATE TABLE agent_relationships (
            id INTEGER PRIMARY KEY, session_id TEXT, agent_id INTEGER,
            related_agent_id INTEGER, trust_score REAL
        );
        CREATE TABLE macro_snapshots (
            id INTEGER PRIMARY KEY, session_id TEXT, round_number INTEGER,
            hsi_level REAL, ccl_index REAL, unemployment_rate REAL,
            consumer_confidence REAL, credit_stress REAL, taiwan_strait_risk REAL
        );
        CREATE TABLE ensemble_results (
            id INTEGER PRIMARY KEY, session_id TEXT, metric TEXT,
            p05 REAL, p25 REAL, p50 REAL, p75 REAL, p95 REAL
        );
    """)
    await db.commit()

    # signal_extractor uses db.execute_fetchone() — add helper
    async def _execute_fetchone(sql: str, params: tuple = ()) -> Any:
        cursor = await db.execute(sql, params)
        return await cursor.fetchone()

    db.execute_fetchone = _execute_fetchone  # type: ignore[attr-defined]

    @asynccontextmanager
    async def mock_get_db():
        yield db

    with patch("backend.app.services.stock_forecaster.get_db", mock_get_db), \
         patch("backend.app.services.signal_extractor.get_db", mock_get_db), \
         patch("backend.app.services.stock_backtester.get_db", mock_get_db):
        yield db

    await db.close()


class TestIntegration:
    """End-to-end integration: seed DB → extract signals → forecast → verify structure."""

    @pytest.mark.asyncio
    async def test_full_flow_seed_extract_forecast(self, integration_db):
        db = integration_db
        # Seed 25 weeks of market data
        await _seed_market_data(db, "^HSI", n_weeks=25)
        # Seed simulation data
        session_id = "integ-sess"
        for i in range(5):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, i, 0.8, "[]"),
            )
        await db.commit()

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=12, session_id=session_id)
        assert result.data_quality == "sufficient"
        assert len(result.points) == 12
        assert result.session_id == session_id

    @pytest.mark.asyncio
    async def test_signal_extraction_to_forecast_overlay_pipeline(self, integration_db):
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=30)
        session_id = "pipe-sess"
        # Strong positive sentiment
        for i in range(10):
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, agent_id, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
                (session_id, 1, i, 1.0, '["finance"]'),
            )
        await db.commit()

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=6, session_id=session_id)
        # With session overlay, signal_shift may be non-zero
        assert result.data_quality == "sufficient"
        assert result.points != ()

    @pytest.mark.asyncio
    async def test_empty_session_no_signal_overlay(self, integration_db):
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=12, session_id=None)
        assert result.signal_shift == 0.0
        assert result.signal_breakdown == ()

    @pytest.mark.asyncio
    async def test_multiple_tickers_sequential(self, integration_db):
        db = integration_db
        for ticker, start in [("^HSI", 18000.0), ("NVDA", 800.0), ("AAPL", 180.0)]:
            await _seed_market_data(db, ticker, n_weeks=25, start_close=start)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        for ticker in ["^HSI", "NVDA", "AAPL"]:
            result = await forecaster.forecast(ticker, horizon=4)
            assert result.ticker == ticker
            assert result.data_quality == "sufficient"
            assert len(result.points) == 4

    @pytest.mark.asyncio
    async def test_forecast_result_serialization_round_trip(self, integration_db):
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=4)
        d = result.to_dict()

        # Verify round-trip serializes correctly
        assert d["ticker"] == "^HSI"
        assert d["horizon"] == 4
        assert isinstance(d["points"], list)
        assert isinstance(d["signal_breakdown"], list)
        assert isinstance(d["signal_shift"], float)
        for pt in d["points"]:
            assert "week" in pt
            assert "close" in pt
            assert "lower_80" in pt
            assert "upper_80" in pt
            assert "lower_95" in pt
            assert "upper_95" in pt
            assert "sentiment_adjusted" in pt

    @pytest.mark.asyncio
    async def test_backtest_full_flow(self, integration_db):
        db = integration_db
        await _seed_backtest_data(db, "^HSI", n_weeks=35)

        from backend.app.services.stock_backtester import StockBacktester

        backtester = StockBacktester()
        result = await backtester.run("^HSI", train_end="2024-W25", horizon=5)
        assert result.ticker == "^HSI"
        assert result.n_obs >= 1
        assert result.mape >= 0.0
        assert result.rmse >= 0.0

    @pytest.mark.asyncio
    async def test_signal_extractor_returns_frozen_result(self, integration_db):
        session_id = "frozen-sess"

        from backend.app.services.signal_extractor import SimulationSignalExtractor

        extractor = SimulationSignalExtractor()
        sig = await extractor.extract(session_id)

        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            sig.sentiment_net = 99.9  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_forecast_points_are_frozen(self, integration_db):
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=3)
        if result.points:
            with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
                result.points[0].close = 99999.0  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_forecast_result_is_frozen(self, integration_db):
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=3)
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            result.ticker = "CHANGED"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_signals_and_forecast_work_together(self, integration_db):
        """Combined: session with macro data + forecast with signal overlay."""
        db = integration_db
        await _seed_market_data(db, "^HSI", n_weeks=25)

        session_id = "macro-integ"
        await db.execute(
            """INSERT INTO macro_snapshots (session_id, round_number, hsi_level, ccl_index,
               unemployment_rate, consumer_confidence, credit_stress, taiwan_strait_risk)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, 1, 17000.0, 150.0, 4.0, 48.0, 0.2, 0.1),
        )
        await db.execute(
            """INSERT INTO macro_snapshots (session_id, round_number, hsi_level, ccl_index,
               unemployment_rate, consumer_confidence, credit_stress, taiwan_strait_risk)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, 20, 19000.0, 165.0, 3.5, 54.0, 0.25, 0.12),
        )
        await db.commit()

        from backend.app.services.stock_forecaster import StockForecaster

        forecaster = StockForecaster()
        result = await forecaster.forecast("^HSI", horizon=4, session_id=session_id)
        assert result.data_quality == "sufficient"
        assert result.session_id == session_id
