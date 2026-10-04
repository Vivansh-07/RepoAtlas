"""Errors the analysis pipeline can raise.

Each error carries the HTTP status the API should answer with, so main.py needs
a single exception handler instead of a try/except in every route.
"""


class RepoAtlasError(Exception):
    status_code = 500


class InvalidRepoURL(RepoAtlasError):
    status_code = 400


class InvalidParams(RepoAtlasError):
    """Graph Lab parameters that are well-formed but don't make sense (e.g. m >= n)."""
    status_code = 400


class RepoNotFound(RepoAtlasError):
    status_code = 404


class RepoTooLarge(RepoAtlasError):
    status_code = 413


class NoPythonFiles(RepoAtlasError):
    status_code = 422


class GitError(RepoAtlasError):
    """git failed for a reason other than 'not found' or 'timed out'."""
    status_code = 502


class GitTimeout(RepoAtlasError):
    status_code = 504
