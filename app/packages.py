"""Package-level view: collapse modules into the packages they belong to.

Every module belongs to the package it lives in; a package's own __init__.py
belongs to that package. Collapsing gives a much smaller *quotient graph*: one
node per package, and an edge P -> Q whenever a module of P imports a module of
Q, weighted by the import statements behind it. Imports between modules of the
same package disappear inside its node.

A package is a folder, so modules are grouped by folder and each group is
named after its dotted package name (see group_modules for name clashes).

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
    return _folder_name(posixpath.dirname(path))


def _folder_name(folder: str) -> str:
    return f"{folder}/" if folder else TOP_LEVEL


def group_modules(modules: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Module -> the name of its package node.

    `modules` maps each module to (its package_of name, its folder). Modules are
    grouped by folder. Usually all modules of a folder share one package name,
    which names the group. But nested projects can reuse a name (Flask's tests/
    and examples/tutorial/tests/ are both `tests`), and after a module name
    clash the parser names a module by its full path, so one folder can hold
    several package names. As in the parser, the shallowest folder keeps a
    contested name; any other folder is named by its path ("examples/tutorial/tests/").
    """
    names_in: dict[str, set[str]] = {}            # folder -> the package names found in it
    for name, folder in modules.values():
        names_in.setdefault(folder, set()).add(name)

    claims: dict[str, list[str]] = {}             # package name -> folders that use only it
    for folder, names in names_in.items():
        if len(names) == 1:
            (name,) = names                       # the set's only element
            claims.setdefault(name, []).append(folder)
    name_of = {min(folders, key=lambda f: (f.count("/"), f)): name for name, folders in claims.items()}

    return {module: name_of.get(folder) or _folder_name(folder) for module, (_, folder) in modules.items()}


def build_package_graph(graph: nx.DiGraph) -> nx.DiGraph:
    """Collapse the module graph (as made by graph_builder.build_graph) into packages."""
    packages = nx.DiGraph()
    # Module (or external library, below) -> its node in `packages`.
    group = group_modules({
        node: (package_of(node, data["is_package"], data["path"]), posixpath.dirname(data["path"]))
        for node, data in graph.nodes(data=True) if not data["is_external"]
    })

    # Sorted, so node order (and therefore the Louvain colours) is reproducible.
    for node, data in sorted(graph.nodes(data=True)):
        if data["is_external"]:
            group[node] = node        # libraries stay as they are
            packages.add_node(node, **{k: data[k] for k in _EXTERNAL_ATTRS}, module_count=0, modules=[])
            continue

        package = group[node]
        if package not in packages:
            packages.add_node(
                package,
                label=package,
                package=package.rpartition(".")[0] if not package.endswith(("/", ")")) else "",
                path=posixpath.dirname(data["path"]) or ".",    # the group's folder ("." = repo root)
                loc=0, kind="internal", is_external=False, is_package=True, parse_error=None,
                module_count=0, modules=[],
            )
        summary = packages.nodes[package]
        summary["loc"] += data["loc"]
        summary["module_count"] += 1
        summary["modules"].append(node)

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
