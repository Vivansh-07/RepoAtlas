"""Package-level view: collapse modules into the packages they belong to.

Every module belongs to the package it lives in; a package's own __init__.py
belongs to that package. Collapsing gives a much smaller *quotient graph*: one
node per package, and an edge P -> Q whenever a module of P imports a module of
Q, weighted by the import statements behind it. Imports between modules of the
same package disappear inside its node.

The package graph uses the same attribute names as the module graph, so the
normal analytics (analytics.analyze) run on it unchanged. That answers
architecture questions: which packages are central, and which *packages*
depend on each other in a loop.
"""

from __future__ import annotations

import posixpath

import networkx as nx

TOP_LEVEL = "(top level)"     # modules straight in the repo root (setup.py, ...)

# Node attributes that describe an external library, copied as-is.
_EXTERNAL_ATTRS = ("label", "package", "path", "loc", "kind", "is_external", "is_package", "parse_error")


def package_of(module: str, is_package: bool, path: str = "") -> str:
    """'flask.json.provider' -> 'flask.json'; the package 'flask.json' -> itself.

    A module outside any package (e.g. the main file of an example project in
    examples/aliases/) is grouped by its folder, 'examples/aliases/', so separate
    example projects don't merge into one group. Only files in the repo root
    itself form the TOP_LEVEL group.
    """
    if is_package:
        return module
    parent = module.rpartition(".")[0]
    if parent:
        return parent
    folder = posixpath.dirname(path)
    return f"{folder}/" if folder else TOP_LEVEL


def build_package_graph(graph: nx.DiGraph) -> nx.DiGraph:
    """Collapse the module graph (as made by graph_builder.build_graph) into packages."""
    packages = nx.DiGraph()
    group: dict[str, str] = {}        # module (or external library) -> its node in `packages`
    folders: dict[str, list[str]] = {}

    # Sorted, so node order (and therefore the Louvain colours) is reproducible.
    for node, data in sorted(graph.nodes(data=True)):
        if data["is_external"]:
            group[node] = node        # libraries stay as they are
            packages.add_node(node, **{k: data[k] for k in _EXTERNAL_ATTRS}, module_count=0, modules=[])
            continue

        package = package_of(node, data["is_package"], data["path"])
        group[node] = package
        if package not in packages:
            packages.add_node(
                package,
                label=package,
                package=package.rpartition(".")[0] if not package.endswith(("/", ")")) else "",
                path=".", loc=0, kind="internal", is_external=False, is_package=True, parse_error=None,
                module_count=0, modules=[],
            )
        summary = packages.nodes[package]
        summary["loc"] += data["loc"]
        summary["module_count"] += 1
        summary["modules"].append(node)
        folders.setdefault(package, []).append(posixpath.dirname(data["path"]))

    # A package's path: the deepest folder holding all its modules ("." = repo root).
    for package, dirs in folders.items():
        packages.nodes[package]["path"] = posixpath.commonpath(dirs) or "."

    for source, target, data in graph.edges(data=True):
        a, b = group[source], group[target]
        if a == b:
            continue                  # an import inside one package
        if packages.has_edge(a, b):
            edge = packages.edges[a, b]
            edge["weight"] += data["weight"]
            # Type-only only if *every* import behind the package edge is.
            edge["type_only"] = edge["type_only"] and data["type_only"]
        else:
            packages.add_edge(a, b, weight=data["weight"], kind=data["kind"], type_only=data["type_only"])
    return packages
