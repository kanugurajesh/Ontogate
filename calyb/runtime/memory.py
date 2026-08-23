from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class Memory:
    """Short-term per-run scratchpad plus a durable, long-term episodic
    store of past runs, retrievable by keyword (Jaccard token overlap)
    rather than embeddings. That's a deliberate trade-off: no embedding
    model/API dependency and every retrieval is fully inspectable, at the
    cost of missing paraphrases an embedding index would catch."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.scratchpad: dict[str, Any] = {}
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                run_id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                outcome TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def remember(self, run_id: str, task: str, outcome: str, summary: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO episodes (run_id, task, outcome, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, task, outcome, summary, time.time()),
        )
        self._conn.commit()

    def recall_similar(self, task: str, limit: int = 3) -> list[dict[str, Any]]:
        query_tokens = _tokenize(task)
        rows = self._conn.execute("SELECT run_id, task, outcome, summary FROM episodes").fetchall()
        scored = []
        for run_id, past_task, outcome, summary in rows:
            past_tokens = _tokenize(past_task)
            union = query_tokens | past_tokens
            if not union:
                continue
            score = len(query_tokens & past_tokens) / len(union)
            if score > 0:
                scored.append(
                    (score, {"run_id": run_id, "task": past_task, "outcome": outcome, "summary": summary})
                )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def close(self) -> None:
        self._conn.close()


def _tokenize(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if len(w) > 2}
