"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Immutable application settings loaded from .env file.

    All values come from environment variables or .env;
    the class is frozen to prevent accidental mutation.
    """

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "frozen": True,
        "extra": "ignore",
    }

    # Database
    DATABASE_PATH: str = "data/murmuroscope.db"

    # LLM API keys
    OPENROUTER_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    FIREWORKS_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    # Demo Mode
    DEMO_MODE: bool = False

    # Security
    AUTH_SECRET_KEY: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 5001
    DEBUG: bool = False

    # OASIS framework path
    OASIS_PATH: str = ""

    # Frontend
    FRONTEND_URL: str = "http://localhost:8080"

    # Logging
    LOG_LEVEL: str = "INFO"

    @property
    def database_dir(self) -> Path:
        """Return the parent directory of the database file."""
        return Path(self.DATABASE_PATH).parent

    @property
    def schema_path(self) -> Path:
        """Return the path to schema.sql in backend/database/."""
        return Path(__file__).parent.parent / "database" / "schema.sql"


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return _settings


_settings = Settings()
