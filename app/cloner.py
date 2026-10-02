"""Validate GitHub URLs, look up a repo's latest commit, and shallow-clone it.

Every git call goes through `_run_git`, which:
  - passes arguments as a list (never shell=True), so nothing in a URL can run
    as a shell command;
  - disables login prompts and credential helpers, so a private or missing repo
    fails fast instead of hanging on a password prompt, and any GitHub login
    saved on the machine is never used (public repos only, by construction).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.errors import GitError, GitTimeout, InvalidRepoURL, NoPythonFiles, RepoNotFound

# GitHub owner/repo names only use ASCII letters, digits, '-', '_' and '.'.
# re.ASCII stops \w from also matching non-English letters.
_GITHUB_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[\w.-]{1,100})/(?P<name>[\w.-]{1,100}?)(?:\.git)?/?",
    re.ASCII,
)
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")

# What git prints when GitHub answers 401/404 (private and missing repos look the same).
_NOT_FOUND_HINTS = ("could not read username", "repository not found")


@dataclass(frozen=True)
class RepoRef:
    """A validated GitHub repository."""
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.slug}.git"


def parse_repo_url(url: str) -> RepoRef:
    # fullmatch, not match + '$': '$' also matches just before a trailing newline.
    match = _GITHUB_URL_RE.fullmatch(url.strip())
    if not match:
        raise InvalidRepoURL("Expected a URL like https://github.com/<owner>/<repo>")
    owner, name = match["owner"], match["name"]
    if set(owner) == {"."} or set(name) == {"."}:
        raise InvalidRepoURL("Owner and repo name can't be just dots")
    # GitHub names are case-insensitive; lowercasing gives one cache entry per repo
    # no matter how the user typed it.
    return RepoRef(owner.lower(), name.lower())


def _run_git(args: list[str], timeout: float, cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # "credential.helper=" (empty) clears every configured helper, e.g. Git
    # Credential Manager on Windows. core.longpaths avoids "Filename too long" on Windows.
    cmd = ["git", "-c", "credential.helper=", "-c", "core.longpaths=true", *args]
    try:
        result = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git is not installed on the server") from None
    except subprocess.TimeoutExpired:
        raise GitTimeout(f"git took longer than {timeout:g}s") from None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if any(hint in stderr.lower() for hint in _NOT_FOUND_HINTS):
            raise RepoNotFound("Repository not found, or it is private")
        raise GitError(f"git failed: {stderr[-300:]}")
    return result.stdout


def get_head_sha(repo: RepoRef) -> str:
    """SHA of the default branch's latest commit, fetched without cloning."""
    out = _run_git(["ls-remote", "--", repo.clone_url, "HEAD"], config.LS_REMOTE_TIMEOUT_S)
    if not out.strip():
        raise NoPythonFiles("Repository is empty")
    sha = out.split()[0]
    if not _SHA_RE.fullmatch(sha):
        raise GitError(f"Unexpected ls-remote output: {out[:100]!r}")
    return sha


def read_local_sha(repo_dir: Path) -> str:
    """SHA actually checked out. Can differ from get_head_sha() if someone pushed
    between the two calls, so this is the one to cache results under."""
    return _run_git(["rev-parse", "HEAD"], config.LS_REMOTE_TIMEOUT_S, cwd=repo_dir).strip()


@contextmanager
def clone_repo(repo: RepoRef) -> Iterator[Path]:
    """Shallow-clone `repo` into a temp dir that is deleted when the `with` block
    exits, even if an exception is raised inside it."""
    with tempfile.TemporaryDirectory(prefix="repoatlas-") as tmp:
        _run_git(
            ["clone", "--depth", "1", "--quiet", "--", repo.clone_url, tmp],
            config.CLONE_TIMEOUT_S,
        )
        yield Path(tmp)


@contextmanager
def open_repo(target: str) -> Iterator[Path]:
    """For the `python -m app.<module>` checks only: clone a GitHub URL, or use a
    local folder as-is. The API never accepts local paths."""
    if target.startswith("https://"):
        with clone_repo(parse_repo_url(target)) as path:
            yield path
    else:
        yield Path(target)


if __name__ == "__main__":
    # Manual check:  python -m app.cloner https://github.com/pallets/click
    import sys

    repo = parse_repo_url(sys.argv[1])
    print("repo:        ", repo.slug)
    print("remote HEAD: ", get_head_sha(repo))
    with clone_repo(repo) as path:
        print("cloned to:   ", path)
        print("cloned HEAD: ", read_local_sha(path))
        print(".py files:   ", sum(1 for _ in path.rglob("*.py")))
    print("temp dir deleted:", not path.exists())
