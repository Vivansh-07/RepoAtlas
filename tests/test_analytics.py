"""Graph builder + analytics tests: the sample repo (known answers) and small
hand-made graphs where the right result is obvious."""

from pathlib import Path

import networkx as nx
import pytest

from app.analytics import analyze, dependency_depth, detect_communities, find_cycles
from app.graph_builder import build_graph, internal_subgraph
from app.parser import parse_repo
from app.resolver import resolve_repo

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"


def graph_of(edges, extra_nodes=()):
    """Internal-only DiGraph with the node attributes analyze() expects."""
    g = nx.DiGraph()
    for node in sorted({n for e in edges for n in e} | set(extra_nodes)):
        g.add_node(node, is_external=False, kind="internal")
    g.add_edges_from(edges, weight=1)
    return g


@pytest.fixture(scope="module")
def sample():
    parsed = parse_repo(SAMPLE)
    graph = build_graph(parsed, resolve_repo(parsed))
    return graph, analyze(graph)


# --- graph builder -------------------------------------------------------------

def test_graph_has_internal_and_external_nodes(sample):
    graph, _ = sample
    external = {n for n, ext in graph.nodes(data="is_external") if ext}
    assert external == {"json", "os", "re", "requests", "setuptools", "pytest"}
    assert internal_subgraph(graph).number_of_nodes() == 10


def test_node_attributes(sample):
    graph, _ = sample
    node = graph.nodes["shop.api.routes"]
    assert (node["label"], node["package"], node["path"]) == ("routes", "shop.api", "src/shop/api/routes.py")
    assert (node["kind"], node["is_external"]) == ("internal", False)
    assert (graph.nodes["requests"]["kind"], graph.nodes["requests"]["is_external"]) == ("third_party", True)


def test_edges_point_from_importer_to_imported(sample):
    graph, _ = sample
    assert graph.has_edge("shop.models", "shop.utils")
    assert not graph.has_edge("shop.utils", "shop.models")


# --- analytics on the sample repo ----------------------------------------------

def test_sample_summary(sample):
    _, s = sample
    assert (s.num_nodes, s.num_edges) == (10, 10)
    assert (s.num_cycles, s.largest_cycle_size) == (1, 2)
    assert s.dependency_depth == 3        # tests.test_orders -> {orders, payments} -> models -> utils
    assert (s.num_stdlib, s.num_third_party) == (3, 3)


def test_sample_cycle_is_marked(sample):
    graph, _ = sample
    in_cycle = {n for n, flag in graph.nodes(data="in_cycle") if flag}
    assert in_cycle == {"shop.orders", "shop.payments"}
    assert graph.nodes["shop.orders"]["scc_id"] == graph.nodes["shop.payments"]["scc_id"] == 0
    cycle_edges = {(u, v) for u, v, flag in graph.edges(data="in_cycle") if flag}
    assert cycle_edges == {("shop.orders", "shop.payments"), ("shop.payments", "shop.orders")}


def test_sample_pagerank(sample):
    graph, s = sample
    # utils is imported by models, payments and routes (and models is popular too)
    assert [m["id"] for m in s.top_modules[:2]] == ["shop.utils", "shop.models"]
    assert graph.nodes["shop.utils"]["pagerank_rank"] == 1
    internal_total = sum(pr for n, pr in graph.nodes(data="pagerank") if not graph.nodes[n]["is_external"])
    assert internal_total == pytest.approx(1.0)


def test_external_nodes_get_neutral_analytics(sample):
    graph, _ = sample
    node = graph.nodes["requests"]
    assert (node["pagerank"], node["pagerank_rank"], node["community"]) == (0.0, None, None)
    assert node["in_degree"] == 1          # used by shop.api.routes


def test_degrees_count_internal_edges_only(sample):
    graph, _ = sample
    utils = graph.nodes["shop.utils"]      # imports only os and re (external)
    assert (utils["in_degree"], utils["out_degree"]) == (3, 0)


def test_isolated_modules_have_no_community(sample):
    graph, _ = sample
    for name in ("setup", "broken", "shop.api"):   # no internal imports either way
        assert graph.nodes[name]["community"] is None
    assert graph.nodes["shop.orders"]["community"] is not None


# --- small hand-made graphs ----------------------------------------------------

def test_two_clusters_are_found():
    big = [(f"a{i}", f"a{j}") for i in range(5) for j in range(i + 1, 5)]     # 5-node clique
    small = [(f"b{i}", f"b{j}") for i in range(3) for j in range(i + 1, 3)]   # 3-node clique
    communities, modularity = detect_communities(graph_of(big + small + [("a0", "b0")]))
    assert communities == [{f"a{i}" for i in range(5)}, {"b0", "b1", "b2"}]  # largest first
    assert modularity > 0.3


def test_depth_of_a_chain_and_of_a_cycle():
    assert dependency_depth(graph_of([("a", "b"), ("b", "c"), ("c", "d")])) == 3
    # a <-> b collapses to one step, then -> c
    assert dependency_depth(graph_of([("a", "b"), ("b", "a"), ("b", "c")])) == 1


def test_cycles_largest_first():
    g = graph_of([("x", "y"), ("y", "x"), ("a", "b"), ("b", "c"), ("c", "a"), ("c", "z")])
    assert find_cycles(g) == [{"a", "b", "c"}, {"x", "y"}]


def test_graph_without_edges():
    s = analyze(graph_of([], extra_nodes=["a", "b", "c"]))
    assert (s.num_edges, s.num_communities, s.modularity, s.num_cycles, s.dependency_depth) == (0, 0, 0.0, 0, 0)
    assert [m["pagerank"] for m in s.top_modules] == pytest.approx([1 / 3] * 3)
