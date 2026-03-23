"""File upload + API source ingestion for the Universal Prediction Engine."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import pandas as pd

from backend.app.services.schema_detector import DetectedField, SchemaDetector
from backend.app.utils.db import get_db

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = frozenset({"csv", "xlsx", "xls", "json"})


@dataclass(frozen=True)
class IngestResult:
    row_count: int
    detected_fields: list[DetectedField]
    mapped_count: int = 0


class DataConnector:
    """Ingest user-supplied files and persist mapped data points."""

    def __init__(self) -> None:
        self._detector = SchemaDetector()

    async def ingest_file(
        self,
        file_content: bytes,
        filename: str,
        session_id: str,
        field_mappings: list[dict] | None = None,
    ) -> IngestResult:
        """Read *filename* bytes, detect schema, optionally store mapped columns.

        Args:
            file_content: Raw bytes of the uploaded file.
            filename: Original filename — used to determine format by extension.
            session_id: Simulation session to associate stored data with.
            field_mappings: Optional list of ``{"source_field": str,
                "target_metric": str}`` dicts.  When provided, numeric values
                from each source column are written to ``user_data_points``.

        Returns:
            IngestResult with row count, detected fields, and stored row count.
        """
        df = self._read_file(file_content, filename)
        fields = self._detector.detect(df)

        mapped = 0
        if field_mappings:
            mapped = await self._store_mapped_data(df, field_mappings, session_id)

        return IngestResult(
            row_count=len(df),
            detected_fields=fields,
            mapped_count=mapped,
        )

    @staticmethod
    def _read_file(content: bytes, filename: str) -> pd.DataFrame:
        """Parse *content* into a DataFrame based on *filename* extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format: {ext!r}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}")
        if ext == "csv":
            return pd.read_csv(io.BytesIO(content))
        if ext in ("xlsx", "xls"):
            return pd.read_excel(io.BytesIO(content))
        # json
        return pd.read_json(io.BytesIO(content))

    @staticmethod
    async def _store_mapped_data(
        df: pd.DataFrame,
        mappings: list[dict],
        session_id: str,
    ) -> int:
        """Persist numeric values from *df* for each mapping into the DB.

        Returns the number of rows stored.
        """
        stored = 0
        rows_to_insert: list[tuple] = []

        for mapping in mappings:
            src = mapping.get("source_field", "")
            tgt = mapping.get("target_metric", "")
            if not src or not tgt:
                logger.warning("Skipping mapping with missing source_field/target_metric: %s", mapping)
                continue
            if src not in df.columns:
                logger.warning("Source field %r not in DataFrame columns", src)
                continue

            for idx, row in df.iterrows():
                raw = row.get("date", idx)
                ts = str(raw) if not isinstance(raw, str) else raw
                val_raw = row[src]
                if pd.isna(val_raw):
                    continue
                try:
                    val = float(val_raw)
                except (TypeError, ValueError):
                    logger.debug("Non-numeric value %r in column %r — skipping", val_raw, src)
                    continue
                rows_to_insert.append((session_id, tgt, val, ts, "user_file"))

        if rows_to_insert:
            async with get_db() as db:
                await db.executemany(
                    "INSERT INTO user_data_points "
                    "(session_id, metric, value, timestamp, source_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows_to_insert,
                )
                await db.commit()
            stored = len(rows_to_insert)

        return stored
