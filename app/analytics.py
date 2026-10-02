"""Graph analytics: importance (PageRank), clusters (Louvain), cycles (SCCs), depth.

Everything is computed on graph_builder.analysis_view: the repo's own modules
joined by imports that actually run.
- External libraries are left out: `typing` would top every importance ranking,
  and showing or hiding them must not change a module's size, colour or rank.
- `if TYPE_CHECKING:` imports are left out: they never execute, so they can't
  cause a circular import (avoiding one is usually why they're written).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from app.graph_builder import analysis_view

TOP_N = 10
LOUVAIN_SEED = 42   # fixed seed -> same communities (and colours) every run


@dataclass
class Summary:
    num_nodes: int
    num_edges: int              # runtime imports between repo modules
    num_type_only_edges: int    # `if TYPE_CHECKING:` imports between repo modules
    density: float
    num_communities: int
    modularity: float
    num_cycles: int
    largest_cycle_size: int
    dependency_depth: int
    num_stdlib: int
    num_third_party: int
    top_modules: list[dict] = field(default_factory=list)


def _largest_first(groups) -> list[set[str]]:
    # Stable numbering: biggest group gets id 0 (so the first palette colour),
    # ties broken by name so the order never depends on set iteration.
    return sorted(groups, key=lambda g: (-len(g), min(g)))


def compute_pagerank(internal: nx.DiGraph) -> dict[str, float]:
    # With edges pointing at what gets imported, rank flows towards modules
    # that many (important) modules depend on: the core of the codebase.
    return nx.pagerank(internal, weight="weight")


def detect_communities(internal: nx.DiGraph) -> tuple[list[set[str]], float]:
    """Louvain communities (largest first) and their modularity.

    Modularity (-0.5..1) measures how much denser the links inside communities
    are than chance would give; above ~0.3 means clearly separated clusters.
    """
    # Louvain works on undirected graphs: "these modules work closely together"
    # doesn't depend on who imports whom.
    undirected = internal.to_undirected()
    # A module with no internal imports either way would become a "community" of
    # one, which is just noise in the colours. Isolated nodes add 0 to modularity.
    undirected.remove_nodes_from(list(nx.isolates(undirected)))
    if undirected.number_of_edges() == 0:
        return [], 0.0
    found = nx.community.louvain_communities(undirected, weight="weight", seed=LOUVAIN_SEED)
    return _largest_first(found), nx.community.modularity(undirected, found, weight="weight")


def find_cycles(internal: nx.DiGraph) -> list[set[str]]:
    # Every strongly connected component (SCC) with 2+ modules is a group where
    # each module can reach every other by following imports: a circular
    # dependency. SCCs take O(V+E); listing every simple cycle can be exponential.
    return _largest_first(c for c in nx.strongly_connected_components(internal) if len(c) > 1)


def dependency_depth(internal: nx.DiGraph) -> int:
    """Longest chain of imports, counting each cycle group as a single step.

    Cycles make "longest path" undefined, so we first collapse every SCC into one
    node (the condensation, which is always a DAG) and measure that instead.
    """
    return nx.dag_longest_path_length(nx.condensation(internal))


def analyze(graph: nx.DiGraph) -> Summary:
    """Write analytics onto every node and edge of `graph`, and return a summary."""
    internal = analysis_view(graph)
    pagerank = compute_pagerank(internal)
    ranking = sorted(pagerank, key=lambda n: (-pagerank[n], n))
    communities, modularity = detect_communities(internal)
    cycles = find_cycles(internal)

    rank_of = {name: i + 1 for i, name in enumerate(ranking)}
    community_of = {n: i for i, group in enumerate(communities) for n in group}
    scc_of = {n: i for i, group in enumerate(cycles) for n in group}

    for node, data in graph.nodes(data=True):
        # An external node's in_degree = how many repo modules use that library.
        degrees_from = graph if data["is_external"] else internal
        data.update(
            in_degree=degrees_from.in_degree(node),
            out_degree=degrees_from.out_degree(node),
            pagerank=pagerank.get(node, 0.0),
            pagerank_rank=rank_of.get(node),
            community=community_of.get(node),
            scc_id=scc_of.get(node),
            in_cycle=node in scc_of,
        )

    for source, target, data in graph.edges(data=True):
        # A type-only edge between two cycle members isn't part of the cycle.
        data["in_cycle"] = (
            not data["type_only"] and source in scc_of and scc_of[source] == scc_of.get(target)
        )

    kinds = [kind for _, kind in graph.nodes(data="kind")]
    return Summary(
        num_nodes=internal.number_of_nodes(),
        num_edges=internal.number_of_edges(),
        num_type_only_edges=sum(
            1 for u, v, type_only in graph.edges(data="type_only")
            if type_only and u in internal and v in internal
        ),
        density=nx.density(internal),
        num_communities=len(communities),
        modularity=modularity,
        num_cycles=len(cycles),
        largest_cycle_size=max((len(c) for c in cycles), default=0),
        dependency_depth=dependency_depth(internal),
        num_stdlib=kinds.count("stdlib"),
        num_third_party=kinds.count("third_party"),
        top_modules=[{"id": n, "pagerank": pagerank[n]} for n in ranking[:TOP_N]],
    )


if __name__ == "__main__":
    # Manual check:
    #   python -m app.analytics tests/fixtures/sample_repo
    #   python -m app.analytics https://github.com/pallets/flask
    import sys

    from app.cloner import open_repo
    from app.graph_builder import build_graph
    from app.parser import parse_repo
    from app.resolver import resolve_repo

    with open_repo(sys.argv[1]) as repo_path:
        parsed = parse_repo(repo_path)
    graph = build_graph(parsed, resolve_repo(parsed))
    s = analyze(graph)

    print(f"{s.num_nodes} modules, {s.num_edges} runtime edges "
          f"(+{s.num_type_only_edges} type-only), density {s.density:.3f}")
    print(f"{s.num_communities} communities, modularity {s.modularity:.2f}")
    print(f"{s.num_cycles} cycle groups, largest has {s.largest_cycle_size} modules")
    print(f"dependency depth {s.dependency_depth}")
    print(f"external: {s.num_stdlib} stdlib, {s.num_third_party} third-party\n")
    print("Most important modules (PageRank):")
    for i, top in enumerate(s.top_modules, 1):
        print(f"  {i:>2}. {top['id']:<40} {top['pagerank']:.4f}")

    groups: dict[int, list[str]] = {}
    for node, scc in graph.nodes(data="scc_id"):
        if scc is not None:
            groups.setdefault(scc, []).append(node)
    for scc, members in sorted(groups.items()):
        print(f"\ncycle group {scc}: {', '.join(sorted(members))}")
