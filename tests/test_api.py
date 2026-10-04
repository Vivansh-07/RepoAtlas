"""API tests, fully offline: the GitHub calls are faked and "cloning" hands back
the sample repo, so we test real HTTP behaviour (status codes, JSON, caching)."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.cache import Cache
from app.errors import GitTimeout, RepoNotFound
from app.main import app, get_cache

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"
FAKE_SHA = "a" * 40
URL = "https://github.com/acme/shop"


@pytest.fixture
def clones(monkeypatch):
    """Fake GitHub. Returns the list of repos 'cloned', so tests can check
    whether a clone happened at all."""
    calls = []

    @contextmanager
    def fake_clone(repo):
        calls.append(repo.slug)
        yield SAMPLE

    monkeypatch.setattr(pipeline, "get_head_sha", lambda repo: FAKE_SHA)
    monkeypatch.setattr(pipeline, "read_local_sha", lambda path: FAKE_SHA)
    monkeypatch.setattr(pipeline, "clone_repo", fake_clone)
    return calls


@pytest.fixture
def client(tmp_path):
    # Swap the real cache for a throwaway one: FastAPI's dependency injection
    # makes this a one-liner instead of patching module globals.
    app.dependency_overrides[get_cache] = lambda: Cache(tmp_path / "cache.db")
    yield TestClient(app)
    app.dependency_overrides.clear()


def analyze(client, **body):
    return client.post("/api/analyze", json={"repo_url": URL, **body})


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_frontend_is_served_at_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "RepoAtlas" in resp.text
    assert client.get("/style.css").status_code == 200
    # The catch-all static mount must not swallow the API or the docs
    assert client.get("/api/health").status_code == 200
    assert client.get("/docs").status_code == 200


def test_static_files_must_be_revalidated(client):
    # Otherwise browsers keep running stale JS/CSS after an update.
    for path in ["/", "/style.css", "/app.js", "/lab.js"]:
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_analyze_returns_a_cytoscape_graph(client, clones):
    resp = analyze(client)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["repo"], body["commit_sha"], body["cached"]) == ("acme/shop", FAKE_SHA, False)
    assert len(body["nodes"]) == 10
    assert not any(n["data"]["is_external"] for n in body["nodes"])
    edges = {e["data"]["id"]: e["data"] for e in body["edges"]}
    assert edges["shop.orders->shop.payments"]["in_cycle"]
    assert edges["shop.models->shop.orders"]["type_only"]
    assert body["summary"]["num_cycles"] == 1
    assert body["summary"]["top_modules"][0] == {"id": "shop.utils", "pagerank": pytest.approx(0.2591, abs=1e-3)}


def test_second_request_is_served_from_cache(client, clones):
    first = analyze(client).json()
    second = analyze(client).json()
    assert (first["cached"], second["cached"]) == (False, True)
    assert clones == ["acme/shop"]                 # cloned only once
    assert second["nodes"] == first["nodes"]


def test_include_external(client, clones):
    body = analyze(client, include_external=True).json()
    external = {n["data"]["id"] for n in body["nodes"] if n["data"]["is_external"]}
    assert external == {"json", "os", "re", "typing", "requests", "setuptools", "pytest"}
    assert any(e["data"]["target"] == "requests" for e in body["edges"])


def test_one_cache_entry_serves_both_toggle_states(client, clones):
    analyze(client)
    body = analyze(client, include_external=True).json()
    assert body["cached"] and len(body["nodes"]) == 17
    assert clones == ["acme/shop"]


@pytest.mark.parametrize("payload, status", [
    ({"repo_url": "https://gitlab.com/a/b"}, 400),
    ({"repo_url": "https://github.com/a/b; rm -rf /"}, 400),
    ({}, 422),                          # missing field: caught by FastAPI/Pydantic
    ({"repo_url": "x" * 301}, 422),     # over max_length
])
def test_bad_requests_never_clone(client, clones, payload, status):
    assert client.post("/api/analyze", json=payload).status_code == status
    assert clones == []


def test_generate_endpoint(client):
    resp = client.get("/api/generate", params={"model": "ws", "n": 30, "k": 4, "p": 0.1, "seed": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert (len(body["nodes"]), len(body["edges"])) == (30, 60)
    assert body["summary"]["seed"] == 5
    assert sum(body["degree_distribution"]["count"]) == 30


@pytest.mark.parametrize("params, status", [
    ({"model": "ba", "n": 10, "m": 10}, 400),      # our semantic check
    ({"model": "xyz", "n": 10}, 422),              # FastAPI's own validation (unknown model)
    ({"model": "er", "n": "many"}, 422),           # not a number
])
def test_generate_rejects_bad_parameters(client, params, status):
    assert client.get("/api/generate", params=params).status_code == status


@pytest.mark.parametrize("error, status", [(RepoNotFound("no such repo"), 404),
                                           (GitTimeout("too slow"), 504)])
def test_pipeline_errors_become_status_codes(client, monkeypatch, error, status):
    def fail(repo):
        raise error

    monkeypatch.setattr(pipeline, "get_head_sha", fail)
    resp = analyze(client)
    assert (resp.status_code, resp.json()) == (status, {"detail": str(error)})
