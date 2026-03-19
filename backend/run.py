"""Uvicorn entry point for Morai backend."""

from __future__ import annotations

import uvicorn

from backend.app import create_app
from backend.app.config import get_settings


def main() -> None:
    """Start the uvicorn server with settings from environment."""
    settings = get_settings()
    app = create_app()

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )


if __name__ == "__main__":
    main()
