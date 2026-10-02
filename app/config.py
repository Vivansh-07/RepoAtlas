"""Limits and timeouts in one place, so they're easy to find and tune."""

# git network calls
LS_REMOTE_TIMEOUT_S = 15
CLONE_TIMEOUT_S = 60

# Parsing limits
MAX_PY_FILES = 2000              # more than this -> 413
MAX_FILE_BYTES = 1_000_000       # larger .py files are skipped (usually generated code)

# Graph Lab
MAX_GENERATED_NODES = 500

# Directories never worth parsing: VCS data, virtualenvs, build output, docs.
SKIP_DIRS = frozenset({
    ".git", "venv", ".venv", "env", "node_modules", "build", "dist",
    "site-packages", "__pycache__", ".tox", "docs",
})
