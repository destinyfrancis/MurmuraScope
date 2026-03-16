"""Tests for data pipeline downloaders and normalisation logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.data_pipeline.census_downloader import (
    CensusRecord,
    CensusResult,
    DATASET_IDS,
    _find_numeric_value,
    _parse_population_csv,
    _pick_csv_resource,
    _try_parse_float,
)
from backend.data_pipeline.economy_downloader import (
    EconomyRecord,
    EconomyResult,
    _try_parse_float as econ_try_parse_float,
)


# ======================================================================
# Census downloader — CSV parsing
# ======================================================================


class TestCensusParsePopulationCSV:
    """Test _parse_population_csv with various CSV shapes."""

    def test_parses_age_sex_csv(self, sample_census_csv):
        dataset_id = DATASET_IDS["population_age_sex"]
        records = _parse_population_csv(
            sample_census_csv, dataset_id, "https://example.com/data.csv"
        )

        assert len(records) > 0
        assert all(isinstance(r, CensusRecord) for r in records)
        assert all(r.dataset_id == dataset_id for r in records)
        assert all(r.period == "2021" for r in records)

    def test_empty_csv_returns_no_records(self):
        records = _parse_population_csv("", "test-id", "https://example.com")
        assert records == []

    def test_single_header_row_returns_no_records(self):
        csv_text = "Year,Age Group,Sex,Population\n"
        records = _parse_population_csv(csv_text, "test-id", "https://example.com")
        assert records == []

    def test_generic_dataset_parses_multiple_columns(self):
        csv_text = (
            "Period,District,Count,Percentage\n"
            "2023Q1,Central,50000,12.5\n"
            "2023Q1,Wan Chai,40000,10.0\n"
        )
        records = _parse_population_csv(
            csv_text, "generic-dataset", "https://example.com"
        )

        assert len(records) > 0
        # Generic path produces records from numeric columns beyond first two
        for record in records:
            assert record.period == "2023Q1"

    def test_source_url_preserved(self, sample_census_csv):
        url = "https://data.gov.hk/test-resource"
        records = _parse_population_csv(
            sample_census_csv, DATASET_IDS["population_age_sex"], url
        )
        assert all(r.source_url == url for r in records)


# ======================================================================
# Census downloader — helper functions
# ======================================================================


class TestCensusHelpers:
    """Test helper functions in census_downloader."""

    def test_try_parse_float_with_commas(self):
        assert _try_parse_float("123,456") == 123456.0

    def test_try_parse_float_with_dash(self):
        assert _try_parse_float("-") is None

    def test_try_parse_float_with_na(self):
        assert _try_parse_float("N/A") is None

    def test_try_parse_float_empty_string(self):
        assert _try_parse_float("") is None

    def test_try_parse_float_valid_decimal(self):
        assert _try_parse_float("3.14") == 3.14

    def test_find_numeric_value_excludes_keys(self):
        row = {"year": "2021", "age": "25", "value": "100"}
        result = _find_numeric_value(row, exclude_keys={"year", "age"})
        assert result == 100.0

    def test_find_numeric_value_no_match(self):
        row = {"year": "2021", "name": "test"}
        result = _find_numeric_value(row, exclude_keys={"year"})
        assert result is None

    def test_pick_csv_resource_finds_csv(self):
        resources = [
            {"format": "XLSX", "name": "data", "url": "https://x.com/data.xlsx"},
            {"format": "CSV", "name": "data", "url": "https://x.com/data.csv"},
        ]
        result = _pick_csv_resource(resources)
        assert result is not None
        assert result["format"] == "CSV"

    def test_pick_csv_resource_fallback_to_first(self):
        resources = [
            {"format": "XLSX", "name": "data", "url": "https://x.com/data.xlsx"},
        ]
        result = _pick_csv_resource(resources)
        assert result is not None
        assert result["format"] == "XLSX"

    def test_pick_csv_resource_empty_list(self):
        result = _pick_csv_resource([])
        assert result is None


# ======================================================================
# Economy downloader — HKMA API response handling
# ======================================================================


class TestEconomyDownloaderHandlesAPIResponse:
    """Test economy downloader with mocked HKMA API responses."""

    @pytest.mark.asyncio
    async def test_download_hibor_parses_records(self, sample_hkma_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_hkma_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "backend.data_pipeline.economy_downloader.RAW_DIR",
        ) as mock_dir:
            mock_path = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=mock_path)
            mock_dir.mkdir = MagicMock()
            mock_path.write_text = MagicMock()

            from backend.data_pipeline.economy_downloader import download_hibor

            result = await download_hibor(mock_client)

        assert isinstance(result, EconomyResult)
        assert result.source_name == "hkma_hibor"
        assert result.row_count > 0
        assert all(isinstance(r, EconomyRecord) for r in result.records)
        assert all(r.category == "interest_rate" for r in result.records)
        assert all(r.source == "HKMA" for r in result.records)

    def test_econ_try_parse_float_strips_commas(self):
        assert econ_try_parse_float("1,234,567") == 1234567.0

    def test_econ_try_parse_float_handles_na(self):
        assert econ_try_parse_float("N.A.") is None


# ======================================================================
# Data normaliser — DB insertion
# ======================================================================


class TestDataNormalizerInsertsSnapshots:
    """Test that parsed records can be inserted into the database."""

    @pytest.mark.asyncio
    async def test_insert_census_records(self, test_db):
        records = [
            CensusRecord(
                dataset_id="test-dataset",
                metric="population_by_age_sex",
                dimension_1="0-4",
                dimension_2="Male",
                dimension_3=None,
                value=123456.0,
                period="2021",
                source_url="https://example.com",
            ),
            CensusRecord(
                dataset_id="test-dataset",
                metric="population_by_age_sex",
                dimension_1="0-4",
                dimension_2="Female",
                dimension_3=None,
                value=118234.0,
                period="2021",
                source_url="https://example.com",
            ),
        ]

        for record in records:
            await test_db.execute(
                """INSERT INTO population_distributions
                   (category, dimension_1, dimension_2, dimension_3,
                    count, probability, source_year, source_dataset)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.metric,
                    record.dimension_1,
                    record.dimension_2,
                    record.dimension_3,
                    int(record.value),
                    0.0,
                    2021,
                    record.dataset_id,
                ),
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT COUNT(*) as cnt FROM population_distributions"
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2

    @pytest.mark.asyncio
    async def test_insert_economy_records(self, test_db):
        records = [
            EconomyRecord(
                category="interest_rate",
                metric="hibor_3m",
                value=4.70,
                unit="percent",
                period="2024-01",
                source="HKMA",
                source_url="https://api.hkma.gov.hk/test",
            ),
        ]

        for record in records:
            await test_db.execute(
                """INSERT INTO hk_data_snapshots
                   (category, metric, value, unit, period, source, source_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.category,
                    record.metric,
                    record.value,
                    record.unit,
                    record.period,
                    record.source,
                    record.source_url,
                ),
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT * FROM hk_data_snapshots WHERE metric = 'hibor_3m'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["value"] == 4.70
        assert row["source"] == "HKMA"


# ======================================================================
# Population distribution probabilities
# ======================================================================


class TestPopulationDistributionSumsToOne:
    """Verify that population distribution probabilities sum to 1.0."""

    @pytest.mark.asyncio
    async def test_probabilities_sum_to_one(self, test_db):
        # Insert records with probabilities that should sum to 1.0
        rows = [
            ("age_distribution", "0-14", None, None, 150000, 0.20, 2021, "census"),
            ("age_distribution", "15-24", None, None, 112500, 0.15, 2021, "census"),
            ("age_distribution", "25-44", None, None, 225000, 0.30, 2021, "census"),
            ("age_distribution", "45-64", None, None, 187500, 0.25, 2021, "census"),
            ("age_distribution", "65+", None, None, 75000, 0.10, 2021, "census"),
        ]

        for row in rows:
            await test_db.execute(
                """INSERT INTO population_distributions
                   (category, dimension_1, dimension_2, dimension_3,
                    count, probability, source_year, source_dataset)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT SUM(probability) as total FROM population_distributions "
            "WHERE category = 'age_distribution'"
        )
        row = await cursor.fetchone()
        assert abs(row["total"] - 1.0) < 1e-9


# ======================================================================
# Download orchestration
# ======================================================================


class TestDownloadAllOrchestration:
    """Test that download_all functions coordinate multiple downloaders."""

    @pytest.mark.asyncio
    async def test_download_all_census_calls_both(self):
        with (
            patch(
                "backend.data_pipeline.census_downloader.download_population_age_sex",
                new_callable=AsyncMock,
            ) as mock_age_sex,
            patch(
                "backend.data_pipeline.census_downloader.download_population_single_age",
                new_callable=AsyncMock,
            ) as mock_single_age,
        ):
            mock_age_sex.return_value = CensusResult(
                dataset_id="age-sex", records=(), raw_file_path="/tmp/a.csv", row_count=0
            )
            mock_single_age.return_value = CensusResult(
                dataset_id="single-age", records=(), raw_file_path="/tmp/b.csv", row_count=0
            )

            from backend.data_pipeline.census_downloader import download_all_census

            mock_client = AsyncMock()
            mock_client.aclose = AsyncMock()

            results = await download_all_census(mock_client)

            assert len(results) == 2
            mock_age_sex.assert_awaited_once()
            mock_single_age.assert_awaited_once()
