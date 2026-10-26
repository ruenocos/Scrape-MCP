"""Small SQLite cache so repeat requests for the same URL are instant and polite."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .fetch import FetchResult

DEFAULT_TTL = 60 * 60  # one hour


def default_cache_path() -> Path:
    root = os.environ.get("SCRAPE_MCP_CACHE_DIR")
    base = Path(root) if root else Path.home() / ".cache" / "scrape-mcp"
    return base / "cache.sqlite3"


class Cache:
    def __init__(self, path: Path | None = None, ttl: int = DEFAULT_TTL):
        self.path = path or default_cache_path()
        self.ttl = ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS pages (
                url TEXT PRIMARY KEY,
                final_url TEXT NOT NULL,
                status INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                body BLOB NOT NULL,
                fetcher TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )"""
        )
        self._db.commit()

    def get(self, url: str) -> tuple[FetchResult, float] | None:
        row = self._db.execute(
            "SELECT final_url, status, content_type, body, fetcher, fetched_at FROM pages WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        final_url, status, content_type, body, fetcher, fetched_at = row
        if time.time() - fetched_at > self.ttl:
            return None
        return FetchResult(url, final_url, status, content_type, body, fetcher), fetched_at

    def put(self, result: FetchResult) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                result.url,
                result.final_url,
                result.status,
                result.content_type,
                result.body,
                result.fetcher,
                time.time(),
            ),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
