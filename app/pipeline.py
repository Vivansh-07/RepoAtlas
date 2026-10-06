"""The whole analysis, from GitHub URL to Cytoscape-ready JSON.

Nothing here knows about HTTP, so it can be tested and reused without a server.
"""

from __future__ import annotations

import threading
from dataclasses import asdict

from app import config
from app.analytics import analyze
from app.cache import Cache
from app.cloner import clone_repo, get_head_sha, parse_repo_url, read_local_sha
from app.errors import ServerBusy
from app.graph_builder import build_graph
from app.packages import build_package_graph
from app.parser import ParsedRepo, parse_repo
from app.resolver import resolve_repo
from app.serializer import serialize_graph, without_external

# A counter of free "analysis slots", shared by all request threads. acquire()
# takes one (waiting if none are free) and release() gives it back. Bounded =
# releasing more slots than exist is a bug that raises instead of passing silently.
_analysis_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_ANALYSES)


def analyze_parsed(parsed: ParsedRepo) -> dict:
    """Resolve -> build graph -> analytics -> JSON, for modules and for packages.
    Externals are always included."""
    graph = build_graph(parsed, resolve_repo(parsed))
    summary = analyze(graph)
    packages = build_package_graph(graph)
    package_summary = analyze(packages)      # the same analytics, one level up
    return {
        "summary": asdict(summary),
        **serialize_graph(graph),
        "packages": {"summary": asdict(package_summary), **serialize_graph(packages)},
    }


def _visible(elements: dict, include_external: bool) -> dict:
    elements = {"nodes": elements["nodes"], "edges": elements["edges"]}
    return elements if include_external else without_external(elements)


def analyze_github_repo(repo_url: str, cache: Cache, include_external: bool = False) -> dict:
    repo = parse_repo_url(repo_url)

    # Asking GitHub for the latest SHA takes about a second; cloning takes several.
    # Checking the cache first means a repeat request never clones at all.
    sha = get_head_sha(repo)
    payload = cache.get(repo.slug, sha)
    cached = payload is not None

    if not cached:
        # Cloning and parsing are the memory-hungry part, so only a few may run at
        # once. Cache hits above never need a slot, so they stay instant.
        if not _analysis_slots.acquire(timeout=config.ANALYSIS_WAIT_S):
            raise ServerBusy("RepoAtlas is busy analysing other repositories. Try again in a minute.")
        try:
            with clone_repo(repo) as path:
                sha = read_local_sha(path)   # in case someone pushed since get_head_sha()
                parsed = parse_repo(path)
            # Analyse after the `with`: the temp folder is already deleted by now,
            # and nothing below needs the files any more.
            payload = analyze_parsed(parsed)
        finally:
            _analysis_slots.release()   # always give the slot back, even after an error
        cache.put(repo.slug, sha, payload)

    packages = payload["packages"]
    return {
        "repo": repo.slug, "commit_sha": sha, "cached": cached,
        "summary": payload["summary"],
        **_visible(payload, include_external),
        "packages": {"summary": packages["summary"], **_visible(packages, include_external)},
    }
