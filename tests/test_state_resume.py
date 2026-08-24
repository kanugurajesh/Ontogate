import pytest

from ontogate.runtime.cache import Cache
from ontogate.runtime.dag import Plan, Step
from ontogate.runtime.orchestrator import Orchestrator
from ontogate.runtime.state import StateStore
from ontogate.runtime.tools import ToolRegistry


def build_tools(call_counts, crash_flag):
    registry = ToolRegistry()

    @registry.register("step1_tool", idempotent=True, description="")
    async def step1_tool():
        call_counts["step1"] += 1
        return {"ok": True}

    @registry.register("step2_tool", idempotent=True, description="")
    async def step2_tool():
        call_counts["step2"] += 1
        if crash_flag[0] and call_counts["step2"] == 1:
            raise RuntimeError("simulated process crash")
        return {"ok": True}

    @registry.register("step3_tool", idempotent=True, description="")
    async def step3_tool():
        call_counts["step3"] += 1
        return {"ok": True}

    return registry


async def test_resume_after_crash_does_not_re_execute_completed_steps(tmp_path):
    call_counts = {"step1": 0, "step2": 0, "step3": 0}
    crash_flag = [True]
    tools = build_tools(call_counts, crash_flag)

    plan = Plan.from_steps(
        "t",
        [
            Step("s1", "step1_tool"),
            Step("s2", "step2_tool", depends_on=["s1"]),
            Step("s3", "step3_tool", depends_on=["s2"]),
        ],
    )

    state_path = tmp_path / "state.db"
    cache_path = tmp_path / "cache.db"

    state = StateStore(state_path)
    cache = Cache(cache_path)
    orch = Orchestrator(tools, state=state, cache=cache)

    with pytest.raises(RuntimeError, match="simulated process crash"):
        await orch.run(plan, "run-1", resume=False)

    assert call_counts == {"step1": 1, "step2": 1, "step3": 0}
    state.close()
    cache.close()

    # "process restarts": fresh connections to the same durable state, and
    # the transient bug is now gone (crash_flag off), mirroring a redeploy.
    crash_flag[0] = False
    state2 = StateStore(state_path)
    cache2 = Cache(cache_path)
    orch2 = Orchestrator(tools, state=state2, cache=cache2)

    result = await orch2.run(plan, "run-1", resume=True)

    assert result.status == "SUCCEEDED"
    assert call_counts["step1"] == 1  # completed step was not re-run
    assert call_counts["step2"] == 2  # the crashed attempt + one real retry-from-scratch
    assert call_counts["step3"] == 1
