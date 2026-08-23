from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from .ontology.seed_data import build_graph
from .runtime.cache import Cache
from .runtime.memory import Memory
from .runtime.orchestrator import Orchestrator
from .runtime.planner import PlannerError, get_planner
from .runtime.state import StateStore
from .runtime.tools import build_tool_registry
from .trace_viewer import render_trace_html

DATA_DIR = Path(__file__).resolve().parent.parent / "runs"

DEMO_SCENARIOS = [
    "Onboard Erin as a data analyst on the data team",
    "Investigate why Carol can't access the data warehouse",
    "Grant Erin access to the VPN",
]


def _run_task(task: str, planner_name: str, failure_rate: float, run_id: str | None, resume: bool) -> int:
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    out_dir = DATA_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    graph = build_graph()
    cache = Cache(out_dir / "cache.db")
    state = StateStore(out_dir / "state.db")
    memory = Memory(DATA_DIR / "memory.db")
    tools = build_tool_registry(graph, failure_rate=failure_rate)

    planner = get_planner(planner_name, graph, tools, memory)
    try:
        plan = planner.plan(task)
    except PlannerError as exc:
        print(f"planning failed: {exc}", file=sys.stderr)
        return 1

    orchestrator = Orchestrator(tools, state=state, cache=cache, memory=memory)
    result = asyncio.run(orchestrator.run(plan, run_id, resume=resume))

    print(f"\nrun {run_id}: {result.status}")
    for sid, out in result.outputs.items():
        print(f"  [ok]   {sid}: {out}")
    for sid, err in result.errors.items():
        print(f"  [FAIL] {sid}: {err}")

    trace_path = out_dir / "trace.json"
    result.tracer.export_json(trace_path)
    html_path = out_dir / "trace.html"
    render_trace_html(plan, result, html_path)
    print(f"\ntrace: {trace_path}")
    print(f"view:  {html_path}")

    for db in (cache, state, memory):
        db.close()

    return 0 if result.status == "SUCCEEDED" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calyb", description="An enterprise workflow agent runtime.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a single task through the agent runtime.")
    run_p.add_argument("task", help="Natural-language enterprise task, e.g. 'Onboard Erin as an engineer'")
    run_p.add_argument("--planner", default="auto", choices=["auto", "rule", "llm"])
    run_p.add_argument("--failure-rate", type=float, default=0.0, help="Simulated transient tool failure rate (0-1)")
    run_p.add_argument("--run-id", default=None)
    run_p.add_argument("--resume", action="store_true", help="Resume a previous run (requires --run-id)")

    demo_p = sub.add_parser("demo", help="Run three canned scenarios end-to-end, including a guardrail denial.")
    demo_p.add_argument("--planner", default="auto", choices=["auto", "rule", "llm"])
    demo_p.add_argument("--failure-rate", type=float, default=0.3)

    args = parser.parse_args(argv)

    if args.command == "run":
        if args.resume and not args.run_id:
            print("--resume requires --run-id", file=sys.stderr)
            return 1
        return _run_task(args.task, args.planner, args.failure_rate, args.run_id, args.resume)

    if args.command == "demo":
        code = 0
        for task in DEMO_SCENARIOS:
            print(f"\n{'=' * 70}\nSCENARIO: {task}\n{'=' * 70}")
            code |= _run_task(task, args.planner, args.failure_rate, None, False)
        return code

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
