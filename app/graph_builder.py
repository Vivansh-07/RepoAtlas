"""Build a NetworkX directed graph from parsed modules and resolved edges.

Edge A -> B means "module A imports module B". External libraries are always
added as nodes (is_external=True); whether they're *shown* is decided later, so
one cached graph can serve both settings of the "show external" toggle.
"""

from __future__ import annotations

import networkx as nx

from app.parser import ParsedRepo
from app.resolver import Edge


def build_graph(parsed: ParsedRepo, edges: list[Edge]) -> nx.DiGraph:
    graph = nx.DiGraph()

    # Sorted insertion order keeps Louvain (and so the colours) reproducible.
    for name in sorted(parsed.modules):
        module = parsed.modules[name]
        package, _, label = name.rpartition(".")
        graph.add_node(
            name, label=label, package=package, path=module.path, loc=module.loc,
            kind="internal", is_external=False, is_package=module.is_package,
            parse_error=module.parse_error,
        )

    for edge in edges:
        if edge.target not in graph:   # only externals can be missing at this point
            graph.add_node(
                edge.target, label=edge.target, package="", path=None, loc=0,
                kind=edge.kind, is_external=True, is_package=False, parse_error=None,
            )
        graph.add_edge(
            edge.source, edge.target, weight=edge.weight, kind=edge.kind, type_only=edge.type_only
        )

    return graph


def analysis_view(graph: nx.DiGraph) -> nx.DiGraph:
    """The graph every analytic runs on: the repo's own modules, joined only by
    imports that actually run (no external libraries, no `if TYPE_CHECKING:` edges).

    A read-only view that filters on the fly, so nothing is copied.
    """
    return nx.subgraph_view(
        graph,
        filter_node=lambda n: not graph.nodes[n]["is_external"],
        filter_edge=lambda u, v: not graph.edges[u, v]["type_only"],
    )
