import asyncio
import json
import uuid
import logging
from typing import Any

from backend.app.services.graph_builder import GraphBuilderService
from backend.app.services.benchmarking_service import BenchmarkingService, F1Score
from backend.app.utils.db import get_db

from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graph_benchmark")

async def run_benchmark():
    # Load scenarios
    with open("data/benchmarks/graph_scenarios.json", "r") as f:
        scenarios = json.load(f)

    results = []
    service = BenchmarkingService()

    for sc in scenarios:
        logger.info(f"Running benchmark for scenario: {sc['title']}")
        session_id = str(uuid.uuid4())
        
        # 1. Seed the session (minimal session entry)
        from backend.app.utils.llm_client import get_agent_provider_model
        provider, model = get_agent_provider_model()
        logger.info(f"Using provider: {provider}, model: {model}")

        async with get_db() as db:
            await db.execute(
                """INSERT INTO simulation_sessions (id, name, sim_mode, seed_text, agent_count, round_count, llm_provider, llm_model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, sc["title"], "kg_driven", sc["seed_text"], 10, 1, "fireworks", "minimax-m2p5")
            )
            await db.commit()

        # 2. Build the Graph
        builder = GraphBuilderService()
        try:
            # We use build_graph which extracts entities and relationships
            await builder.build_graph(session_id, "benchmark", sc["seed_text"])
        except Exception as e:
            logger.error(f"Graph building failed for {sc['id']}: {e}")
            continue

        # 3. Retrieve extracted graph from DB
        async with get_db() as db:
            cursor = await db.execute("SELECT title, entity_type FROM kg_nodes WHERE session_id = ?", (session_id,))
            nodes = await cursor.fetchall()
            
            cursor = await db.execute(
                """SELECT kn1.title as source, kn2.title as target, ke.relation_type
                   FROM kg_edges ke
                   JOIN kg_nodes kn1 ON ke.source_id = kn1.id
                   JOIN kg_nodes kn2 ON ke.target_id = kn2.id
                   WHERE ke.session_id = ?""",
                (session_id,)
            )
            edges = await cursor.fetchall()

        # 4. Compare with Gold Standard
        actual_nodes = { (r["title"], r["entity_type"]) for r in nodes }
        gold_nodes = { (n[0], n[1]) for n in sc["gold_nodes"] }
        
        actual_edges = { (r["source"], r["target"], r["relation_type"]) for r in edges }
        gold_edges = { (e[0], e[1], e[2]) for e in sc["gold_edges"] }

        node_metrics = service.calculate_f1(actual_nodes, gold_nodes)
        edge_metrics = service.calculate_f1(actual_edges, gold_edges)

        results.append({
            "id": sc["id"],
            "title": sc["title"],
            "node_f1": node_metrics,
            "edge_f1": edge_metrics
        })

    # Summary Report
    print("\n" + "="*60)
    print(" MURMURASCOPE GRAPH ACCURACY BENCHMARK REPORT")
    print("="*60)
    print(f"{'Scenario':<20} | {'Node F1':<10} | {'Edge F1':<10}")
    print("-" * 60)
    
    avg_node_f1 = 0
    avg_edge_f1 = 0
    
    for r in results:
        print(f"{r['title']:<20} | {r['node_f1'].f1:<10.2f} | {r['edge_f1'].f1:<10.2f}")
        avg_node_f1 += r['node_f1'].f1
        avg_edge_f1 += r['edge_f1'].f1
        
    if results:
        print("-" * 60)
        print(f"{'AVERAGE':<20} | {avg_node_f1/len(results):<10.2f} | {avg_edge_f1/len(results):<10.2f}")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
