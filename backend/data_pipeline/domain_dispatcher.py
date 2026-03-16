"""Domain-aware data pipeline dispatcher.

Runs all data sources declared by a domain pack's DataSourceSpec list,
dispatching each to the appropriate downloader module and function.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from backend.app.domain.base import DomainPackRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    """Immutable result of a single data-source dispatch."""

    source_id: str
    category: str
    row_count: int
    error: str | None = None


async def download_for_domain(pack_id: str) -> list[DispatchResult]:
    """Run all data sources declared by a domain pack.

    Iterates over pack.data_sources, dynamically imports each downloader
    module, calls the specified function with the declared params, and
    collects DispatchResult objects.  Failures are logged and recorded as
    error results rather than raising exceptions so the pipeline always
    completes.

    Args:
        pack_id: Registered domain pack identifier (e.g. "hk_city").

    Returns:
        List of DispatchResult, one per DataSourceSpec in the pack.
        Returns an empty list if the pack has no data sources defined.
    """
    pack = DomainPackRegistry.get(pack_id)
    results: list[DispatchResult] = []

    for source in pack.data_sources:
        try:
            module = importlib.import_module(source.downloader)
            fn = getattr(module, source.function)
            result = await fn(**source.params)
            row_count = len(result) if isinstance(result, list) else 0
            results.append(DispatchResult(
                source_id=source.id,
                category=source.category,
                row_count=row_count,
            ))
            logger.info(
                "Data source %s (%s.%s) completed: %d rows",
                source.id, source.downloader, source.function, row_count,
            )
        except Exception as exc:
            logger.error(
                "Data source %s (%s.%s) failed: %s",
                source.id, source.downloader, source.function, exc,
            )
            results.append(DispatchResult(
                source_id=source.id,
                category=source.category,
                row_count=0,
                error=str(exc),
            ))

    return results
