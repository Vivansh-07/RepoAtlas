"""HTTP layer: routes and error handling. The real work lives in pipeline.py."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.cache import Cache
from app.errors import RepoAtlasError
from app.generators import generate
from app.models import AnalyzeRequest, ErrorResponse, GenerateResponse, GraphResponse
from app.pipeline import analyze_github_repo

app = FastAPI(
    title="RepoAtlas",
    version="0.1.0",
    description="Turn a Python repo's imports into an interactive dependency graph.",
)


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must re-check before reusing a cached copy.

    Without a Cache-Control header, browsers guess how long a file stays fresh
    (often hours), so after an update users would keep running old JS against new
    HTML. "no-cache" still allows caching, but each use costs one quick request
    that answers 304 Not Modified when nothing changed.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@lru_cache
def get_cache() -> Cache:
    # Created on first use (not at import), and tests can swap it out through
    # app.dependency_overrides without ever touching the real database.
    return Cache(config.CACHE_DB_PATH)


@app.exception_handler(RepoAtlasError)
async def handle_repoatlas_error(request: Request, exc: RepoAtlasError) -> JSONResponse:
    # Every pipeline error knows its own HTTP status (see errors.py). Same
    # {"detail": ...} shape as FastAPI's own errors, so the frontend handles one format.
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_ERRORS = {
    code: {"model": ErrorResponse, "description": text}
    for code, text in {
        400: "Not a valid https://github.com/<owner>/<repo> URL",
        404: "Repository not found, or private",
        413: "Too many Python files",
        422: "No Python files found",
        502: "git failed",
        503: "Too many analyses running; try again shortly",
        504: "GitHub took too long",
    }.items()
}


@app.post("/api/analyze", response_model=GraphResponse, responses=_ERRORS)
def analyze(request: AnalyzeRequest, cache: Annotated[Cache, Depends(get_cache)]) -> dict:
    # A plain `def`, not `async def`: cloning and parsing block for seconds.
    # FastAPI runs plain functions on a worker thread, so the server can keep
    # answering other requests meanwhile. Blocking inside `async def` would
    # freeze the whole server.
    return analyze_github_repo(request.repo_url, cache, request.include_external)


@app.get(
    "/api/generate",
    response_model=GenerateResponse,
    responses={400: {"model": ErrorResponse, "description": "Parameters out of range"}},
)
def generate_graph(
    # GET, not POST: the graph is a pure function of these parameters, so a
    # generate URL can be bookmarked or shared.
    model: Annotated[Literal["er", "ba", "ws"], Query(description="er = Erdős–Rényi, ba = Barabási–Albert, ws = Watts–Strogatz")],
    n: Annotated[int, Query(description="Number of nodes (2–500)")] = 100,
    p: Annotated[float | None, Query(description="ER: link probability. WS: rewiring probability.")] = None,
    m: Annotated[int | None, Query(description="BA: links per new node")] = None,
    k: Annotated[int | None, Query(description="WS: ring neighbours per node (even)")] = None,
    seed: Annotated[int | None, Query(description="Random seed; omit it and one is picked and returned")] = None,
) -> dict:
    # Plain def again: generating and measuring up to 500 nodes is CPU work.
    return generate(model, n, p, m, k, seed)


# The frontend: static/index.html at "/", plus its CSS and JS files.
# Must stay LAST: a mount at "/" matches every path, and FastAPI checks routes in
# the order they were added, so anything registered after this would be unreachable.
app.mount("/", RevalidatingStaticFiles(directory=config.STATIC_DIR, html=True), name="static")
