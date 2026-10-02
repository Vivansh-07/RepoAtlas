"""Turn the analysed NetworkX graph into Cytoscape.js elements.

Cytoscape expects `{"data": {...}}` for every node and edge, with `id` (and
`source`/`target` for edges) inside `data`, so the browser can use our JSON as-is.
"""

from __future__ import annotations

import networkx as nx


def serialize_graph(graph: nx.DiGraph) -> dict[str, list[dict]]:
    nodes = [{"data": {"id": node, **attrs}} for node, attrs in graph.nodes(data=True)]
    edges = [
        # "->" can't appear in a module name, so this id is always unique.
        {"data": {"id": f"{source}->{target}", "source": source, "target": target, **attrs}}
        for source, target, attrs in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}


def without_external(elements: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop external libraries and every edge that points at one."""
    return {
        "nodes": [n for n in elements["nodes"] if not n["data"]["is_external"]],
        "edges": [e for e in elements["edges"] if e["data"]["kind"] == "internal"],
    }
