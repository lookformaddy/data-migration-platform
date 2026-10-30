"""CLI: `python -m data_migration_platform.cli demo` runs the end-to-end
synthetic migration; `run --plan <json> --mode dry_run|apply` executes a
plan file against a JSON table store (see examples/migration_plan.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data_migration_platform.engine import MigrationEngine
from data_migration_platform.models import MigrationPlan, RunMode
from data_migration_platform.store import TableStore, load_json, save_json


def build_demo_store() -> TableStore:
    return TableStore(
        {
            "src_customers": [
                {"id": 1, "full_name": " Ada Lovelace ", "email": "ADA@example.com", "signup": "2024-01-15", "cents": 4999},
                {"id": 2, "full_name": "Grace Hopper", "email": "grace@example.com", "signup": "2024/02/20", "cents": 1250},
                {"id": 3, "full_name": "Alan Turing", "email": "alan@example.com", "signup": "not-a-date", "cents": 0},
            ],
            "src_orders": [
                {"id": 10, "customer_id": 1, "amount": "$42.50", "status": "PAID"},
                {"id": 11, "customer_id": 2, "amount": "7.00", "status": "pending"},
            ],
        }
    )


def demo_plan() -> MigrationPlan:
    from data_migration_platform.models import Coercion, FieldMapping, MigrationStep, ValidationCheck

    return MigrationPlan(
        plan_id="demo-customers-orders",
        steps=[
            MigrationStep(
                step_id="customers",
                source_table="src_customers",
                target_table="customers",
                primary_key="customer_id",
                mappings=[
                    FieldMapping("id", "customer_id", Coercion.INTEGER, required=True),
                    FieldMapping("full_name", "name", Coercion.TRIM, required=True),
                    FieldMapping("email", "email", Coercion.LOWER, required=True),
                    FieldMapping("signup", "signup_date", Coercion.DATE),
                    FieldMapping("cents", "lifetime_value", Coercion.DECIMAL, transform="cents_to_units"),
                ],
                validations=[ValidationCheck("email", "regex", pattern=r"^[^@]+@[^@]+\.[^@]+$")],
            ),
            MigrationStep(
                step_id="orders",
                source_table="src_orders",
                target_table="orders",
                primary_key="order_id",
                depends_on=["customers"],
                mappings=[
                    FieldMapping("id", "order_id", Coercion.INTEGER, required=True),
                    FieldMapping("customer_id", "customer_id", Coercion.INTEGER, required=True),
                    FieldMapping("amount", "amount", Coercion.DECIMAL, transform="strip_currency"),
                    FieldMapping("status", "status", Coercion.LOWER),
                ],
                validations=[ValidationCheck("amount", "range", min_value=0.0)],
            ),
        ],
    )


def run_demo() -> int:
    store = build_demo_store()
    plan = demo_plan()
    engine = MigrationEngine(store)
    dry = engine.run(plan, mode=RunMode.DRY_RUN)
    would_be = sum(s.source_rows - s.quarantined_rows for s in dry.manifest.steps)
    print(f"DRY-RUN: status={dry.manifest.status.value} would-apply={would_be} "
          f"quarantined={dry.manifest.total_quarantined}")
    print(f"  target tables untouched after dry-run: {sorted(t for t in store.tables if not t.startswith('src_')) or 'none'}")
    applied = engine.run(plan, mode=RunMode.APPLY)
    print(f"APPLY: status={applied.manifest.status.value} applied={applied.manifest.total_applied} "
          f"quarantined={applied.manifest.total_quarantined}")
    for q in applied.manifest.quarantine:
        print(f"  QUARANTINED step={q.step_id} key={q.row_key} reason={q.reason}")
    for row in store.rows("customers"):
        print(f"  customer: {row}")
    # Deliberate mismatch: tamper one target value, then reconcile.
    customers = store.rows("customers")
    customers[0]["lifetime_value"] = "9999.99"
    store.set_table("customers", customers)
    from data_migration_platform.mapping import map_row
    from data_migration_platform.reconciliation import reconcile, summarize

    expected = [map_row(r, plan.steps[0].mappings) for r in build_demo_store().rows("src_customers")
                if r["id"] != 3]
    recon = reconcile("customers", expected, store.rows("customers"), "customer_id")
    print(f"RECONCILIATION AFTER TAMPER: {summarize(recon)}")
    assert not recon.matches, "tampered target must fail reconciliation"
    print("DEMO OK: dry-run clean, apply quarantined the bad date, reconciliation caught the tamper.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data-migration-platform")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    run_p = sub.add_parser("run")
    run_p.add_argument("--plan", required=True)
    run_p.add_argument("--store", required=True, help="JSON file of {table: [rows]}")
    run_p.add_argument("--mode", choices=["dry_run", "apply"], default="dry_run")
    run_p.add_argument("--checkpoint", default=None)
    run_p.add_argument("--out", default=None, help="manifest JSON output path")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return run_demo()
    plan = MigrationPlan.from_json(Path(args.plan).read_text())
    store = TableStore(load_json(Path(args.store)))
    result = MigrationEngine(store).run(
        plan,
        mode=RunMode(args.mode),
        checkpoint_path=Path(args.checkpoint) if args.checkpoint else None,
    )
    print(result.manifest.to_json())
    if args.out:
        save_json(Path(args.out), result.manifest.to_dict())
    if args.mode == "apply":
        save_json(Path(args.store), store.tables)
    return 0


if __name__ == "__main__":
    sys.exit(main())
