"""Migration engine: dry-run vs apply, checkpoints, rollback, quarantine.

Semantics, stated plainly because operators bet production data on them:
- DRY_RUN never mutates the target store. It maps, quarantines and
  reconciles against what *would* land.
- APPLY is idempotent: rows are upserted by primary key, so re-running
  a completed step (or the whole run) changes nothing.
- A checkpoint records completed step ids after each step. A resumed
  run skips completed steps and reports resumed_from_checkpoint=True.
  If a run crashes mid-step, that step is not checkpointed and re-runs
  in full — upsert idempotency makes that safe.
- ROLLBACK restores the pre-run snapshot of every touched target table.
  Snapshots are taken once, before the first apply step, and returned
  to the caller (or saved to disk by the CLI) — the engine never deletes
  data it cannot restore.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data_migration_platform.mapping import MappingError, map_row
from data_migration_platform.models import (
    MigrationPlan,
    QuarantinedRow,
    ReconciliationResult,
    RunManifest,
    RunMode,
    RunStatus,
    StepResult,
    ValidationResult,
)
from data_migration_platform.reconciliation import reconcile
from data_migration_platform.store import TableStore, load_json, save_json
from data_migration_platform.validation import run_validations


@dataclass
class EngineResult:
    manifest: RunManifest
    # Deep copy of every target table before apply (empty dict for dry-run).
    rollback_snapshot: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    checkpoint_path: Path | None = None


class MigrationEngine:
    def __init__(self, store: TableStore) -> None:
        self.store = store

    def run(
        self,
        plan: MigrationPlan,
        mode: RunMode = RunMode.DRY_RUN,
        checkpoint_path: Path | None = None,
        run_id: str | None = None,
    ) -> EngineResult:
        ordered = plan.ordered_steps()  # raises on cycles / unknown deps
        completed: set[str] = set()
        resumed = False
        if checkpoint_path is not None and checkpoint_path.exists():
            completed = set(load_json(checkpoint_path).get("completed_steps", []))
            resumed = bool(completed)
        snapshot = self.store.snapshot() if mode == RunMode.APPLY else {}
        manifest = RunManifest(
            run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
            plan_id=plan.plan_id,
            mode=mode,
            status=RunStatus.DRY_RUN_OK if mode == RunMode.DRY_RUN else RunStatus.SUCCEEDED,
            resumed_from_checkpoint=resumed,
        )
        for step in ordered:
            started = time.monotonic()
            source_rows = self.store.rows(step.source_table)
            if step.filter_equals:
                col, wanted = next(iter(step.filter_equals.items()))
                source_rows = [r for r in source_rows if r.get(col) == wanted]
            expected: list[dict[str, Any]] = []
            quarantine: list[QuarantinedRow] = []
            for row in source_rows:
                try:
                    mapped = map_row(row, step.mappings)
                except MappingError as exc:
                    key = str(row.get("id", row))
                    quarantine.append(QuarantinedRow(step.step_id, key, str(exc), row))
                    continue
                expected.append(mapped)
            skipped = 0
            if mode == RunMode.APPLY:
                if step.step_id in completed:
                    # Already applied in an earlier attempt: verify, don't rewrite.
                    skipped = len(expected)
                else:
                    for mapped in expected:
                        self.store.upsert(step.target_table, step.primary_key, mapped)
                    completed.add(step.step_id)
                    if checkpoint_path is not None:
                        save_json(checkpoint_path, {"completed_steps": sorted(completed)})
            actual = expected if mode == RunMode.DRY_RUN else self.store.rows(step.target_table)
            # For apply, compare expected rows against the rows this step
            # produced (filtered to this step's keys), not the whole table,
            # which may legitimately hold rows from earlier migrations.
            if mode == RunMode.APPLY:
                keys = {r.get(step.primary_key) for r in expected}
                actual = [r for r in actual if r.get(step.primary_key) in keys]
            recon = reconcile(step.step_id, expected, actual, step.primary_key)
            manifest.reconciliation.append(recon)
            validations = run_validations(actual, step.validations)
            manifest.validations.extend(validations)
            manifest.quarantine.extend(quarantine)
            manifest.steps.append(
                StepResult(
                    step_id=step.step_id,
                    source_rows=len(source_rows),
                    applied_rows=0 if mode == RunMode.DRY_RUN else len(expected),
                    quarantined_rows=len(quarantine),
                    skipped_as_already_applied=skipped,
                    duration_seconds=round(time.monotonic() - started, 4),
                )
            )
            if not recon.matches:
                manifest.notes.append(
                    f"reconciliation mismatch on {step.step_id}: "
                    f"source {recon.source.row_count} vs target {recon.target.row_count}, "
                    f"checksum_match={recon.checksum_match}"
                )
        if manifest.quarantine and manifest.status == RunStatus.SUCCEEDED:
            manifest.status = RunStatus.SUCCEEDED_WITH_QUARANTINE
        return EngineResult(
            manifest=manifest, rollback_snapshot=snapshot, checkpoint_path=checkpoint_path
        )

    def rollback(self, snapshot: dict[str, list[dict[str, Any]]]) -> None:
        """Restore target tables to the pre-run snapshot."""
        self.store.restore(snapshot)


def rollback_to_snapshot(store: TableStore, snapshot: dict[str, list[dict[str, Any]]]) -> None:
    store.restore(snapshot)
