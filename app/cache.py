"""SQLite cache of finished analyses, keyed by (repo, commit SHA, analysis version).

A commit SHA names an exact snapshot of the code, so the analysis of a given
SHA never changes. The only thing that can make a cached result stale is *our*
code changing, which is what ANALYSIS_VERSION is for.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    repo        TEXT    NOT NULL,
    commit_sha  TEXT    NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,   -- JSON: summary + all nodes/edges (externals included)
    PRIMARY KEY (repo, commit_sha, version)
)
"""


class Cache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn, conn:
            conn.execute(_SCHEMA)

    def _connect(self):
        # A fresh connection per call: FastAPI runs requests on several threads,
        # and a sqlite3 connection must not be shared between threads.
        # closing() closes it afterwards; `with conn:` wraps a transaction.
        return closing(sqlite3.connect(self.path, timeout=10))

    def get(self, repo: str, commit_sha: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                # `?` placeholders: sqlite3 fills in the values safely, so a
                # repo name can never be run as SQL (no SQL injection).
                "SELECT payload FROM analyses WHERE repo = ? AND commit_sha = ? AND version = ?",
                (repo, commit_sha, config.ANALYSIS_VERSION),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, repo: str, commit_sha: str, payload: dict) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses VALUES (?, ?, ?, ?, ?)",
                (repo, commit_sha, config.ANALYSIS_VERSION,
                 datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
            )
