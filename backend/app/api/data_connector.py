"""Data ingestion endpoints for the Universal Prediction Engine.

Prefix: /api/ingest  (mounted under /api in create_app)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.app.services.data_connector import DataConnector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["data-connector"])

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "json"}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
) -> dict:
    """Ingest a CSV/XLSX/XLS/JSON file and auto-detect its schema.

    - **file**: The data file to upload (max 50 MB).
    - **session_id**: The simulation session to associate the data with.

    Returns detected field types and sample values.  If you also pass
    ``field_mappings`` via the form, numeric columns will be stored in
    ``user_data_points`` and the response will include ``mapped_count``.
    """
    content = await file.read()

    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    original_name = file.filename or "upload.csv"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext!r}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    connector = DataConnector()
    try:
        result = await connector.ingest_file(
            file_content=content,
            filename=original_name,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("Unexpected error during file ingestion")
        raise HTTPException(status_code=500, detail="File ingestion failed") from exc

    return {
        "row_count": result.row_count,
        "fields": [
            {
                "name": f.source_field,
                "type": f.detected_type,
                "samples": f.sample_values,
            }
            for f in result.detected_fields
        ],
    }
