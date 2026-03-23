"""Auto-detect column types and suggest field mappings."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DetectedField:
    source_field: str
    detected_type: str  # "numeric", "date", "categorical"
    sample_values: list[str]
    suggested_metric: str | None = None


class SchemaDetector:
    """Inspect a DataFrame and classify each column by data type."""

    def detect(self, df: pd.DataFrame) -> list[DetectedField]:
        """Return a DetectedField for every column in *df*."""
        fields: list[DetectedField] = []
        for col in df.columns:
            dtype = self._detect_type(df[col])
            samples = [str(v) for v in df[col].head(3).tolist()]
            fields.append(
                DetectedField(
                    source_field=col,
                    detected_type=dtype,
                    sample_values=samples,
                )
            )
        return fields

    @staticmethod
    def _detect_type(series: pd.Series) -> str:
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"
        try:
            pd.to_datetime(series)
            return "date"
        except (ValueError, TypeError):
            pass
        return "categorical"
