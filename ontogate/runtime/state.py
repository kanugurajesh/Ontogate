from __future__ import annotations

import json
import sqlite3
import time
from enum import Enum
from pathlib import Path
from typing import Any


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StateStore:
    """Durable, SQLite-backed run/step state. Every step transition is
    persisted before the orchestrator moves on, so if the process dies
    mid-run, `Orchestrator.run(..., resume=True)` can pick up exactly where
    it left off instead of re-running (and re-side-effecting) completed
    steps."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                status TEXT NOT NULL,
                output TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (run_id, step_id)
            );
            """
        )
        self._conn.commit()

    def run_exists(self, run_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return row is not None

    def create_run(self, run_id: str, task: str) -> None:
        now = time.time()
        self._conn.execute(
            "INSERT INTO runs (run_id, task, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, task, "RUNNING", now, now),
        )
        self._conn.commit()

    def set_run_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, time.time(), run_id),
        )
        self._conn.commit()

    def set_step_status(
        self,
        run_id: str,
        step_id: str,
        status: StepStatus,
        output: Any = None,
        error: str | None = None,
        attempts: int | None = None,
    ) -> None:
        existing = self.get_step(run_id, step_id)
        prev_attempts = existing["attempts"] if existing else 0
        self._conn.execute(
            """
            INSERT INTO steps (run_id, step_id, status, output, error, attempts, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, step_id) DO UPDATE SET
                status = excluded.status,
                output = excluded.output,
                error = excluded.error,
                attempts = excluded.attempts,
                updated_at = excluded.updated_at
            """,
            (
                run_id,
                step_id,
                status.value,
                json.dumps(output) if output is not None else None,
                error,
                attempts if attempts is not None else prev_attempts,
                time.time(),
            ),
        )
        self._conn.commit()

    def get_step(self, run_id: str, step_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT status, output, error, attempts FROM steps WHERE run_id = ? AND step_id = ?",
            (run_id, step_id),
        ).fetchone()
        if row is None:
            return None
        status, output, error, attempts = row
        return {
            "status": status,
            "output": json.loads(output) if output is not None else None,
            "error": error,
            "attempts": attempts,
        }

    def get_run_steps(self, run_id: str) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT step_id, status, output, error, attempts FROM steps WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for step_id, status, output, error, attempts in rows:
            result[step_id] = {
                "status": status,
                "output": json.loads(output) if output is not None else None,
                "error": error,
                "attempts": attempts,
            }
        return result

    def close(self) -> None:
        self._conn.close()
