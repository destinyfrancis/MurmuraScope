"""Tests for ExternalDataFeed health check, periodic refresh, and change detection."""

from __future__ import annotations

import pytest

from backend.app.services.external_data_feed import (
    ExternalDataFeed,
    detect_significant_changes,
)

# ---------------------------------------------------------------------------
# detect_significant_changes
# ---------------------------------------------------------------------------


class TestDetectSignificantChanges:
    def test_above_threshold_detected(self):
        prev = {"fed_rate": 0.045, "gdp_growth": 0.03}
        current = {"fed_rate": 0.055, "gdp_growth": 0.03}
        changes = detect_significant_changes(prev, current, threshold=0.05)
        assert len(changes) == 1
        field, old, new = changes[0]
        assert field == "fed_rate"
        assert old == 0.045
        assert new == 0.055

    def test_below_threshold_ignored(self):
        prev = {"fed_rate": 0.045}
        current = {"fed_rate": 0.046}  # ~2.2% change
        changes = detect_significant_changes(prev, current, threshold=0.05)
        assert changes == []

    def test_new_field_ignored(self):
        """Fields in current but not in prev are not 'changes'."""
        prev = {"fed_rate": 0.045}
        current = {"fed_rate": 0.045, "new_metric": 1.0}
        changes = detect_significant_changes(prev, current, threshold=0.05)
        assert changes == []

    def test_empty_prev_returns_empty(self):
        changes = detect_significant_changes({}, {"fed_rate": 0.05}, threshold=0.05)
        assert changes == []

    def test_both_empty_returns_empty(self):
        changes = detect_significant_changes({}, {}, threshold=0.05)
        assert changes == []

    def test_zero_old_value_uses_floor(self):
        """When old value is 0, denominator uses floor of 0.001."""
        prev = {"x": 0.0}
        current = {"x": 0.1}
        changes = detect_significant_changes(prev, current, threshold=0.05)
        # 0.1 / 0.001 = 100 > 0.05 → detected
        assert len(changes) == 1

    def test_multiple_changes(self):
        prev = {"a": 1.0, "b": 2.0, "c": 3.0}
        current = {"a": 1.2, "b": 2.0, "c": 4.0}
        changes = detect_significant_changes(prev, current, threshold=0.05)
        fields = {c[0] for c in changes}
        assert "a" in fields  # 20% change
        assert "c" in fields  # 33% change
        assert "b" not in fields  # no change


# ---------------------------------------------------------------------------
# ExternalDataFeed.health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_structure(self, monkeypatch):
        """health_check returns dict with three source keys, each with 'configured'."""
        monkeypatch.delenv("FRED_API_KEY", raising=False)

        feed = ExternalDataFeed()

        # Mock network calls to avoid real API hits
        async def _mock_fred():
            return {}

        async def _mock_wb():
            return {"gdp_growth": 0.03}

        async def _mock_taiwan():
            return 0.20

        feed._fetch_fred = _mock_fred
        feed._fetch_world_bank = _mock_wb
        feed._fetch_taiwan_risk_proxy = _mock_taiwan

        result = await feed.health_check()
        assert "fred" in result
        assert "world_bank" in result
        assert "taiwan_risk_proxy" in result

        # FRED not configured (no API key)
        assert result["fred"]["configured"] is False
        assert result["fred"]["status"] == "skipped"

        # World Bank always configured
        assert result["world_bank"]["configured"] is True
        assert result["world_bank"]["status"] == "ok"
        assert "gdp_growth" in result["world_bank"]["fields"]

        # Taiwan risk proxy
        assert result["taiwan_risk_proxy"]["configured"] is True
        assert result["taiwan_risk_proxy"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_with_fred_key(self, monkeypatch):
        """When FRED_API_KEY is set, health_check attempts to fetch."""
        monkeypatch.setenv("FRED_API_KEY", "test_key_123")

        feed = ExternalDataFeed()

        async def _mock_fred():
            return {"fed_rate": 0.045}

        async def _mock_wb():
            return {}

        async def _mock_taiwan():
            return 0.20

        feed._fetch_fred = _mock_fred
        feed._fetch_world_bank = _mock_wb
        feed._fetch_taiwan_risk_proxy = _mock_taiwan

        result = await feed.health_check()
        assert result["fred"]["configured"] is True
        assert result["fred"]["status"] == "ok"
        assert "fed_rate" in result["fred"]["fields"]

    @pytest.mark.asyncio
    async def test_health_check_handles_errors(self, monkeypatch):
        """health_check captures errors without raising."""
        monkeypatch.setenv("FRED_API_KEY", "test_key")

        feed = ExternalDataFeed()

        async def _failing_fred():
            raise ConnectionError("Network unreachable")

        async def _mock_wb():
            return {}

        async def _mock_taiwan():
            return 0.20

        feed._fetch_fred = _failing_fred
        feed._fetch_world_bank = _mock_wb
        feed._fetch_taiwan_risk_proxy = _mock_taiwan

        result = await feed.health_check()
        assert result["fred"]["configured"] is True
        assert "error" in result["fred"]["status"]


# ---------------------------------------------------------------------------
# Force refresh / cache bypass
# ---------------------------------------------------------------------------


class TestForceRefresh:
    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self):
        """force_refresh=True should re-fetch even when cache is warm."""
        feed = ExternalDataFeed()
        fetch_count = 0

        async def _counting_fred():
            nonlocal fetch_count
            fetch_count += 1
            return {"fed_rate": 0.045 + fetch_count * 0.001}

        async def _mock_wb():
            return {}

        async def _mock_taiwan():
            return 0.20

        feed._fetch_fred = _counting_fred
        feed._fetch_world_bank = _mock_wb
        feed._fetch_taiwan_risk_proxy = _mock_taiwan

        # First fetch (populates cache)
        result1 = await feed.fetch()
        assert fetch_count == 1

        # Second fetch (should use cache)
        result2 = await feed.fetch()
        assert fetch_count == 1  # No re-fetch

        # Force refresh (should re-fetch)
        result3 = await feed.fetch(force_refresh=True)
        assert fetch_count == 2  # Re-fetched
        assert result3.get("fed_rate") != result1.get("fed_rate")
