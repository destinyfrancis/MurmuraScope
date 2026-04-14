import networkx as nx
from typing import Any
from backend.app.utils.logger import get_logger

logger = get_logger("graph_metrics")

def calculate_topological_metrics(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate centralized and structural hole metrics using NetworkX.
    
    Args:
        edges: List of edges with 'source', 'target', 'weight'
        
    Returns:
        Dict containing centrality and structural hole scores.
    """
    if not edges:
        return {"centrality": {}, "structural_holes": {}}

    G = nx.DiGraph()
    for e in edges:
        G.add_edge(e["source"], e["target"], weight=e.get("weight", 1.0))

    try:
        # 1. Betweenness Centrality (identifies bridges)
        betweenness = nx.betweenness_centrality(G, weight="weight")
        
        # 2. Structural Holes - Constraint (lower is better for bridge actors)
        # Burts constraint measures how redundant nodes are
        try:
            constraints = nx.constraint(G)
        except Exception:
            # nx.constraint needs at least two nodes or certain connectivity
            constraints = {}

        # 3. Eigenvector Centrality (identifies influencers connected to other influencers)
        try:
            eigenvector = nx.eigenvector_centrality_numpy(G, weight="weight")
        except Exception:
            eigenvector = nx.degree_centrality(G) # Fallback to degree centrality

        return {
            "betweenness": betweenness,
            "constraint": constraints,
            "eigenvector": eigenvector,
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges()
        }
    except Exception as e:
        logger.error("Error calculating graph metrics: %s", e)
        return {"error": str(e)}

def find_latent_nodes(metrics: dict[str, Any], threshold: float = 0.5) -> list[str]:
    """Identify nodes that could be 'Structural Holes' but are currently missing or bridges.
    
    Basically, finding nodes with high betweenness but high constraint (or vice versa).
    """
    # Placeholder for more complex latent discovery logic
    # Real logic would likely happen in the Service layer combining these metrics with LLM.
    betweenness = metrics.get("betweenness", {})
    return [node for node, score in betweenness.items() if score > threshold]
