# backend/app/services/surrogate_model.py
"""Phase A Surrogate Model — learn belief→decision mapping from Phase A logs.

Trains a LogisticRegression on (belief_vector → decision_type) pairs from
Phase A simulation_actions rows.  Phase B MultiRunOrchestrator can optionally
use this surrogate for outcome prediction instead of the ad-hoc scoring function,
giving a data-driven rather than heuristic outcome assignment.

Usage::

    surrogate = SurrogateModel()
    result = await surrogate.train_from_session("session_abc", metrics=["x","y"])
    if result.is_fitted:
        prob_dist = result.predict_distribution({"x": 0.7, "y": 0.3})
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("surrogate_model")

_MIN_TRAINING_ROWS = 20


@dataclass
class SurrogateModelResult:
    """Fitted logistic regression surrogate.

    Note: Not frozen — sklearn model objects are mutable.
    Access via predict() / predict_distribution() only.
    """

    is_fitted: bool
    n_classes: int
    classes: list[str]
    train_accuracy: float
    metrics_used: list[str]
    _clf: Any = field(default=None, repr=False)

    def predict(self, belief_vec: dict[str, float]) -> str:
        """Return most likely outcome for a belief vector."""
        if not self.is_fitted or self._clf is None:
            return "unknown"
        X = [[belief_vec.get(m, 0.5) for m in self.metrics_used]]
        return str(self._clf.predict(X)[0])

    def predict_distribution(self, belief_vec: dict[str, float]) -> dict[str, float]:
        """Return probability distribution over outcomes."""
        if not self.is_fitted or self._clf is None:
            n = max(len(self.classes), 1)
            return {c: 1.0 / n for c in self.classes}
        X = [[belief_vec.get(m, 0.5) for m in self.metrics_used]]
        probs = self._clf.predict_proba(X)[0]
        return {c: round(float(p), 4) for c, p in zip(self._clf.classes_, probs)}


class SurrogateModel:
    """Train and serve a belief→decision surrogate from Phase A data."""

    def train_from_rows(
        self,
        rows: list[Any],
        outcome_col: str,
        metrics: list[str],
    ) -> SurrogateModelResult:
        """Train from pre-fetched rows (dicts or sqlite Row objects).

        Args:
            rows: Each row must have keys: outcome_col (str label) and
                  'belief_snapshot' (JSON string with metric→float dict).
            outcome_col: Column name for the decision/outcome label.
            metrics: Metric names to use as features (in consistent order).

        Returns:
            SurrogateModelResult (fitted or unfitted).
        """
        if not rows or len(rows) < _MIN_TRAINING_ROWS:
            logger.info("SurrogateModel: insufficient rows (%d < %d)", len(rows), _MIN_TRAINING_ROWS)
            return SurrogateModelResult(
                is_fitted=False,
                n_classes=0,
                classes=[],
                train_accuracy=0.0,
                metrics_used=metrics,
            )

        try:
            from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
        except ImportError:
            logger.error("scikit-learn not installed")
            return SurrogateModelResult(
                is_fitted=False,
                n_classes=0,
                classes=[],
                train_accuracy=0.0,
                metrics_used=metrics,
            )

        X, y = [], []
        for row in rows:
            try:
                # Always expect dict-like access (train_from_session pre-converts;
                # tests pass dicts directly)
                row_dict = row if isinstance(row, dict) else dict(row)
                snapshot_raw = row_dict.get("belief_snapshot", "{}")
                snapshot: dict[str, float] = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else {}
                label = row_dict.get(outcome_col)
                if not label:
                    continue
                X.append([snapshot.get(m, 0.5) for m in metrics])
                y.append(str(label))
            except Exception:
                continue

        if len(X) < _MIN_TRAINING_ROWS or len(set(y)) < 2:
            return SurrogateModelResult(
                is_fitted=False,
                n_classes=0,
                classes=[],
                train_accuracy=0.0,
                metrics_used=metrics,
            )

        clf = LogisticRegression(max_iter=300, C=1.0, solver="lbfgs")
        clf.fit(X, y)
        accuracy = clf.score(X, y)
        classes = list(clf.classes_)

        logger.info(
            "SurrogateModel trained: %d rows, %d classes, train_acc=%.3f",
            len(X),
            len(classes),
            accuracy,
        )
        return SurrogateModelResult(
            is_fitted=True,
            n_classes=len(classes),
            classes=classes,
            train_accuracy=round(accuracy, 4),
            metrics_used=metrics,
            _clf=clf,
        )

    async def train_from_session(
        self,
        session_id: str,
        metrics: list[str] | None = None,
    ) -> SurrogateModelResult:
        """Train from a completed Phase A session stored in DB.

        Args:
            session_id: Phase A simulation session ID.
            metrics: Metric names to use as features.  If None, inferred
                from belief_snapshot keys of first row.

        Returns:
            SurrogateModelResult.
        """
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT sa.agent_id, sa.round_number, sa.decision_type,
                       am.content as belief_snapshot
                FROM simulation_actions sa
                LEFT JOIN agent_memories am
                    ON am.session_id = sa.session_id
                    AND am.agent_id = sa.agent_id
                    AND am.round_number = sa.round_number
                    AND am.memory_type = 'belief_snapshot'
                WHERE sa.session_id = ?
                  AND sa.decision_type IS NOT NULL
                LIMIT 500
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return SurrogateModelResult(
                is_fitted=False,
                n_classes=0,
                classes=[],
                train_accuracy=0.0,
                metrics_used=metrics or [],
            )

        # Infer metrics from first valid snapshot if not provided
        inferred_metrics = metrics
        if inferred_metrics is None:
            for r in rows:
                try:
                    snap = json.loads(r[3] or "{}")
                    if snap:
                        inferred_metrics = list(snap.keys())
                        break
                except Exception:
                    pass
        inferred_metrics = inferred_metrics or []

        dict_rows = [{"decision_type": r[2], "belief_snapshot": r[3]} for r in rows]
        return self.train_from_rows(dict_rows, outcome_col="decision_type", metrics=inferred_metrics)
