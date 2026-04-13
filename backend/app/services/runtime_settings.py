"""Runtime settings override store — in-memory singleton.

Architecture:
  .env (bootstrap default)
     ↓ startup
  DB: app_settings table
     ↕ GET/PUT /api/settings
  RuntimeSettingsStore  ← this module
     ↑ read priority (fallback → .env / config.py)
  llm_client.py reads from get_override()

This module intentionally has NO imports from the DB layer at module load
time to avoid circular import issues.  Call load_from_rows() from the
lifespan hook after the DB is ready.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("murmuroscope.runtime_settings")

# ---------------------------------------------------------------------------
# Private state
# ---------------------------------------------------------------------------

_store: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_override(key: str) -> str | None:
    """Return the runtime override for *key*, or None if not set.

    Callers should fall back to the .env-based value when this returns None::

        provider = get_override("agent_llm_provider") or settings.AGENT_LLM_PROVIDER
    """
    return _store.get(key)


def set_override(key: str, value: str) -> None:
    """Update a single key in the in-memory store.

    This does NOT write to the DB — persistence is the caller's responsibility.
    """
    _store[key] = value
    logger.debug("RuntimeSettings: set %s", key)


def delete_override(key: str) -> None:
    """Remove a key from the in-memory store (revert to .env default)."""
    _store.pop(key, None)
    logger.debug("RuntimeSettings: deleted %s", key)


def load_from_rows(rows: list) -> None:
    """Bulk-load the store from DB rows at startup.

    Each row must be indexable as row["key"] and row["value"]
    (aiosqlite Row objects support this with row_factory=sqlite3.Row).
    """
    _store.clear()
    for row in rows:
        _store[row["key"]] = row["value"]
    logger.info("RuntimeSettings: loaded %d setting(s) from DB", len(rows))


def get_all() -> dict[str, str]:
    """Return a shallow copy of the entire store (for diagnostics)."""
    return dict(_store)
