from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .cache import CACHE_MISS, Cache
from .circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from .dag import Plan
from .memory import Memory
from .state import StateStore, StepStatus
from .tools import PermanentToolError, ToolError, ToolRegistry
from .tracing import Tracer


@dataclass
class RunResult:
    run_id: str
    task: str
    status: str
    outputs: dict[str, Any]
    errors: dict[str, str]
    tracer: Tracer


class Orchestrator:
    """Executes a validated Plan: schedules independent steps concurrently
    within each dependency wave, retries transient tool failures with
    exponential backoff (short-circuited by a per-tool circuit breaker),
    memoizes idempotent calls through the cache, checkpoints every step
    transition to the StateStore for crash-resume, and records a structured
    trace of the whole run."""

    def __init__(
        self,
        tools: ToolRegistry,
        *,
        state: StateStore,
        cache: Cache,
        memory: Memory | None = None,
        max_retries: int = 2,
        backoff_base: float = 0.05,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_reset: float = 2.0,
    ) -> None:
        self.tools = tools
        self.state = state
        self.cache = cache
        self.memory = memory
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.breakers = CircuitBreakerRegistry(
            failure_threshold=circuit_breaker_threshold, reset_timeout=circuit_breaker_reset
        )

    async def run(self, plan: Plan, run_id: str, resume: bool = False) -> RunResult:
        tracer = Tracer(run_id)

        if resume and self.state.run_exists(run_id):
            prior = self.state.get_run_steps(run_id)
        else:
            self.state.create_run(run_id, plan.task)
            prior = {}

        outputs: dict[str, Any] = {}
        errors: dict[str, str] = {}
        failed: set[str] = set()
        skipped: set[str] = set()
        for sid, s in prior.items():
            if s["status"] == StepStatus.SUCCEEDED.value:
                outputs[sid] = s["output"]
            elif s["status"] == StepStatus.FAILED.value:
                failed.add(sid)
                errors[sid] = s["error"] or ""
            elif s["status"] == StepStatus.SKIPPED.value:
                skipped.add(sid)
            # RUNNING (interrupted mid-flight) and PENDING both fall through
            # and are simply re-executed below.

        for wave_index, wave in enumerate(plan.waves()):
            pending: list[str] = []
            for sid in wave:
                if sid in outputs or sid in failed or sid in skipped:
                    continue
                step = plan.steps[sid]
                if any(dep in failed or dep in skipped for dep in step.depends_on):
                    skipped.add(sid)
                    self.state.set_step_status(run_id, sid, StepStatus.SKIPPED)
                    tracer.record_skip(sid, wave_index)
                    continue
                pending.append(sid)

            results = await asyncio.gather(
                *(self._run_step(plan, sid, run_id, outputs, tracer, wave_index) for sid in pending)
            )
            for sid, (status, value) in zip(pending, results):
                if status == StepStatus.SUCCEEDED:
                    outputs[sid] = value
                else:
                    failed.add(sid)
                    errors[sid] = str(value)

        overall = "FAILED" if failed else "SUCCEEDED"
        self.state.set_run_status(run_id, overall)

        if self.memory is not None:
            summary = f"{len(outputs)} step(s) succeeded, {len(failed)} failed, {len(skipped)} skipped"
            self.memory.remember(run_id, plan.task, overall, summary)

        return RunResult(run_id=run_id, task=plan.task, status=overall, outputs=outputs, errors=errors, tracer=tracer)

    async def _run_step(
        self,
        plan: Plan,
        sid: str,
        run_id: str,
        outputs: dict[str, Any],
        tracer: Tracer,
        wave_index: int,
    ) -> tuple[StepStatus, Any]:
        step = plan.steps[sid]
        tool_spec = self.tools.get(step.tool)
        args = plan.resolve_args(step, outputs)
        breaker = self.breakers.get(step.tool)
        cache_key = self.cache.make_key(step.tool, args) if tool_spec.idempotent else None

        with tracer.span(sid, wave=wave_index, tool=step.tool, args=args) as span:
            if cache_key is not None:
                cached = self.cache.get(cache_key)
                if cached is not CACHE_MISS:
                    span.attributes["cache"] = "hit"
                    self.state.set_step_status(run_id, sid, StepStatus.SUCCEEDED, output=cached)
                    return StepStatus.SUCCEEDED, cached
                span.attributes["cache"] = "miss"

            self.state.set_step_status(run_id, sid, StepStatus.RUNNING)
            attempt = 0
            last_exc: Exception | None = None
            while attempt <= self.max_retries:
                attempt += 1
                try:
                    breaker.before_call()
                    result = await tool_spec.fn(**args)
                    breaker.on_success()
                    if cache_key is not None:
                        self.cache.set(cache_key, result)
                    span.attributes["attempts"] = attempt
                    self.state.set_step_status(run_id, sid, StepStatus.SUCCEEDED, output=result, attempts=attempt)
                    return StepStatus.SUCCEEDED, result
                except PermanentToolError as exc:
                    breaker.on_failure()
                    last_exc = exc
                    break  # guardrail/permanent errors are never worth retrying
                except (ToolError, CircuitOpenError) as exc:
                    breaker.on_failure()
                    last_exc = exc
                    if attempt <= self.max_retries:
                        await asyncio.sleep(self.backoff_base * (2 ** (attempt - 1)))
                except Exception as exc:
                    # Not a ToolError - e.g. a TypeError from a planner passing
                    # args that don't match the tool's signature. Retrying
                    # would just fail identically every time, so treat it as
                    # permanent and fail this step without crashing the run.
                    breaker.on_failure()
                    last_exc = exc
                    break

            span.attributes["attempts"] = attempt
            span.status = "FAILED"
            span.error = str(last_exc)
            self.state.set_step_status(run_id, sid, StepStatus.FAILED, error=str(last_exc), attempts=attempt)
            return StepStatus.FAILED, str(last_exc)
