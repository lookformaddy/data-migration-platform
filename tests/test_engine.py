import json

import pytest

from data_migration_platform.cli import build_demo_store, demo_plan
from data_migration_platform.engine import MigrationEngine
from data_migration_platform.models import RunMode, RunStatus
from data_migration_platform.store import TableStore


def test_dry_run_never_mutates():
    store = build_demo_store()
    before = store.snapshot()
    result = MigrationEngine(store).run(demo_plan(), mode=RunMode.DRY_RUN)
    assert store.snapshot() == before
    assert result.manifest.status == RunStatus.DRY_RUN_OK
    assert all(r.matches for r in result.manifest.reconciliation)


def test_apply_quarantines_bad_row_and_is_idempotent():
    store = build_demo_store()
    engine = MigrationEngine(store)
    first = engine.run(demo_plan(), mode=RunMode.APPLY)
    assert first.manifest.status == RunStatus.SUCCEEDED_WITH_QUARANTINE
    assert first.manifest.total_quarantined == 1  # Alan Turing's bad date
    assert len(store.rows("customers")) == 2
    assert len(store.rows("orders")) == 2
    snapshot = store.snapshot()
    second = engine.run(demo_plan(), mode=RunMode.APPLY)
    assert store.snapshot() == snapshot  # re-run changes nothing
    assert second.manifest.total_applied == 4


def test_checkpoint_resume_skips_completed_step(tmp_path):
    store = build_demo_store()
    # A real resume reuses the target data the earlier attempt already wrote.
    from data_migration_platform.mapping import map_row

    plan = demo_plan()
    store.set_table(
        "customers",
        [map_row(r, plan.steps[0].mappings) for r in store.rows("src_customers") if r["id"] != 3],
    )
    checkpoint = tmp_path / "ckpt.json"
    # Simulate a crashed run: customers checkpointed, orders not yet run.
    checkpoint.write_text(json.dumps({"completed_steps": ["customers"]}))
    result = MigrationEngine(store).run(
        demo_plan(), mode=RunMode.APPLY, checkpoint_path=checkpoint
    )
    assert result.manifest.resumed_from_checkpoint is True
    by_id = {s.step_id: s for s in result.manifest.steps}
    assert by_id["customers"].skipped_as_already_applied == 2
    assert by_id["orders"].applied_rows == 2
    assert len(store.rows("orders")) == 2


def test_rollback_restores_snapshot():
    store = build_demo_store()
    engine = MigrationEngine(store)
    result = engine.run(demo_plan(), mode=RunMode.APPLY)
    assert store.rows("customers")
    engine.rollback(result.rollback_snapshot)
    assert store.rows("customers") == []
    assert "customers" not in store.tables or store.rows("customers") == []


def test_reconciliation_catches_tamper():
    store = build_demo_store()
    engine = MigrationEngine(store)
    engine.run(demo_plan(), mode=RunMode.APPLY)
    customers = store.rows("customers")
    customers[0]["lifetime_value"] = "9999.99"
    store.set_table("customers", customers)
    from data_migration_platform.mapping import map_row
    from data_migration_platform.reconciliation import reconcile

    expected = [
        map_row(r, demo_plan().steps[0].mappings)
        for r in build_demo_store().rows("src_customers")
        if r["id"] != 3
    ]
    recon = reconcile("customers", expected, store.rows("customers"), "customer_id")
    assert not recon.matches
    assert "lifetime_value" in recon.mismatched_columns


def test_filter_equals_limits_rows():
    store = TableStore({"s": [{"id": 1, "k": "a"}, {"id": 2, "k": "b"}]})
    from data_migration_platform.models import Coercion, FieldMapping, MigrationPlan, MigrationStep

    plan = MigrationPlan(
        "p",
        [MigrationStep("s1", "s", "t", "id", [FieldMapping("id", "id", Coercion.INTEGER)],
                       filter_equals={"k": "a"})],
    )
    result = MigrationEngine(store).run(plan, mode=RunMode.APPLY)
    assert len(store.rows("t")) == 1
    assert result.manifest.steps[0].source_rows == 1
