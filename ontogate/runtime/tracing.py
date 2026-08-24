from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

try:
    from rich.console import Console

    _console: "Console | None" = Console()
except ImportError:  # pragma: no cover - rich is an optional dependency
    _console = None


@dataclass
class Span:
    name: str
    wave: int
    attributes: dict[str, Any] = field(default_factory=dict)
    start: float = field(default_factory=time.time)
    end: float | None = None
    status: str = "RUNNING"
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return (self.end - self.start) * 1000


class Tracer:
    """Structured, per-step tracing: one span per orchestrator step with
    timing, status, and arbitrary attributes (args, cache hit/miss, retry
    count). Exported as JSON for the static HTML trace viewer, and printed
    live to the console as the run progresses."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, wave: int = 0, **attributes: Any) -> Iterator[Span]:
        s = Span(name=name, wave=wave, attributes=dict(attributes))
        self.spans.append(s)
        self._log(f"[wave {wave}] -> {name} started")
        try:
            yield s
        except Exception as exc:
            s.status = "FAILED"
            s.error = str(exc)
            raise
        finally:
            if s.end is None:
                s.end = time.time()
            if s.status == "RUNNING":
                s.status = "SUCCEEDED"
            self._log(f"[wave {wave}]    {name} {s.status.lower()} ({s.duration_ms:.0f}ms)")

    def record_skip(self, name: str, wave: int) -> None:
        s = Span(name=name, wave=wave, status="SKIPPED")
        s.end = s.start
        self.spans.append(s)
        self._log(f"[wave {wave}]    {name} skipped (blocked by a failed dependency)")

    def _log(self, message: str) -> None:
        if _console is not None:
            _console.print(message)
        else:
            print(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "spans": [
                {
                    "name": s.name,
                    "wave": s.wave,
                    "attributes": s.attributes,
                    "start": s.start,
                    "end": s.end,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "error": s.error,
                }
                for s in self.spans
            ],
        }

    def export_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
