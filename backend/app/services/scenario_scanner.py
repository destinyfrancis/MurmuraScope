"""Scenario Scanner — systematic parameter sweep over simulation variants.

Generates grid or Latin Hypercube Sampling combinations from a parameter space,
creates branch sessions for each variant, and returns branch IDs for downstream
analysis (Monte Carlo, comparison, etc.).
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("scenario_scanner")

# ---------------------------------------------------------------------------
# Preset templates
# ---------------------------------------------------------------------------

SCAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "PROPERTY_SWEEP": {
        "parameters": {
            "interest_rate": [0.03, 0.04, 0.05, 0.06, 0.08],
            "stamp_duty": [0.0, 0.075, 0.15],
        },
        "description": "Property market sensitivity: interest rate × stamp duty grid",
    },
    "EMIGRATION_SWEEP": {
        "parameters": {
            "taiwan_strait_risk": [0.1, 0.3, 0.5, 0.7, 0.9],
        },
        "description": "Emigration pressure sweep over geopolitical risk levels",
    },
    "MACRO_SWEEP": {
        "parameters": {
            "gdp_growth": [-0.05, -0.02, 0.0, 0.02, 0.05],
        },
        "description": "GDP growth scenario sweep from recession to boom",
    },
    "FULL_MACRO_SWEEP": {
        "parameters": {
            "gdp_growth": [-0.03, 0.0, 0.03],
            "unemployment_rate": [0.03, 0.05, 0.08],
            "interest_rate": [0.03, 0.055, 0.08],
        },
        "description": "Full macro sweep: GDP × unemployment × interest rate",
    },
}

# Maximum grid size before switching to LHS
_LHS_THRESHOLD = 10
# Column names in simulation_sessions that may be overridden
_ALLOWED_MACRO_PARAMS = frozenset({
    "interest_rate",
    "stamp_duty",
    "taiwan_strait_risk",
    "gdp_growth",
    "unemployment_rate",
    "consumer_confidence",
    "hsi_level",
    "ccl_index",
    "cpi_yoy",
    "fed_rate",
    "china_gdp_growth",
})


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanVariant:
    """One parameter combination within a scan."""

    branch_id: str
    parent_session_id: str
    label: str
    parameters: dict[str, float]  # the overrides applied


@dataclass(frozen=True)
class ScanResult:
    """Result of a full scenario scan."""

    parent_session_id: str
    n_variants: int
    sampling_method: str  # "grid" or "lhs"
    variants: tuple[ScanVariant, ...]

    @property
    def branch_ids(self) -> list[str]:
        return [v.branch_id for v in self.variants]


# ---------------------------------------------------------------------------
# ScenarioScanner
# ---------------------------------------------------------------------------


class ScenarioScanner:
    """Systematic scenario scanner — grid or LHS sweep over parameter spaces."""

    async def scan(
        self,
        session_id: str,
        parameter_space: dict[str, list[float]],
        max_variants: int = 10,
        label_prefix: str = "scan",
    ) -> ScanResult:
        """Scan over all combinations in *parameter_space*.

        If the full Cartesian product exceeds *max_variants* we switch to
        Latin Hypercube Sampling (LHS) to obtain *max_variants* quasi-random
        but space-filling points.

        Args:
            session_id: Parent simulation session UUID.
            parameter_space: Dict mapping parameter names → list of candidate values.
                             E.g. ``{"interest_rate": [0.03, 0.05, 0.08]}``.
            max_variants: Maximum number of branches to create.
            label_prefix: Human-readable prefix for branch labels.

        Returns:
            ScanResult with branch IDs for all created variants.
        """
        # Validate parameter names
        unknown = set(parameter_space) - _ALLOWED_MACRO_PARAMS
        if unknown:
            logger.warning("Unknown scan parameters (ignored): %s", unknown)
            parameter_space = {
                k: v for k, v in parameter_space.items() if k in _ALLOWED_MACRO_PARAMS
            }

        if not parameter_space:
            raise ValueError("No valid parameters in parameter_space")

        # Determine sampling method
        grid_size = 1
        for vals in parameter_space.values():
            grid_size *= len(vals)

        if grid_size <= max_variants:
            combos = list(self._grid_combinations(parameter_space))
            method = "grid"
        else:
            combos = self._lhs_combinations(parameter_space, max_variants)
            method = "lhs"

        logger.info(
            "scan session=%s params=%s grid_size=%d method=%s n_combos=%d",
            session_id, list(parameter_space), grid_size, method, len(combos),
        )

        variants: list[ScanVariant] = []
        for i, combo in enumerate(combos):
            label = self._make_label(label_prefix, i, combo)
            branch_id = await self._create_branch(session_id, combo, label)
            variants.append(ScanVariant(
                branch_id=branch_id,
                parent_session_id=session_id,
                label=label,
                parameters=combo,
            ))

        return ScanResult(
            parent_session_id=session_id,
            n_variants=len(variants),
            sampling_method=method,
            variants=tuple(variants),
        )

    @staticmethod
    def get_template(name: str) -> dict[str, Any]:
        """Return a preset scan template by name.

        Args:
            name: One of the keys in SCAN_TEMPLATES.

        Returns:
            Template dict with keys ``parameters`` and ``description``.

        Raises:
            KeyError: If the template name is not recognised.
        """
        if name not in SCAN_TEMPLATES:
            available = ", ".join(SCAN_TEMPLATES)
            raise KeyError(f"Unknown template '{name}'. Available: {available}")
        return SCAN_TEMPLATES[name]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _grid_combinations(
        parameter_space: dict[str, list[float]],
    ) -> list[dict[str, float]]:
        """Return the full Cartesian product of all parameter values."""
        keys = list(parameter_space)
        value_lists = [parameter_space[k] for k in keys]
        combos: list[dict[str, float]] = []
        for combo_vals in itertools.product(*value_lists):
            combos.append(dict(zip(keys, combo_vals)))
        return combos

    @staticmethod
    def _lhs_combinations(
        parameter_space: dict[str, list[float]],
        n_samples: int,
    ) -> list[dict[str, float]]:
        """Latin Hypercube Sampling — returns *n_samples* quasi-random points.

        Each parameter's range is derived from its min/max values. This gives
        better coverage than pure random sampling within the budget.
        """
        keys = list(parameter_space)
        n_params = len(keys)
        rng = np.random.default_rng(seed=42)  # deterministic for reproducibility

        # Build (n_samples, n_params) LHS matrix in [0, 1]
        lhs = np.zeros((n_samples, n_params))
        for j in range(n_params):
            perm = rng.permutation(n_samples)
            lhs[:, j] = (perm + rng.random(n_samples)) / n_samples

        # Scale each column to [min_val, max_val] of the candidate list
        combos: list[dict[str, float]] = []
        for row in lhs:
            combo: dict[str, float] = {}
            for j, key in enumerate(keys):
                candidates = sorted(parameter_space[key])
                lo, hi = candidates[0], candidates[-1]
                raw = lo + row[j] * (hi - lo)
                # Snap to nearest candidate value
                best = min(candidates, key=lambda c: abs(c - raw))
                combo[key] = best
            combos.append(combo)

        return combos

    @staticmethod
    def _make_label(prefix: str, index: int, combo: dict[str, float]) -> str:
        """Human-readable branch label."""
        parts = [f"{k}={v}" for k, v in combo.items()]
        return f"{prefix}-{index + 1} [{', '.join(parts)}]"

    async def _create_branch(
        self,
        parent_session_id: str,
        parameter_overrides: dict[str, float],
        label: str,
    ) -> str:
        """Insert a branch row into scenario_branches and return branch_id.

        The branch stores the parameter overrides as JSON in ``config_overrides``.
        """
        branch_id = str(uuid.uuid4())
        overrides_json = json.dumps(parameter_overrides)

        async with get_db() as db:
            # Ensure scenario_branches table exists (may not be in original schema)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_branches (
                    id               TEXT PRIMARY KEY,
                    parent_session_id TEXT NOT NULL,
                    branch_session_id TEXT,
                    label            TEXT NOT NULL DEFAULT '',
                    fork_round       INTEGER,
                    config_overrides TEXT,
                    created_at       TEXT DEFAULT (datetime('now'))
                )
                """
            )
            await db.execute(
                """
                INSERT INTO scenario_branches
                    (id, parent_session_id, label, config_overrides)
                VALUES (?, ?, ?, ?)
                """,
                (branch_id, parent_session_id, label, overrides_json),
            )
            await db.commit()

        logger.debug(
            "Created branch %s for session %s params=%s",
            branch_id, parent_session_id, parameter_overrides,
        )
        return branch_id

    async def list_scan_branches(self, session_id: str) -> list[dict]:
        """Return all scanner-created branches for a session.

        Args:
            session_id: Parent session UUID.

        Returns:
            List of branch dicts with id, label, config_overrides.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT id, parent_session_id, label, config_overrides, created_at
                    FROM scenario_branches
                    WHERE parent_session_id = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if d.get("config_overrides"):
                    try:
                        d["config_overrides"] = json.loads(d["config_overrides"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append(d)
            return result
        except Exception:
            logger.exception("list_scan_branches failed session=%s", session_id)
            return []
