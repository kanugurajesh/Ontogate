# Ontogate Agent Runtime

A from-scratch **enterprise agent runtime**: an ontology-grounded planner that
decomposes a natural-language task into a DAG, an async orchestrator that
executes it with retries, a circuit breaker, checkpointed fault tolerance,
content-addressed caching, keyword-retrieval memory, and structured tracing.

I built this after reading Ontogate's internship posting. Ontogate's own framing —
"capturing the knowledge that runs a business and making it machine
executable so AI workers can assist or automate any workflow" — is exactly
what this project tries to demonstrate in miniature: an **ontology engine**
that encodes enterprise knowledge (who has what role, which systems a policy
governs, who's on which team) as typed, validated relationships, and an
**agent runtime** that plans and executes real actions against it — actions
the ontology can *refuse*, not just log.

No agent framework (no LangChain/LangGraph) — every piece is built from
first principles on the standard library, on purpose, so the design
decisions are all mine to explain.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt   # optional: only needed for --planner llm or colored output

python -m ontogate.cli demo
```

This runs three scenarios end-to-end and writes a trace + a self-contained
HTML viewer per run to `runs/<run-id>/trace.html` — open it directly in a
browser, no server needed. A pre-generated example is in
[`examples/guardrail-denial-trace.html`](examples/guardrail-denial-trace.html).

Run a single task:

```bash
python -m ontogate.cli run "Onboard Erin as a data analyst on the data team"
python -m ontogate.cli run "Grant Erin access to the VPN"          # denied by the ontology
python -m ontogate.cli run "..." --planner llm                     # needs OPENAI_API_KEY
python -m ontogate.cli run "..." --run-id demo-1 --resume          # resume a crashed/interrupted run
```

Run the tests:

```bash
pip install -r requirements.txt
pytest
```

## Architecture

```
 task (natural language)
        |
        v
 +--------------+      ontology snapshot      +-------------------+
 |   Planner    | <-------------------------- |  KnowledgeGraph   |
 | (rule | LLM) |      + memory recall        |  (ontology engine) |
 +--------------+                             +-------------------+
        |
        v  validated DAG (Plan)
 +----------------------------------------------------------+
 |                      Orchestrator                        |
 |  wave-by-wave async execution -> retry + backoff          |
 |  -> per-tool circuit breaker -> cache -> checkpoint       |
 +----------------------------------------------------------+
        |            |              |              |
        v            v              v              v
   ToolRegistry   StateStore      Cache          Tracer
   (mock          (SQLite,       (SQLite,      (spans -> JSON
   enterprise     resumable)     content-       + static HTML
   systems, all                  addressed)     DAG/timeline
   graph-backed)                                viewer)
```

| JD term | Where it lives |
|---|---|
| Ontology engine | `ontogate/ontology/` — typed entities/relations, pluggable validation rules, policy-based access guardrails |
| Planning | `ontogate/runtime/planner.py` — `RuleBasedPlanner` (deterministic fallback) and `LLMPlanner` (OpenAI, JSON-schema constrained, self-correcting) |
| Orchestration | `ontogate/runtime/orchestrator.py` — dependency-wave scheduling, concurrent execution within a wave |
| Execution algorithms | `ontogate/runtime/dag.py` — topological wave computation, cycle detection, placeholder resolution between steps |
| Memory | `ontogate/runtime/memory.py` — per-run scratchpad + durable episodic recall |
| State management | `ontogate/runtime/state.py` — per-step status persisted to SQLite, drives resume |
| Caching | `ontogate/runtime/cache.py` — content-addressed, TTL-aware, memoizes idempotent tool calls |
| Observability | `ontogate/runtime/tracing.py` + `ontogate/trace_viewer.py` — spans, live console output, static HTML trace/DAG viewer |
| Fault tolerance | `ontogate/runtime/circuit_breaker.py` + retry/backoff in the orchestrator + checkpointed resume |

## The ontology as a guardrail, not documentation

The interesting design decision is in `ontogate/ontology/rules.py`. Most
"ontology" demos are just a schema — a description of the world an LLM can
still ignore. Here, `rule_access_requires_policy_role` runs on every write to
the graph: granting a user access to a system checks every `POLICY` that
`GOVERNS` that system, and requires the user to already hold one of the
roles that policy `REQUIRES_ROLE`. The agent runtime doesn't check this in
the planner or in a prompt — the graph itself refuses the write:

```
$ python -m ontogate.cli run "Grant Erin access to the VPN"
...
[FAIL] grant: access denied by ontology: policy 'policy:eng_policy' governing
       'system:vpn' requires one of roles [role:engineer, role:admin], but
       'user:erin' has none of them
```

The orchestrator also knows this specific failure is never worth retrying
(`PermanentToolError`, vs. the retryable `ToolError` used for simulated
transient upstream failures) and correctly cascades a `SKIPPED` status to
the dependent `notify` step instead of quietly running it. Compare that to
`python -m ontogate.cli run "Onboard Erin as a data analyst on the data team"`,
where the same `grant_access` tool call succeeds because onboarding assigns
the role *first* (a DAG dependency), which the policy then accepts.

## Fault tolerance and state, concretely

`tests/test_state_resume.py` simulates a real crash: step 1 completes and
persists `SUCCEEDED`, step 2 raises an unhandled exception mid-call (nothing
catches it — this isn't a retryable `ToolError`, it's meant to look like the
process dying), which propagates out of `Orchestrator.run()` entirely. A
second `Orchestrator` — fresh instances, same SQLite files, `resume=True` —
picks the run back up: step 1 is **not** re-invoked (its side effect already
happened and is durable), step 2 re-runs from scratch, and the run completes.
That's the actual mechanism, not a mock of it.

## Trade-offs I made on purpose (and would revisit)

- **No dynamic re-planning.** The DAG is fixed once the planner returns it;
  a step's failure can only skip its dependents, not trigger a new plan. A
  production system would want a ReAct-style replan-on-failure loop — I kept
  it a static DAG because it's much easier to reason about, checkpoint, and
  visualize, and it's still enough to show a real dependency graph and real
  parallelism.
- **Keyword-overlap memory, not embeddings.** `Memory.recall_similar` uses
  Jaccard token overlap instead of a vector index. It's fully inspectable
  and needs no embedding model/API, at the cost of missing paraphrases. For
  a larger episodic store this is the first thing I'd swap out.
- **In-process circuit breakers.** One `CircuitBreaker` per tool name, held
  in memory by the `Orchestrator` — real protection within a run, but it
  doesn't persist across process restarts (unlike `StateStore`/`Cache`,
  which are durable by design). A multi-worker deployment would need this
  shared, e.g. in Redis.
- **RuleBasedPlanner is intentionally narrow.** It only recognizes a handful
  of phrasings, on purpose — it exists to make the runtime's tests and demo
  deterministic without an API key. `LLMPlanner` is the generalization path.

## Project layout

```
ontogate/
  ontology/       entities, relations, validation rules, seed enterprise graph
  runtime/        dag, planner, orchestrator, cache, state, memory, tracing, circuit breaker, tools
  trace_viewer.py static HTML DAG/timeline renderer
  cli.py          `ontogate run` / `ontogate demo`
tests/            29 tests covering ontology rules, DAG validation, cache,
                  circuit breaker, checkpoint/resume, and end-to-end runs
examples/         a pre-generated trace, in case you don't want to run it
```
