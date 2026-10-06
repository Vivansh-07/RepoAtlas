"""Limits, timeouts and paths in one place, so they're easy to find and tune."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DB_PATH = BASE_DIR / "data" / "cache.db"
STATIC_DIR = BASE_DIR / "static"

# Part of the cache key. Bump it whenever the analysis output changes, so results
# cached by older code are ignored instead of served.
ANALYSIS_VERSION = 4              # 2: + package graph; 3: packages grouped by folder; 4: short package labels

# git network calls
LS_REMOTE_TIMEOUT_S = 15
CLONE_TIMEOUT_S = 60
# How long the answer of `git ls-remote` (a repo's latest commit) is reused. A
# push is noticed at most this late; in exchange, repeat visits skip a ~1 s call.
HEAD_SHA_TTL_S = 60

# At most this many analyses clone + parse at the same time (a free hosting plan
# has ~512 MB of RAM). Others wait up to ANALYSIS_WAIT_S, then get a 503.
MAX_CONCURRENT_ANALYSES = 2
ANALYSIS_WAIT_S = 20

# Parsing limits
MAX_PY_FILES = 2000              # more than this -> 413
MAX_FILE_BYTES = 1_000_000       # larger .py files are skipped (usually generated code)

# Graph Lab
MAX_GENERATED_NODES = 500
MAX_GENERATED_EDGES = 5000       # beyond this the browser drawing gets sluggish

# Directories never worth parsing: VCS data, virtualenvs, build output, docs.
SKIP_DIRS = frozenset({
    ".git", "venv", ".venv", "env", "node_modules", "build", "dist",
    "site-packages", "__pycache__", ".tox", "docs",
})
