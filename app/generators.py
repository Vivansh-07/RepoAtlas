"""Graph Lab: generate random graphs from three classic models, and measure them.

Each model is famous for one property, and the statistics are chosen to show it:
  - Erdős–Rényi G(n, p): every pair of nodes is linked with probability p.
    Degrees cluster around the average (bell shape, no hubs), and one "giant"
    component suddenly appears once the average degree passes 1.
  - Barabási–Albert (n, m): nodes arrive one at a time and link to m existing
    nodes, preferring well-connected ones ("the rich get richer"). Degrees are
    heavy-tailed (scale-free): a few big hubs, many small nodes.
  - Watts–Strogatz (n, k, p): start from a ring where every node links to its k
    nearest neighbours, then rewire each edge with probability p. A little
    rewiring keeps clustering high while paths get short: a "small world".
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass

import networkx as nx

from app import config
from app.analytics import detect_communities
from app.errors import InvalidParams
from app.serializer import serialize_graph

DEFAULT_P = {"er": 0.04, "ws": 0.1}
DEFAULT_M = 2
DEFAULT_K = 4


@dataclass
class LabSummary:
    model: str
    n: int
    p: float | None          # only the parameters the model uses are filled in
    m: int | None
    k: int | None
    seed: int
    num_nodes: int
    num_edges: int
    density: float
    avg_degree: float
    max_degree: int
    avg_clustering: float     # how often two neighbours of a node are also neighbours
    num_components: int
    giant_component_size: int
    avg_path_length: float | None   # average hops between nodes, inside the giant component
    num_communities: int
    modularity: float


def _check_edge_budget(expected_edges: float) -> None:
    if expected_edges > config.MAX_GENERATED_EDGES:
        raise InvalidParams(
            f"That would create about {expected_edges:,.0f} edges "
            f"(limit {config.MAX_GENERATED_EDGES:,}). Lower n or the other parameter."
        )


def _check_probability(p: float) -> None:
    if not 0.0 <= p <= 1.0:
        raise InvalidParams("p must be between 0 and 1")


def build_graph(model: str, n: int, p: float, m: int, k: int, seed: int) -> nx.Graph:
    """Generate the raw graph, after checking the parameters make sense."""
    if not 2 <= n <= config.MAX_GENERATED_NODES:
        raise InvalidParams(f"n must be between 2 and {config.MAX_GENERATED_NODES}")

    if model == "er":
        _check_probability(p)
        _check_edge_budget(p * n * (n - 1) / 2)          # expected number of edges
        return nx.gnp_random_graph(n, p, seed=seed)
    if model == "ba":
        if not 1 <= m < n:
            raise InvalidParams("m must be at least 1 and smaller than n")
        _check_edge_budget(m * (n - m))
        return nx.barabasi_albert_graph(n, m, seed=seed)
    if model == "ws":
        _check_probability(p)
        if k < 2 or k % 2 or k >= n:
            raise InvalidParams("k must be an even number, at least 2 and smaller than n")
        _check_edge_budget(n * k / 2)
        return nx.watts_strogatz_graph(n, k, p, seed=seed)
    raise InvalidParams(f"Unknown model {model!r}: use er, ba or ws")


def degree_distribution(graph: nx.Graph) -> dict[str, list[int]]:
    """How many nodes have degree 0, 1, 2, ... up to the maximum (zeros included,
    so the chart shows gaps honestly)."""
    counts = Counter(d for _, d in graph.degree())
    top = max(counts, default=0)
    return {"degree": list(range(top + 1)), "count": [counts.get(d, 0) for d in range(top + 1)]}


def measure(graph: nx.Graph) -> dict:
    """Statistics + per-node attributes. Writes `degree`, `clustering`,
    `community` (and a `label`) onto every node."""
    degrees = dict(graph.degree())
    clustering = nx.clustering(graph)
    communities, modularity = detect_communities(graph)   # works on undirected graphs too
    community_of = {node: i for i, group in enumerate(communities) for node in group}

    for node, data in graph.nodes(data=True):
        data.update(label=node, degree=degrees[node], clustering=clustering[node],
                    community=community_of.get(node))

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    giant = graph.subgraph(components[0]) if components else graph
    n = graph.number_of_nodes()
    return {
        "num_nodes": n,
        "num_edges": graph.number_of_edges(),
        "density": nx.density(graph),
        "avg_degree": 2 * graph.number_of_edges() / n if n else 0.0,
        "max_degree": max(degrees.values(), default=0),
        "avg_clustering": nx.average_clustering(graph) if n else 0.0,
        "num_components": len(components),
        "giant_component_size": giant.number_of_nodes(),
        # One BFS per node: fine up to 500 nodes (well under a second).
        "avg_path_length": nx.average_shortest_path_length(giant) if giant.number_of_nodes() > 1 else None,
        "num_communities": len(communities),
        "modularity": modularity,
    }


def generate(model: str, n: int = 100, p: float | None = None, m: int | None = None,
             k: int | None = None, seed: int | None = None) -> dict:
    """Build, measure and serialise one random graph for the Graph Lab."""
    p = DEFAULT_P.get(model, 0.0) if p is None else p
    m = DEFAULT_M if m is None else m
    k = DEFAULT_K if k is None else k
    # Always report a seed, so any graph the user likes can be regenerated exactly.
    seed = random.randrange(1, 1_000_000) if seed is None else seed

    graph = build_graph(model, n, p, m, k, seed)
    graph = nx.relabel_nodes(graph, str)        # Cytoscape needs string ids
    stats = measure(graph)
    summary = LabSummary(
        model=model, n=n,
        p=p if model in ("er", "ws") else None,
        m=m if model == "ba" else None,
        k=k if model == "ws" else None,
        seed=seed, **stats,
    )
    return {"summary": asdict(summary), "degree_distribution": degree_distribution(graph),
            **serialize_graph(graph)}
