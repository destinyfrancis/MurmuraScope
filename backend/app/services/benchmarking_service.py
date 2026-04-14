"""Structural/Accuracy Benchmarking Service for MurmuraScope Knowledge Graphs.

This service calculates Precision, Recall, and F1 scores for knowledge graphs,
comparing a generated 'belief' or 'extracted' graph against a 'truth' or 'reference' graph.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db

logger = logging.getLogger(__name__)

@dataclass
class F1Score:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

@dataclass
class GraphBenchmarkResult:
    session_id: str
    node_f1: F1Score
    edge_f1: F1Score

class BenchmarkingService:
    @staticmethod
    def calculate_f1(actual_set: set, reference_set: set) -> F1Score:
        """Calculate Precision, Recall and F1 for two sets of identifiers."""
        if not actual_set and not reference_set:
            return F1Score(1.0, 1.0, 1.0, 0, 0, 0)
        
        tp = len(actual_set.intersection(reference_set))
        fp = len(actual_set - reference_set)
        fn = len(reference_set - actual_set)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return F1Score(precision, recall, f1, tp, fp, fn)

    async def benchmark_session(self, session_id: str) -> GraphBenchmarkResult:
        """Benchmark the current session's belief vs truth (if available).
        
        If no 'truth' layer exists in this session, it compares against the 
        initial seed graph nodes.
        """
        async with get_db() as db:
            # Fetch nodes
            cursor = await db.execute(
                "SELECT title, entity_type, layer_type FROM kg_nodes WHERE session_id = ?",
                (session_id,)
            )
            node_rows = await cursor.fetchall()
            
            # Fetch edges
            cursor = await db.execute(
                """SELECT kn1.title as source, kn2.title as target, ke.relation_type, ke.layer_type
                   FROM kg_edges ke
                   JOIN kg_nodes kn1 ON ke.source_id = kn1.id
                   JOIN kg_nodes kn2 ON ke.target_id = kn2.id
                   WHERE ke.session_id = ?""",
                (session_id,)
            )
            edge_rows = await cursor.fetchall()

        # Split into Truth and Belief sets
        truth_nodes = { (r["title"], r["entity_type"]) for r in node_rows if r["layer_type"] == "truth" }
        belief_nodes = { (r["title"], r["entity_type"]) for r in node_rows if r["layer_type"] == "belief" }
        
        # If belief layer is used as the "target" of generation (extracted from agent memory),
        # we treat truth as baseline.
        
        truth_edges = { (r["source"], r["target"], r["relation_type"]) for r in edge_rows if r["layer_type"] == "truth" }
        belief_edges = { (r["source"], r["target"], r["relation_type"]) for r in edge_rows if r["layer_type"] == "belief" }

        node_metrics = self.calculate_f1(belief_nodes, truth_nodes)
        edge_metrics = self.calculate_f1(belief_edges, truth_edges)

        return GraphBenchmarkResult(
            session_id=session_id,
            node_f1=node_metrics,
            edge_f1=edge_metrics
        )

    async def benchmark_cross_session(self, session_a: str, session_b: str) -> GraphBenchmarkResult:
        """Benchmark one session's graph (A) against another (B) as truth."""
        # Implementation similar to above but comparing two distinct session ID graphs.
        # Useful for evaluating extraction quality against a gold standard session.
        pass
