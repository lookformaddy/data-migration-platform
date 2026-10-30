import pytest

from data_migration_platform.models import FieldMapping, MigrationPlan, MigrationStep


def step(step_id, depends_on=None):
    return MigrationStep(step_id, "s", "t", "id", [FieldMapping("id", "id")], depends_on or [])


def test_ordering_respects_dependencies_regardless_of_position():
    plan = MigrationPlan("p", [step("child", ["parent"]), step("parent")])
    assert [s.step_id for s in plan.ordered_steps()] == ["parent", "child"]


def test_cycle_and_unknown_dependency_raise():
    with pytest.raises(ValueError, match="cycle"):
        MigrationPlan("p", [step("a", ["b"]), step("b", ["a"])]).ordered_steps()
    with pytest.raises(ValueError, match="unknown"):
        MigrationPlan("p", [step("a", ["ghost"])]).ordered_steps()


def test_plan_json_round_trip():
    plan = MigrationPlan("p", [step("a")])
    restored = MigrationPlan.from_json(plan.to_json())
    assert restored.plan_id == "p"
    assert restored.steps[0].step_id == "a"
