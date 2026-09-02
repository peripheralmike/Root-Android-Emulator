"""Local SQLite state: when we first saw a game, and a TTL cache for details.

The cache matters more than it looks. Without it, every scheduled run
re-fetches the store page of every game it has already seen -- hundreds of
needless requests a week against Steam and itch.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    key         TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    title       TEXT,
    score       REAL
);
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    fetched_at  REAL NOT NULL,
    payload     TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class State:
    """Wraps the SQLite file. Safe to construct on every run."""

    def __init__(self, path: Path, cache_ttl_hours: int = 168) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = cache_ttl_hours * 3600
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.executescript(SCHEMA)

    # -- first-seen tracking -------------------------------------------------

    def first_seen(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT first_seen FROM seen WHERE key = ?", (key,)
        ).fetchone()
        return row["first_seen"] if row else None

    def record(self, key: str, title: str, score: float) -> str:
        """Upsert a sighting and return the game's first_seen timestamp."""
        now = utcnow()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO seen (key, first_seen, last_seen, title, score)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    title     = excluded.title,
                    score     = excluded.score
                """,
                (key, now, now, title, score),
            )
        return self.first_seen(key) or now

    def is_new(self, key: str) -> bool:
        return self.first_seen(key) is None

    # -- detail cache --------------------------------------------------------

    def get(self, key: str):
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        if time.time() - row["fetched_at"] > self.ttl:
            return None
        try:
            return json.loads(row["payload"])
        except ValueError:
            log.debug("dropping undecodable cache entry %s", key)
            return None

    def put(self, key: str, value) -> None:
        try:
            payload = json.dumps(value)
        except (TypeError, ValueError):
            # Not serialisable: skip caching rather than blowing up the run.
            log.debug("value for %s is not JSON-serialisable, not caching", key)
            return
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO cache (key, fetched_at, payload) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload    = excluded.payload
                """,
                (key, time.time(), payload),
            )

    def purge_expired(self) -> int:
        cutoff = time.time() - self.ttl
        with self.conn:
            cur = self.conn.execute("DELETE FROM cache WHERE fetched_at < ?", (cutoff,))
        return cur.rowcount or 0

    def close(self) -> None:
        with closing(self.conn):
            pass
