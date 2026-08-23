from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class _Miss:
    def __repr__(self) -> str:
        return "<CACHE_MISS>"


CACHE_MISS = _Miss()


class Cache:
    """Content-addressed cache for idempotent tool/LLM calls, backed by
    SQLite so it survives process restarts. Keys are a hash of (tool name,
    args) so identical calls anywhere in a run - or across resumed runs -
    are free."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl_seconds REAL
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def make_key(tool: str, args: dict[str, Any]) -> str:
        payload = json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> Any:
        row = self._conn.execute(
            "SELECT value, created_at, ttl_seconds FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return CACHE_MISS
        value, created_at, ttl = row
        if ttl is not None and time.time() - created_at > ttl:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return CACHE_MISS
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value), time.time(), ttl_seconds),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
