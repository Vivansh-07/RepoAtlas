"""Package graph tests: the sample repo (known packages) and small hand-made graphs."""

from pathlib import Path

import networkx as nx
import pytest

from app.analytics import analyze
from app.graph_builder import build_graph
from app.packages import TOP_LEVEL, build_package_graph, group_modules, package_of, short_label
from app.parser import parse_repo
from app.resolver import resolve_repo

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.mark.parametrize("module, is_package, path, expected", [
    ("flask.json.provider", False, "src/flask/json/provider.py", "flask.json"),
    ("flask.json", True, "src/flask/json/__init__.py", "flask.json"),   # a package's __init__ belongs to it
    ("flask.app", False, "src/flask/app.py", "flask"),
    ("flask", True, "src/flask/__init__.py", "flask"),
    ("setup", False, "setup.py", TOP_LEVEL),                            # repo root
    # The main file of an example project: grouped by folder, not merged with other examples
    ("aliases", False, "examples/aliases/aliases.py", "examples/aliases/"),
])
def test_package_of(module, is_package, path, expected):
    assert package_of(module, is_package, path) == expected


@pytest.mark.parametrize("package, label", [
    ("flask", "flask"),
    ("flask.json", "json"),                       # like a module's label: the last part
    ("examples/tutorial/tests/", "tests/"),
    (TOP_LEVEL, TOP_LEVEL),
])
def test_short_label(package, label):
    assert short_label(package) == label


def test_top_level_modules_of_different_folders_stay_apart():
    g = nx.DiGraph()
    for name, path in [("aliases", "examples/aliases/aliases.py"), ("colors", "examples/colors/colors.py"),
                       ("setup", "setup.py")]:
        g.add_node(name, label=name, package="", path=path, loc=5, kind="internal", is_external=False,
                   is_package=False, parse_error=None)
    packages = build_package_graph(g)
    assert {n: d["path"] for n, d in packages.nodes(data=True)} == {
        "examples/aliases/": "examples/aliases", "examples/colors/": "examples/colors", TOP_LEVEL: "."}


def test_folders_sharing_a_name_stay_apart():
    # Like Flask: tests/ at the root and in a nested example project are both `tests`.
    groups = group_modules({
        "tests.test_a": ("tests", "tests"),
        "tests.conftest": ("tests", "tests"),
        "tests.test_b": ("tests", "examples/tut/tests"),
    })
    assert groups == {"tests.test_a": "tests", "tests.conftest": "tests",       # shallowest keeps the name
                      "tests.test_b": "examples/tut/tests/"}


def test_folder_with_several_package_names_is_named_by_its_path():
    # After a module name clash the parser uses the full path, so one folder can
    # hold `tests.test_b` and `examples.tut.tests.conftest`: still one group.
    groups = group_modules({
        "tests.test_b": ("tests", "examples/tut/tests"),
        "examples.tut.tests.conftest": ("examples.tut.tests", "examples/tut/tests"),
    })
    assert set(groups.values()) == {"examples/tut/tests/"}


def test_package_node_path_is_its_folder():
    g = nx.DiGraph()
    for name, path in [("tests.test_a", "tests/test_a.py"), ("tests.test_b", "examples/tut/tests/test_b.py")]:
        g.add_node(name, label=name, package="tests", path=path, loc=5, kind="internal", is_external=False,
                   is_package=False, parse_error=None)
    packages = build_package_graph(g)
    assert {n: d["path"] for n, d in packages.nodes(data=True)} == {
        "tests": "tests", "examples/tut/tests/": "examples/tut/tests"}


@pytest.fixture(scope="module")
def sample():
    parsed = parse_repo(SAMPLE)
    packages = build_package_graph(build_graph(parsed, resolve_repo(parsed)))
    return packages, analyze(packages)


def internal_edges(graph):
    return {(u, v, d["weight"]) for u, v, d in graph.edges(data=True) if d["kind"] == "internal"}


def test_sample_packages_and_members(sample):
    packages, _ = sample
    internal = {n: d for n, d in packages.nodes(data=True) if not d["is_external"]}
    assert {n: sorted(d["modules"]) for n, d in internal.items()} == {
        "shop": ["shop", "shop.models", "shop.orders", "shop.payments", "shop.utils"],
        "shop.api": ["shop.api", "shop.api.routes"],
        "tests": ["tests.test_orders"],
        TOP_LEVEL: ["broken", "setup"],
    }
    assert internal["shop"]["module_count"] == 5
    assert internal["shop"]["path"] == "src/shop"
    modules = parse_repo(SAMPLE).modules
    assert internal["shop"]["loc"] == sum(modules[m].loc for m in internal["shop"]["modules"])  # lines add up


def test_sample_package_edges(sample):
    packages, _ = sample
    # routes imports utils, orders and models: three module edges -> weight 3.
    # Imports inside "shop" (incl. the orders <-> payments cycle) vanish into its node.
    assert internal_edges(packages) == {("shop.api", "shop", 3), ("tests", "shop", 1)}


def test_cycle_inside_a_package_is_not_a_package_cycle(sample):
    packages, summary = sample
    assert summary.num_cycles == 0
    assert not packages.nodes["shop"]["in_cycle"]


def test_external_libraries_are_kept(sample):
    packages, summary = sample
    assert packages.nodes["requests"]["module_count"] == 0
    assert packages.has_edge("shop.api", "requests")
    assert (summary.num_stdlib, summary.num_third_party) == (4, 3)


def test_sample_package_analytics(sample):
    _, summary = sample
    assert summary.num_nodes == 4                       # internal packages only
    assert summary.top_modules[0].id == "shop"          # everything depends on it


# --- small hand-made graphs -------------------------------------------------------

def module_graph(edges, type_only=()):
    """Module DiGraph with build_graph's attributes; module 'a.x' lives in package 'a'."""
    g = nx.DiGraph()
    for node in sorted({n for e in [*edges, *type_only] for n in e}):
        g.add_node(node, label=node, package=node.rpartition(".")[0], path=node.replace(".", "/") + ".py",
                   loc=10, kind="internal", is_external=False, is_package=False, parse_error=None)
    for u, v in edges:
        g.add_edge(u, v, weight=1, kind="internal", type_only=False)
    for u, v in type_only:
        g.add_edge(u, v, weight=1, kind="internal", type_only=True)
    return g


def test_packages_importing_each_other_form_a_package_cycle():
    # No module-level cycle at all, yet packages a and b depend on each other.
    packages = build_package_graph(module_graph([("a.x", "b.y"), ("b.z", "a.w")]))
    summary = analyze(packages)
    assert (summary.num_cycles, summary.largest_cycle_size) == (1, 2)
    assert packages.nodes["a"]["in_cycle"] and packages.nodes["b"]["in_cycle"]


def test_package_edge_is_type_only_only_if_every_import_is():
    packages = build_package_graph(module_graph(
        edges=[("a.x", "b.y")],
        type_only=[("a.w", "b.z"), ("c.p", "b.y")],
    ))
    assert packages.edges["a", "b"]["type_only"] is False      # one runtime import is enough
    assert packages.edges["a", "b"]["weight"] == 2
    assert packages.edges["c", "b"]["type_only"] is True
