"""URL validation is the security boundary for everything that follows, so it gets
its own tests. These run offline; the network parts are checked manually via
`python -m app.cloner <url>`."""

import pytest

from app.cloner import RepoRef, parse_repo_url
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
