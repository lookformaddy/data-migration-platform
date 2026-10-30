# data-migration-platform

A governed data-migration platform: declarative source → target schema
mappings, ordered migration plans, dry-run vs apply, row-count and
checksum reconciliation, sample-based value validation, resumable
checkpointed runs with idempotent applies, rollback snapshots, and
quarantine of failed rows with reasons. Every run produces a manifest
that an operator — or an auditor — can read without re-running anything.

## The enterprise problem

Migrations fail in boring, expensive ways: a date format nobody checked,
a column renamed in the target, a run killed halfway and re-run twice,
a "successful" load that silently dropped 3% of rows. The usual response
is a one-off script per migration, reviewed by nobody, re-runnable by
nobody, and unauditable afterwards.

This platform treats a migration as a **reviewable plan** (data, not
code) executed by a **strict engine** (coercion failures quarantine rows
instead of corrupting them) and closed out by **reconciliation**
(expected target rows vs actual target rows, by count and checksum).
If reconciliation fails, you know before anyone declares victory.

## Architecture overview

```
MigrationPlan (JSON / dataclasses)          TableStore (in-memory tables)
  steps, ordered by depends_on ──►  MigrationEngine
  field mappings + coercions        ├─ dry-run: map + quarantine, no writes
  validations (sample-based)        ├─ apply: idempotent upsert by PK
  row filters                        ├─ checkpoint after each step
                                     ├─ reconcile expected vs actual
                                     └─ manifest + quarantine + metrics
Rollback: pre-run snapshot restored on demand.
```

Modules (`src/data_migration_platform/`):

| Module | Responsibility |
| --- | --- |
| `models.py` | Plan/step/mapping/manifest dataclasses, JSON round-trip, topological ordering, canonical checksums |
| `mapping.py` | Strict type coercion (int, float, bool, date, decimal, trim/case) and transforms (cents → units, strip currency) |
| `validation.py` | Sample-based checks: not_null, range, regex, allowed_values, unique |
| `reconciliation.py` | Row-count + SHA-256 checksum comparison, mismatched-column reporting |
| `engine.py` | Dry-run/apply, checkpoints, idempotent upsert, rollback, manifest |
| `store.py` | In-memory table store, JSON snapshot save/load |
| `api.py` | Optional FastAPI surface (plan validation, run execution) |
| `cli.py` | `demo` and `run --plan … --mode …` commands |

## How to run it

```bash
pip install -r requirements.txt   # core needs stdlib only; FastAPI is optional
python3 -m pytest -q              # from the project directory
python3 examples/run_demo.py      # end-to-end synthetic migration
# or via the CLI (PYTHONPATH=src):
PYTHONPATH=src python -m data_migration_platform.cli demo
PYTHONPATH=src python -m data_migration_platform.cli run \
  --plan examples/migration_plan.json --store examples/store.json --mode dry_run
```

The demo migrates synthetic customers and orders, quarantines one row
with an unparseable date, then deliberately tampers with a migrated
value to show reconciliation catching the mismatch.

To activate CI, move `docs/github-actions-ci.yml` to
`.github/workflows/ci.yml` (the file explains why it ships under
`docs/` — see Architecture).

## Key design decisions and trade-offs

- **Strict coercion, quarantine on failure.** A bad value never lands
  as NULL or a guessed type. Cost: operators must triage quarantined
  rows. Benefit: the target is never silently wrong.
- **Reconciliation over mapped rows, not raw rows.** Source and target
  schemas differ by design; comparing raw rows would always mismatch.
  The engine reconciles what *should* have landed against what did.
- **Sample-based validation, full reconciliation.** Validation samples
  (default 100 rows) keep large migrations cheap; reconciliation is
  always full-table, because a sampled count check is not a guarantee.
- **Checkpoint per step, not per row.** A crash mid-step re-runs that
  step in full; primary-key upserts make that safe. Per-row checkpoints
  would be slower and would complicate the manifest for little gain.
- **Validation failure ≠ run failure.** A failed check is recorded on
  the manifest for operator judgement; quarantine is per-row and
  happens at map time. Conflating the two would either block good
  loads or hide bad ones.
- **In-memory store behind a narrow interface.** Real warehouse /
  database adapters plug in behind `TableStore`'s interface; the
  engine never sees a connection, which is what makes it fully testable
  without infrastructure.
- **Rollback restores a snapshot, not an inverse migration.** Inverse
  migrations are lossy when the target has since changed. A snapshot
  is exact — but it is only as good as the disk it is saved to, so the
  CLI persists manifests and stores as JSON.

## What it demonstrates

Declarative migration planning, dependency-ordered execution, strict
type coercion with quarantine, idempotent and resumable applies,
checksum reconciliation, sample-based validation, rollback design,
run manifests as audit artifacts, and a clean core/web separation
(stdlib core, optional FastAPI surface with auto-skipping tests).

## Clean-room note

All code is original; all data is synthetic. No employer code, data,
internal architecture, or project names are used. Domains are generic.
