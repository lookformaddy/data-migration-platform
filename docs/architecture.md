# Architecture

## Flow

```
plan.json ──► MigrationPlan.from_json ──► ordered_steps() (topological)
                                                    │
source tables ──► map_row (strict coercion) ──► expected target rows
                                                    ├─► quarantine (MappingError rows, with reason)
                                                    ├─► DRY_RUN: reconcile expected vs expected (no writes)
                                                    └─► APPLY: upsert by PK, checkpoint step, reconcile
                                                              expected vs actual (filtered to step keys)
                                                    │
                                                    ▼
                                              RunManifest (JSON):
                                              per-step counts/durations,
                                              quarantine, reconciliation,
                                              validations, notes
```

## Failure modes and handling

| Failure | Handling |
| --- | --- |
| Uncoercible value | Row quarantined with field + reason; run continues |
| Missing required field | Same — quarantined, never defaulted silently |
| Dependency cycle / unknown step | Plan rejected before any step runs |
| Crash mid-run | Completed steps checkpointed; resume skips them; crashed step re-runs safely via upsert |
| Tampered / partial target | Reconciliation mismatch recorded on the manifest with mismatched columns |
| Bad migration overall | `rollback()` restores the pre-run snapshot of every touched table |

## Why the CI file lives under docs/

The GitHub App integration used to publish this project cannot write
under `.github/workflows/` (it lacks the Workflows permission), so the
CI definition ships as `docs/github-actions-ci.yml`. Activating it is a
one-step move to `.github/workflows/ci.yml` — no content change needed.
The workflow itself runs pytest on Python 3.12 and the demo script.

## Extension points

- **Real stores:** implement the `TableStore` interface (rows / upsert /
  snapshot) over a warehouse or database; the engine is unchanged.
- **New coercions/transforms:** add a `Coercion` value and a branch in
  `coerce()`; add a transform name in `apply_transform()`.
- **New validation kinds:** add a branch in `run_check()`; the manifest
  format already carries arbitrary checks.
- **Parallel steps:** steps with no dependency path between them are
  independent; a future engine could run them concurrently, but must
  keep checkpoint ordering deterministic.
