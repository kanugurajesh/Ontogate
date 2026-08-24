from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Matches "$steps.<id>.output" or "$steps.<id>.output.<dotted.path>"
_PLACEHOLDER_RE = re.compile(r"\$steps\.([a-zA-Z0-9_\-]+)\.output(?:\.([a-zA-Z0-9_.\-]+))?")


class DAGValidationError(Exception):
    pass


@dataclass
class Step:
    id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False  # if True, this step's own failure doesn't fail the whole run


@dataclass
class Plan:
    """A validated DAG of tool-invocation steps produced by a planner."""

    task: str
    steps: dict[str, Step]

    @classmethod
    def from_steps(cls, task: str, steps: list[Step]) -> "Plan":
        by_id: dict[str, Step] = {}
        for s in steps:
            if s.id in by_id:
                raise DAGValidationError(f"duplicate step id {s.id!r}")
            by_id[s.id] = s
        plan = cls(task=task, steps=by_id)
        plan.validate()
        return plan

    def validate(self) -> None:
        for step in self.steps.values():
            for dep in step.depends_on:
                if dep not in self.steps:
                    raise DAGValidationError(f"step {step.id!r} depends on unknown step {dep!r}")
            for value in _iter_strings(step.args):
                for m in _PLACEHOLDER_RE.finditer(value):
                    ref = m.group(1)
                    if ref not in self.steps:
                        raise DAGValidationError(f"step {step.id!r} references unknown step {ref!r}")
                    if ref != step.id and ref not in step.depends_on:
                        raise DAGValidationError(
                            f"step {step.id!r} references output of {ref!r} but does not "
                            "declare it in depends_on"
                        )
        self._compute_waves()  # raises DAGValidationError on cycles

    def _compute_waves(self) -> list[list[str]]:
        remaining = {sid: set(s.depends_on) for sid, s in self.steps.items()}
        done: set[str] = set()
        waves: list[list[str]] = []
        while remaining:
            ready = sorted(sid for sid, deps in remaining.items() if deps <= done)
            if not ready:
                cyclic = ", ".join(sorted(remaining))
                raise DAGValidationError(f"cycle detected among steps: {cyclic}")
            waves.append(ready)
            for sid in ready:
                del remaining[sid]
            done.update(ready)
        return waves

    def waves(self) -> list[list[str]]:
        """Steps grouped into dependency-respecting execution waves; steps
        within a wave have no dependency on each other and can run in
        parallel."""
        return self._compute_waves()

    def resolve_args(self, step: Step, outputs: dict[str, Any]) -> dict[str, Any]:
        """Substitute $steps.<id>.output[.path] placeholders with real
        values from already-completed steps' outputs."""

        def lookup(ref: str, path: str | None) -> Any:
            out = outputs[ref]
            if path:
                for part in path.split("."):
                    out = out[part]
            return out

        def resolve_value(value: Any) -> Any:
            if isinstance(value, str):
                stripped = value.strip()
                m = _PLACEHOLDER_RE.fullmatch(stripped)
                if m:
                    return lookup(m.group(1), m.group(2))

                def sub(match: re.Match) -> str:
                    return str(lookup(match.group(1), match.group(2)))

                return _PLACEHOLDER_RE.sub(sub, value)
            if isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve_value(v) for v in value]
            return value

        return {k: resolve_value(v) for k, v in step.args.items()}


def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)
