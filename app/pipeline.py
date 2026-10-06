"""The whole analysis, from GitHub URL to Cytoscape-ready JSON.

Nothing here knows about HTTP, so it can be tested and reused without a server.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict

from app import config
from app.analytics import analyze
from app.cache import Cache
from app.cloner import RepoRef, clone_repo, get_head_sha, parse_repo_url, read_local_sha
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

# One lock per repository, so simultaneous first requests for the same repo
# clone it only once: the others wait, then find the result in the cache. A
# fixed set of locks picked by hash ("lock striping") keeps memory bounded
# however many repos are analysed; two repos that share a lock just take turns.
_repo_locks = [threading.Lock() for _ in range(64)]

# Recently asked latest commits: repo slug -> (sha, when). `git ls-remote` takes
# about a second, which is most of a cache hit's time, so the answer is reused
# for config.HEAD_SHA_TTL_S seconds.
_head_shas: dict[str, tuple[str, float]] = {}
_head_shas_lock = threading.Lock()


def _lock_for(slug: str) -> threading.Lock:
    return _repo_locks[hash(slug) % len(_repo_locks)]


def _latest_sha(repo: RepoRef) -> str:
    with _head_shas_lock:
        known = _head_shas.get(repo.slug)
    if known and time.monotonic() - known[1] < config.HEAD_SHA_TTL_S:
        return known[0]
    sha = get_head_sha(repo)          # outside the lock: a network call mustn't block other repos
    _remember_sha(repo.slug, sha)
    return sha


def _remember_sha(slug: str, sha: str) -> None:
    now = time.monotonic()
    with _head_shas_lock:
        # Drop expired answers, so the table only holds recently used repos.
        for key in [k for k, (_, when) in _head_shas.items() if now - when >= config.HEAD_SHA_TTL_S]:
            del _head_shas[key]
        _head_shas[slug] = (sha, now)


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


def _clone_and_analyze(repo: RepoRef) -> tuple[str, dict]:
    """Clone, parse and analyse. Returns (the commit actually cloned, payload)."""
    # Cloning and parsing are the memory-hungry part, so only a few may run at
    # once. Cache hits never need a slot, so they stay instant.
    if not _analysis_slots.acquire(timeout=config.ANALYSIS_WAIT_S):
        raise ServerBusy("RepoAtlas is busy analysing other repositories. Try again in a minute.")
    try:
        with clone_repo(repo) as path:
            sha = read_local_sha(path)   # in case someone pushed since ls-remote
            parsed = parse_repo(path)
        # Analyse after the `with`: the temp folder is already deleted by now,
        # and nothing below needs the files any more.
        return sha, analyze_parsed(parsed)
    finally:
        _analysis_slots.release()   # always give the slot back, even after an error


def analyze_github_repo(repo_url: str, cache: Cache, include_external: bool = False) -> dict:
    repo = parse_repo_url(repo_url)

    # Asking GitHub for the latest SHA takes about a second (or nothing, if we
    # asked in the last minute); cloning takes several. Checking the cache first
    # means a repeat request never clones at all.
    sha = _latest_sha(repo)
    payload = cache.get(repo.slug, sha)
    cached = payload is not None

    if not cached:
        with _lock_for(repo.slug):
            # Check again: another request for this repo may have finished the
            # analysis while we waited for the lock ("double-checked locking").
            payload = cache.get(repo.slug, sha)
            cached = payload is not None
            if not cached:
                sha, payload = _clone_and_analyze(repo)
                cache.put(repo.slug, sha, payload)
                _remember_sha(repo.slug, sha)

    packages = payload["packages"]
    return {
        "repo": repo.slug, "commit_sha": sha, "cached": cached,
        "summary": payload["summary"],
        **_visible(payload, include_external),
        "packages": {"summary": packages["summary"], **_visible(packages, include_external)},
    }
