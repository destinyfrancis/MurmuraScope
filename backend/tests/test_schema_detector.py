"""Tests for SchemaDetector."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services.schema_detector import DetectedField, SchemaDetector


def test_detect_numeric_columns():
    df = pd.DataFrame(
        {
            "price": [100, 200, 300],
            "date": ["2025-01", "2025-02", "2025-03"],
            "category": ["A", "B", "A"],
        }
    )
    detector = SchemaDetector()
    result = detector.detect(df)
    assert any(f.source_field == "price" and f.detected_type == "numeric" for f in result)
    assert any(f.source_field == "date" and f.detected_type == "date" for f in result)
    assert any(f.source_field == "category" and f.detected_type == "categorical" for f in result)


def test_detect_all_numeric():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    detector = SchemaDetector()
    result = detector.detect(df)
    assert all(f.detected_type == "numeric" for f in result)


def test_detect_samples():
    df = pd.DataFrame({"x": [10, 20, 30, 40]})
    detector = SchemaDetector()
    result = detector.detect(df)
    assert result[0].sample_values == ["10", "20", "30"]


def test_detected_field_is_frozen():
    field = DetectedField(
        source_field="col",
        detected_type="numeric",
        sample_values=["1", "2"],
    )
    with pytest.raises((AttributeError, TypeError)):
        field.source_field = "other"  # type: ignore[misc]


def test_empty_dataframe_returns_no_fields():
    df = pd.DataFrame()
    result = SchemaDetector().detect(df)
    assert result == []


def test_suggested_metric_defaults_to_none():
    df = pd.DataFrame({"val": [1.0]})
    result = SchemaDetector().detect(df)
    assert result[0].suggested_metric is None


def test_detect_integer_column_as_numeric():
    df = pd.DataFrame({"count": [10, 20, 30]})
    result = SchemaDetector().detect(df)
    assert result[0].detected_type == "numeric"


def test_detect_float_column_as_numeric():
    df = pd.DataFrame({"rate": [0.05, 0.06, 0.07]})
    result = SchemaDetector().detect(df)
    assert result[0].detected_type == "numeric"


def test_detect_iso_date_strings_as_date():
    df = pd.DataFrame({"ts": ["2024-01-01", "2024-02-01", "2024-03-01"]})
    result = SchemaDetector().detect(df)
    assert result[0].detected_type == "date"


def test_detect_free_text_as_categorical():
    df = pd.DataFrame({"label": ["hello world", "foo bar", "baz"]})
    result = SchemaDetector().detect(df)
    assert result[0].detected_type == "categorical"
