# RepoAtlas

[![tests](https://github.com/Vivansh-07/RepoAtlas/actions/workflows/tests.yml/badge.svg)](https://github.com/Vivansh-07/RepoAtlas/actions/workflows/tests.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688)
![License: MIT](https://img.shields.io/badge/license-MIT-6d28d9)

**Paste a public GitHub repository and get an interactive map of how its Python modules depend on each other:** what's central, what clusters together, and where imports go round in circles.

**Live demo: [repoatlas-iqbu.onrender.com](https://repoatlas-iqbu.onrender.com)** · try [Flask's package view](https://repoatlas-iqbu.onrender.com/?repo=pallets/flask&layout=force&level=packages) or the [Graph Lab](https://repoatlas-iqbu.onrender.com/?lab=ba&n=300&m=2&seed=4&layout=force). It runs on a free plan, so the first visit after a quiet spell takes 30–60 s to wake the server.

![RepoAtlas showing the pallets/flask repository](docs/images/explorer-flask.png)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Vivansh-07/RepoAtlas)

---

## Why

Large codebases are hard to understand because their structure is invisible. A folder tree shows where files live, not which files rely on which, where the core of the system is, or where circular dependencies make every change risky. RepoAtlas reads a repository's imports and turns that hidden structure into a map in a few seconds.

It's for developers joining an unfamiliar codebase, tech leads planning a refactor, reviewers checking whether a change touches a heavily used module, and students who want to learn from open source but don't know where to start reading.

## Features

![Demo: analysing Flask, exploring a module, switching layouts, then the Graph Lab](docs/images/demo.gif)

### Repo Explorer
- **One URL in, a dependency graph out.** Accepts `https://github.com/owner/repo` or just `owner/repo`.
- **Visual analytics on top of the graph**
  - size = importance (PageRank)
  - colour = cluster (Louvain communities)
  - red halo = circular dependency (strongly connected components)
  - dashed arrow = type-only import (`if TYPE_CHECKING:`)
- **Two levels of detail: Modules or Packages.**
  - The package view collapses modules into packages: Flask's 82 modules become 20 packages, with their own PageRank, communities and **package-level cycles**.
  - Click a package to list its modules, then click one to drill down. From a module, its package link goes back up.
- **Four layouts**, each answering a question:
  - **Force:** what belongs together?
  - **Hierarchy:** what builds on what? (a layered layout written for this project)
  - **Rings:** where is the core?
  - **Circle:** how big is each cluster?
- **Explore:**
  - hover for focus + context
  - click for a details card (path, lines, rank, community, clickable *imports* and *imported by*)
  - search with suggestions
  - zoom, with labels appearing as nodes grow on screen
- **Show options:** external libraries, type-only imports, only circular dependencies. These are instant, because filtering happens in the browser.
- **Summary panel:** modules, imports, communities, cycle groups, dependency depth, modularity, and the 10 most important modules.
- **Shareable links** (`/?repo=pallets/flask&layout=hierarchy&level=packages`) and **PNG export** of the current view.

### Graph Lab
- Generate **Erdős–Rényi**, **Barabási–Albert** and **Watts–Strogatz** random graphs with sliders and a seed, so any graph can be reproduced.
- **Statistics** chosen to show each model's signature: degree distribution and max degree (scale-free hubs), clustering and average path length (small world), components and giant-component size (the ER phase transition).
- **Degree-distribution chart** with a **log–log** mode, where a power law becomes a straight line.
- Watts–Strogatz **shortcuts drawn in violet** on the ring.

| | |
|---|---|
| ![Details card for flask.app with its neighbourhood in focus](docs/images/explorer-details.png) | ![pallets/click in the Hierarchy layout](docs/images/explorer-hierarchy.png) |
| **Click a module:** details, imports and imported-by, with its neighbourhood in focus. | **Hierarchy:** tests on top, foundations at the bottom, each cycle group on one red row (pallets/click). |
| ![Only the circular dependencies of Flask](docs/images/explorer-cycles.png) | ![Watts–Strogatz graph in the Circle layout with violet shortcuts](docs/images/lab-ws.png) |
| **Only circular dependencies:** Flask's 11-module core loop and an example app's 2-module loop. | **Graph Lab:** a Watts–Strogatz small world, a ring plus a few random shortcuts. |
| ![Flask's package view with the flask package's card listing its modules](docs/images/explorer-packages.png) | ![The module view after drilling down to flask.sansio.app](docs/images/explorer-drilldown.png) |
| **Packages:** Flask's 82 modules as 20 packages. The red loop is `flask` ↔ `json` ↔ `sansio`. A package's card lists its modules. | **Drill down:** a module picked from that list opens in the module view, with a link back up to its package. |

## Reading the map

| You see | It means |
|---|---|
| A circle | One Python module (one `.py` file; a package's `__init__.py` is the package) |
| An arrow A → B | A imports B: A depends on B |
| Bigger circle | Higher PageRank: important modules depend on it |
| Same colour | Same Louvain community: these modules import each other a lot |
| Red ring and halo, red arrows | Part of a circular dependency |
| Grey | No imports to or from the rest of the repo |
| Dashed arrow | Type-only import: it never runs, so it can't cause a circular-import error |
| Dashed grey circle | External library (shown on request) |
| *Package view:* a circle | A whole package (or a folder of loose files); an arrow stands for all the imports between two packages |

## What it finds in real code

| Repository (commit) | Modules | Imports | Communities (modularity) | Cycle groups | Depth | Most important |
|---|---|---|---|---|---|---|
| pallets/flask (`d73fa1c`) | 82 | 162 (+24 type-only) | 8 (0.37) | 11, 2 | 9 | `flask`, `flask.globals` |
| psf/requests (`611c616`) | 35 | 94 (+12) | 6 (0.21) | none | 10 | `requests.compat` |
| pallets/click (`2247b35`) | 90 | 163 (+5) | 4 (0.30) | 7, 2, 2 | 6 | `click._compat` |
| encode/httpx (`b5addb6`) | 60 | 116 (+6) | 4 (0.37) | 2 | 11 | `httpx`, `httpx._types` |

A few things these maps reveal:
- **Flask's core is one 11-module loop.** `app`, `blueprints`, `cli`, `templating`, `wrappers` and the package itself all reach each other. It still works at runtime because Flask defers some imports into functions.
- **The biggest file isn't the most important.** `flask.app` has 1,238 lines but ranks #27: five of its six importers use it only for type hints.
- **A legacy shim became load-bearing.** requests' #1 module is `requests.compat`, a Python 2/3 compatibility layer still imported by 14 modules.
- **Some cycles only exist on one platform.** click's `_compat ↔ _winconsole` loop only runs on Windows (`if sys.platform.startswith("win")`).
- **Loops between packages.** At package level, Flask's 20 packages keep one loop: `flask` ↔ `flask.json` ↔ `flask.sansio`. httpx's 5 packages keep one too: `httpx` ↔ `httpx._transports`. Packages in a loop can't be split out or understood on their own. requests and click have none.

## How it works

```mermaid
flowchart TB
    B["Browser<br/>vanilla JS · Cytoscape.js · Chart.js"] -->|"POST /api/analyze"| P
    B -->|"GET /api/generate"| GEN
    subgraph S["FastAPI backend"]
        P["pipeline"] --> CL["cloner<br/>check URL · ls-remote · sparse clone"]
        CL --> PA["parser<br/>find .py · name modules · ast imports"]
        PA --> RE["resolver<br/>internal / stdlib / third-party"]
        RE --> GB["graph_builder<br/>NetworkX DiGraph"]
        GB --> AN["analytics<br/>PageRank · Louvain · SCC · depth"]
        AN --> PK["packages<br/>collapse into packages · same analytics"]
        PK --> SE["serializer<br/>Cytoscape JSON"]
        GEN["generators<br/>ER · BA · WS + stats"]
    end
    P <--> DB[("SQLite cache<br/>repo · commit · version")]
    CL <--> GH[("GitHub")]
```

1. **Validate** the URL strictly, then ask GitHub for the latest commit with `git ls-remote`, without downloading anything.
2. **Cache check** on (repo, commit, analysis version). A repeat request skips everything below: about 1.5 s instead of about 5 s. The latest commit is remembered for a minute, so a repeat visit within that minute takes about 0.02 s.
3. **Fetch only what we read:** a shallow *partial* clone plus a sparse checkout downloads just the `.py` files and project files (`pyproject.toml`, `setup.py`, `setup.cfg`) into a temporary folder, deleted afterwards whatever happens. Images, data and docs are never downloaded.
4. **Parse** every `.py` file with Python's `ast`. The code is read as data and never run.
5. **Resolve** each import: longest matching module, relative imports, the script-folder rule, stdlib versus third-party.
6. **Build** a directed graph (A → B means "A imports B") and run the **analytics** on the repo's own runtime imports.
7. **Collapse** it into a package graph (one node per package folder; an edge sums every import between two packages) and run the same analytics on that.
8. **Serialize** both to Cytoscape's `{"data": {...}}` format, so the browser draws them as-is.

## Design decisions

| Decision | Why | Rejected alternative |
|---|---|---|
| Parse with `ast` | Safe: a malicious repo can't run code on the server; handles all syntax | Regex (breaks on strings and multi-line imports); importing the code (unsafe) |
| Cycles as strongly connected components | Linear time, and answers "which modules are tangled together?" | Listing every simple cycle (can take exponential time) |
| Type-only imports as dashed edges, excluded from analytics | They never run. Counting them turned Flask's core into a fake 20-module cycle and gave requests an 8-module one that doesn't exist. | Dropping them (loses information) or counting them (fake cycles) |
| Analytics on the repo's own modules only | `typing` would top every ranking, and toggling libraries must not change sizes or colours | Analysing whatever is visible |
| Our own layered layout (simplified Sugiyama) | Cytoscape's breadth-first layout put 60 test modules on one row. Ours collapses cycle groups (condensation), assigns layers by longest path, orders by community and wraps rows. | `breadthfirst`; adding a dagre dependency |
| Package view as a separate, collapsed graph (a quotient graph) | It gets its own analytics, including cycles *between packages*. It works with every layout, and the server computes it once and caches it. | Cytoscape compound nodes (modules drawn inside package boxes): no package-level analytics, and the layered, ring and circle layouts don't support them |
| Circle area ∝ importance (square-root sizing) | Viewers judge circles by area | Linear diameter (exaggerates the top module) |
| Cache key = repo + commit + analysis version | A commit is an exact snapshot, so its analysis never changes; the version invalidates old results when the analysis logic changes | Time-based expiry (stale or wasteful) |
| Git with credential helpers disabled | Private repos fail fast as 404 instead of hanging on a login prompt, and the server never uses saved credentials | Relying on the timeout |
| Partial clone + sparse checkout (only `.py` and project files) | numpy went from a 60 s timeout to 12 s; FastAPI from 58 MB to 8 MB. The checked-out code is identical to a full clone. | A full shallow clone (downloads everything); fetching files one by one through the GitHub API (rate limits, thousands of requests) |
| Timeouts kill git's whole process tree | `subprocess`'s timeout only kills git itself, and git's download helpers kept the request waiting: a 56 s limit once took 133 s | Trusting `subprocess.run(timeout=...)` |
| Read the source folders a project declares (`pyproject.toml`, `setup.cfg`) | SQLAlchemy keeps its code in `lib/`; without this, 393 of its modules pointed at a fake third-party "sqlalchemy" | Guessing from folder names (`lib/` often holds helper scripts) |
| At most 2 analyses at once, then 503 | A free instance has about 512 MB of RAM; cache hits bypass the limit | Unlimited (crashes under a burst) |
| Remember each repo's latest commit for 60 s | The GitHub round trip was most of a cache hit (1.5 s → 0.02 s). A push shows up at most a minute late. | Asking GitHub on every request |
| One lock per repository (64 locks shared by hash), with the cache checked again inside it | Two people opening the same new repository trigger one clone, not two. The second waits, then hits the cache. Memory stays fixed however many repos are seen. | One global lock (unrelated repos would queue); a lock per repo name (grows forever) |
| Vanilla JS as ES modules, CDN libraries pinned with integrity hashes | No build step; tampered CDN files are refused by the browser | React plus a bundler |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `POST /api/analyze` | Body `{"repo_url": "https://github.com/pallets/flask", "include_external": false}`. Returns the commit, a `cached` flag, the summary, the nodes and edges in Cytoscape's format, and `packages`: the same graph collapsed into packages, with its own summary |
| `GET /api/generate?model=ba&n=200&m=2&seed=1` | Random graph (`er`: n, p · `ba`: n, m · `ws`: n, k, p). Returns the stats, the degree distribution, and the nodes and edges |

Errors always look like `{"detail": "..."}`: 400 bad URL or parameters · 404 not found or private · 413 too many files · 422 no Python files · 502 git failed · 503 busy · 504 timed out. Interactive docs are at `/docs`.

## Running it

```bash
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload    # http://127.0.0.1:8000
pytest -q                        # run the tests
```

Requires Python 3.11+ and `git` on your PATH. `requirements.txt` is the runtime set; `requirements-dev.txt` adds the test tools.

**On Windows**, after the one-time setup above you can double-click `scripts\start-windows.bat`. It starts the server and opens the browser; close its window to stop the server. `scripts\run-tests.bat` runs the test suite.

**Docker:** `docker build -t repoatlas . && docker run -p 8000:8000 repoatlas`. The image is `python:3.13-slim` plus `git`, running as a non-root user.

**Deploy:** `render.yaml` is a Render Blueprint (a free Docker web service with a health check and auto-deploy on push). Use the button above, or Render → New → Blueprint. The live demo above is deployed exactly this way, and redeploys on every merge to `main`.

## Testing and CI

**174 tests** (pytest). They cover:
- URL validation, including injection attempts
- path → module naming on real layouts (src/, folders declared in `pyproject.toml`/`setup.cfg`, nested projects, name clashes)
- every import-resolution rule, plus a fake repository with a known graph and one cycle
- analytics, the package graph (grouping rules, a cycle between packages without any cycle between modules), the cache and the API (offline, with GitHub faked), including two simultaneous requests cloning only once
- the sparse clone against a throwaway local git repository (only `.py` and project files arrive; git confirms the rest was never downloaded), and timeouts that stop git's helper processes

Several Graph Lab tests check **graph theory** rather than shape: ring-lattice clustering = 3(k−2)/(4(k−1)), the small-world drop in path length, Barabási–Albert hubs versus Erdős–Rényi, and exact edge counts.

GitHub Actions runs two jobs on every push and pull request:
- **pytest**
- **docker:** builds the production image, starts it, and analyses a real repository *inside the container*

**Tested on unfamiliar code.** Beyond the four repositories above, RepoAtlas was run on 16 more it had never seen: typer, FastAPI, black, Jinja, Werkzeug, Starlette, pytest, Pydantic, Scrapy, HTTPie, SQLAlchemy, numpy, Django, and three edge cases (no Python, a missing repository, a tiny sample project). That found and fixed four problems:
- SQLAlchemy's declared `lib/` folder was not recognised
- FastAPI's and Typer's `docs_src/` example scripts swamped the graph
- numpy timed out while downloading files it never reads
- git timeouts didn't stop git's helper processes

Every fix left the four reference repositories' results unchanged. Django (over 2,000 Python files) gets a clear 413 message; FastAPI's 703 modules draw in about 4 s.

## Limitations

- Python only; public GitHub repositories only; at most 2,000 Python files (files over 1 MB are kept as nodes but not parsed).
- Static analysis: `importlib.import_module("…")` and other dynamic imports aren't seen; conditions aren't evaluated (an import inside `if sys.platform == "win32"` counts everywhere). `if TYPE_CHECKING:` imports are recognised.
- Tests are included, so the modules tests import most (often the package `__init__`) rank high.
- Imports that only work because code edits `sys.path` at runtime appear as external libraries.
- Package folders declared only in `setup.py` aren't detected (it's code, and RepoAtlas never runs repository code); `pyproject.toml` and `setup.cfg` declarations are.
- Big graphs are slower: the Force layout of a ~700-module repository takes a few seconds in the browser (the Rings and Hierarchy layouts stay instant).

## Future work

- Compare two repositories, or two commits of one, side by side
- Function-level call graphs
- Stream real progress (Server-Sent Events) instead of estimated loading steps

## License

[MIT](LICENSE) © 2026 Vivansh Garg
