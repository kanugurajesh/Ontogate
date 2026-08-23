import pytest

from calyb.runtime.dag import DAGValidationError, Plan, Step


def test_waves_respect_dependencies_and_parallelize_independent_steps():
    plan = Plan.from_steps(
        "t",
        [
            Step("a", "tool_a"),
            Step("b", "tool_b"),
            Step("c", "tool_c", depends_on=["a", "b"]),
        ],
    )
    waves = plan.waves()
    assert waves[0] == ["a", "b"]
    assert waves[1] == ["c"]


def test_cycle_is_rejected():
    with pytest.raises(DAGValidationError, match="cycle"):
        Plan.from_steps(
            "t",
            [
                Step("a", "tool_a", depends_on=["b"]),
                Step("b", "tool_b", depends_on=["a"]),
            ],
        )


def test_unknown_dependency_is_rejected():
    with pytest.raises(DAGValidationError, match="unknown step"):
        Plan.from_steps("t", [Step("a", "tool_a", depends_on=["ghost"])])


def test_undeclared_output_reference_is_rejected():
    with pytest.raises(DAGValidationError, match="does not declare"):
        Plan.from_steps(
            "t",
            [
                Step("a", "tool_a"),
                Step("b", "tool_b", args={"x": "$steps.a.output.id"}),  # missing depends_on=["a"]
            ],
        )


def test_duplicate_step_id_is_rejected():
    with pytest.raises(DAGValidationError, match="duplicate"):
        Plan.from_steps("t", [Step("a", "tool_a"), Step("a", "tool_b")])


def test_resolve_args_substitutes_whole_value_preserving_type():
    plan = Plan.from_steps(
        "t",
        [Step("a", "tool_a"), Step("b", "tool_b", args={"x": "$steps.a.output.data"}, depends_on=["a"])],
    )
    outputs = {"a": {"data": {"nested": 1}}}
    resolved = plan.resolve_args(plan.steps["b"], outputs)
    assert resolved["x"] == {"nested": 1}


def test_resolve_args_substitutes_inline_within_string():
    plan = Plan.from_steps(
        "t",
        [Step("a", "tool_a"), Step("b", "tool_b", args={"msg": "hello $steps.a.output.name!"}, depends_on=["a"])],
    )
    outputs = {"a": {"name": "erin"}}
    resolved = plan.resolve_args(plan.steps["b"], outputs)
    assert resolved["msg"] == "hello erin!"
