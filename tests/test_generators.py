"""Graph Lab tests. Where possible the expected values come from graph theory,
so these check that the statistics mean what the UI says they mean."""

import pytest

from app.errors import InvalidParams
from app.generators import degree_distribution, generate


def summary_of(**kwargs):
    return generate(seed=42, **kwargs)["summary"]


# --- the three models --------------------------------------------------------

def test_er_extremes():
    empty = summary_of(model="er", n=20, p=0.0)
    assert (empty["num_edges"], empty["num_components"]) == (0, 20)
    complete = summary_of(model="er", n=20, p=1.0)
    assert complete["num_edges"] == 20 * 19 // 2            # every pair linked
    assert complete["avg_clustering"] == 1.0
    assert complete["avg_path_length"] == 1.0


def test_ba_edge_count_and_connectedness():
    s = summary_of(model="ba", n=100, m=3)
    assert s["num_edges"] == 3 * (100 - 3)                    # m new links per arriving node
    assert s["num_components"] == 1


def test_ba_has_hubs_but_er_does_not():
    # Same average degree (about 4), very different maximum degree.
    ba = summary_of(model="ba", n=500, m=2)
    er = summary_of(model="er", n=500, p=4 / 499)
    assert ba["max_degree"] > 5 * ba["avg_degree"]            # heavy tail: hubs
    assert er["max_degree"] < 4 * er["avg_degree"]            # bell curve: no hubs


def test_ws_ring_lattice_matches_theory():
    s = summary_of(model="ws", n=60, k=4, p=0.0)
    assert s["num_edges"] == 60 * 4 // 2
    # Clustering of a ring lattice is exactly 3(k-2) / (4(k-1)) = 0.5 for k = 4
    assert s["avg_clustering"] == pytest.approx(0.5)


def test_ws_small_world_effect():
    lattice = summary_of(model="ws", n=200, k=6, p=0.0)
    small_world = summary_of(model="ws", n=200, k=6, p=0.1)
    # A little rewiring makes paths much shorter while keeping most clustering.
    assert small_world["avg_path_length"] < 0.5 * lattice["avg_path_length"]
    assert small_world["avg_clustering"] > 0.5 * lattice["avg_clustering"]


# --- shape of the result -----------------------------------------------------

def test_same_seed_same_graph():
    a = generate(model="ba", n=50, m=2, seed=7)
    b = generate(model="ba", n=50, m=2, seed=7)
    assert [e["data"]["id"] for e in a["edges"]] == [e["data"]["id"] for e in b["edges"]]


def test_seed_is_picked_and_reported_when_missing():
    assert isinstance(generate(model="er", n=30, p=0.1)["summary"]["seed"], int)


def test_only_relevant_parameters_are_reported():
    s = summary_of(model="ba", n=30, m=2)
    assert (s["m"], s["p"], s["k"]) == (2, None, None)


def test_nodes_carry_their_measurements():
    result = generate(model="ws", n=20, k=4, p=0.0, seed=1)
    node = result["nodes"][0]["data"]
    assert isinstance(node["id"], str)                         # Cytoscape needs string ids
    assert node["degree"] == 4 and node["clustering"] == pytest.approx(0.5)


def test_degree_distribution_is_consistent():
    result = generate(model="ba", n=120, m=2, seed=3)
    dist, s = result["degree_distribution"], result["summary"]
    assert sum(dist["count"]) == s["num_nodes"]                # every node counted once
    assert len(dist["degree"]) == s["max_degree"] + 1          # 0 .. max, gaps included
    assert sum(d * c for d, c in zip(dist["degree"], dist["count"])) == 2 * s["num_edges"]


def test_degree_distribution_of_empty_graph():
    import networkx as nx
    assert degree_distribution(nx.empty_graph(3)) == {"degree": [0], "count": [3]}


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    dict(model="er", n=1, p=0.1),                 # too few nodes
    dict(model="er", n=501, p=0.01),              # too many nodes
    dict(model="er", n=50, p=1.5),                # not a probability
    dict(model="er", n=500, p=0.5),               # ~62,000 edges: over the budget
    dict(model="ba", n=10, m=10),                 # m must be < n
    dict(model="ba", n=10, m=0),
    dict(model="ws", n=20, k=3, p=0.1),           # k must be even
    dict(model="ws", n=6, k=6, p=0.1),            # k must be < n
    dict(model="xx", n=20),
])
def test_invalid_parameters(kwargs):
    with pytest.raises(InvalidParams):
        generate(seed=1, **kwargs)
