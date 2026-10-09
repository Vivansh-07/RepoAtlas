"""URL validation is the security boundary for everything that follows, so it gets
its own tests. Everything here runs offline: the clone test uses a throwaway local
git repository instead of GitHub (the CI docker job clones a real one)."""

import shutil
import subprocess
import sys
import time

import pytest

from app.cloner import CHECKOUT_PATTERNS, RepoRef, _run_command, parse_repo_url, sparse_clone
from app.errors import InvalidRepoURL


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/pallets/flask", ("pallets", "flask")),
    ("https://github.com/pallets/flask/", ("pallets", "flask")),
    ("https://github.com/pallets/flask.git", ("pallets", "flask")),
    ("https://github.com/encode/httpx.git/", ("encode", "httpx")),
    ("  https://github.com/Pallets/Flask \n", ("pallets", "flask")),   # trimmed + lowercased
    ("https://github.com/socketio/socket.io", ("socketio", "socket.io")),
    ("https://github.com/octo-org/.github", ("octo-org", ".github")),
    ("https://github.com/my_org/repo-name_2", ("my_org", "repo-name_2")),
])
def test_valid_urls(url, expected):
    assert parse_repo_url(url) == RepoRef(*expected)


@pytest.mark.parametrize("url", [
    "",
    "github.com/pallets/flask",                       # no scheme
    "http://github.com/pallets/flask",                # not https
    "https://gitlab.com/pallets/flask",               # other host
    "https://github.com.evil.com/pallets/flask",      # lookalike host
    "https://evil.com/github.com/pallets/flask",
    "https://user:pass@github.com/pallets/flask",     # embedded credentials
    "https://github.com/pallets",                     # no repo
    "https://github.com/pallets/flask/tree/main",     # deeper path
    "https://github.com/pallets/flask?tab=readme",    # query string
    "https://github.com/pallets/flask; rm -rf /",     # shell injection attempt
    "https://github.com/pallets/flask\n--upload-pack=touch /tmp/x",  # option injection
    "https://github.com/../flask",                    # path traversal
    "https://github.com/pallets/..",
    "https://github.com/пример/flask",                # non-ASCII
])
def test_invalid_urls(url):
    with pytest.raises(InvalidRepoURL):
        parse_repo_url(url)


def test_clone_url_is_rebuilt_from_parts():
    # We never pass the user's raw string to git, only this rebuilt URL.
    assert parse_repo_url("https://github.com/Pallets/Flask/").clone_url == \
        "https://github.com/pallets/flask.git"


# --- fetching only the files we read ----------------------------------------

def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_sparse_clone_fetches_only_python_and_project_files(tmp_path):
    source = tmp_path / "source"
    files = {
        "pkg/__init__.py": "", "pkg/core.py": "import os\n",
        "examples/demo/pyproject.toml": "", "setup.cfg": "",
        "README.md": "# hi\n", "docs/logo.png": "not really a png", "data/big.csv": "1,2,3\n" * 1000,
    }
    for rel, text in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text(text)
    git("init", "-q", cwd=source)
    git("add", ".", cwd=source)
    git("commit", "-q", "-m", "files", cwd=source)
    git("config", "uploadpack.allowFilter", "true", cwd=source)   # GitHub allows partial clones; a local repo must opt in

    dest = tmp_path / "dest"
    sparse_clone(source.as_uri(), dest)

    checked_out = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert checked_out == {"pkg/__init__.py", "pkg/core.py", "examples/demo/pyproject.toml", "setup.cfg"}
    # Not just hidden: the other files' contents were never downloaded. Git lists
    # them as "missing" objects (lines starting with "?") in the partial clone.
    out = subprocess.run(["git", "rev-list", "--objects", "--missing=print", "HEAD"], cwd=dest,
                         capture_output=True, text=True, check=True).stdout
    assert sum(line.startswith("?") for line in out.splitlines()) == 3      # README, logo, CSV


def test_checkout_patterns_cover_every_file_the_parser_reads():
    from app.parser import PROJECT_MARKERS
    assert "*.py" in CHECKOUT_PATTERNS
    assert {f"**/{name}" for name in PROJECT_MARKERS} <= set(CHECKOUT_PATTERNS)


def test_timeout_also_stops_the_processes_the_command_started():
    # Like git during a download: the command starts a helper that inherits its
    # output pipe, then both hang. Killing only the command would leave us
    # waiting ~30 s for the helper; the whole tree must go at the 1 s timeout.
    helper = "import time; time.sleep(30)"
    script = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {helper!r}]); time.sleep(30)"
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_command([sys.executable, "-c", script], timeout=1)
    assert time.monotonic() - start < 10


def test_run_command_returns_output_and_exit_code():
    code, out, err = _run_command([sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"], timeout=30)
    assert (code, out.strip()) == (3, "hi")
