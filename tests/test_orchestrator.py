from ontogate.ontology.schema import RelationType
from ontogate.ontology.seed_data import build_graph
from ontogate.runtime.cache import Cache
from ontogate.runtime.dag import Plan, Step
from ontogate.runtime.orchestrator import Orchestrator
from ontogate.runtime.planner import RuleBasedPlanner
from ontogate.runtime.state import StateStore
from ontogate.runtime.tools import PermanentToolError, ToolError, ToolRegistry, build_tool_registry


def make_orchestrator(tools, **kwargs):
    return Orchestrator(tools, state=StateStore(), cache=Cache(), **kwargs)


async def test_transient_failure_is_retried_then_succeeds():
    attempts = {"n": 0}
    tools = ToolRegistry()

    @tools.register("flaky", idempotent=True, description="")
    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ToolError("transient")
        return {"ok": True}

    plan = Plan.from_steps("t", [Step("s1", "flaky")])
    orch = make_orchestrator(tools, max_retries=2, backoff_base=0.001)
    result = await orch.run(plan, "run-flaky")

    assert result.status == "SUCCEEDED"
    assert attempts["n"] == 3


async def test_permanent_failure_skips_dependents_and_fails_run():
    tools = ToolRegistry()

    @tools.register("always_fails", idempotent=True, description="")
    async def always_fails():
        raise PermanentToolError("nope")

    @tools.register("noop", idempotent=True, description="")
    async def noop():
        return {"ok": True}

    plan = Plan.from_steps("t", [Step("a", "always_fails"), Step("b", "noop", depends_on=["a"])])
    orch = make_orchestrator(tools)
    result = await orch.run(plan, "run-permanent")

    assert result.status == "FAILED"
    assert "a" in result.errors
    assert "b" not in result.outputs
    assert any(s.name == "b" and s.status == "SKIPPED" for s in result.tracer.spans)


async def test_idempotent_calls_are_cached_across_steps():
    calls = {"n": 0}
    tools = ToolRegistry()

    @tools.register("lookup", idempotent=True, description="")
    async def lookup(user_id: str):
        calls["n"] += 1
        return {"id": user_id}

    plan = Plan.from_steps(
        "t",
        [
            Step("s1", "lookup", args={"user_id": "user:bob"}),
            Step("s2", "lookup", args={"user_id": "user:bob"}),
        ],
    )
    orch = make_orchestrator(tools)
    result = await orch.run(plan, "run-cache")

    assert result.status == "SUCCEEDED"
    assert calls["n"] == 1  # the second step was served from cache


async def test_ontology_guardrail_denies_unauthorized_grant_end_to_end():
    graph = build_graph()
    tools = build_tool_registry(graph, failure_rate=0.0)
    plan = RuleBasedPlanner(graph, tools).plan("Grant Erin access to the VPN")

    orch = make_orchestrator(tools)
    result = await orch.run(plan, "run-guardrail")

    assert result.status == "FAILED"
    assert "access denied by ontology" in result.errors["grant"]
    assert "notify" not in result.outputs


async def test_onboarding_scenario_succeeds_end_to_end():
    graph = build_graph()
    tools = build_tool_registry(graph, failure_rate=0.0)
    plan = RuleBasedPlanner(graph, tools).plan("Onboard Erin as a data analyst on the data team")

    orch = make_orchestrator(tools)
    result = await orch.run(plan, "run-onboard")

    assert result.status == "SUCCEEDED"
    granted = {s.id for s in graph.neighbors("user:erin", RelationType.GRANTS_ACCESS_TO)}
    assert "system:data_warehouse" in granted
    roles = {r.id for r in graph.neighbors("user:erin", RelationType.HAS_ROLE)}
    assert roles == {"role:data_analyst"}
