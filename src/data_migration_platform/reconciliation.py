"""Row-count + checksum reconciliation between source and target.

Checksums are computed over the *mapped* source rows, not raw source
rows — source and target schemas differ by design, so comparing raw
rows would always mismatch. The engine therefore reconciles
expected-target rows (mapping applied, quarantine excluded) against
actual target rows, and reports which columns diverge when sums differ.
"""

from __future__ import annotations

from typing import Any

from data_migration_platform.models import (
    ChecksumResult,
    ReconciliationResult,
    canonical_checksum,
)


def reconcile(
    step_id: str,
    expected_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    key: str,
) -> ReconciliationResult:
    source = canonical_checksum(expected_rows, key)
    target = canonical_checksum(actual_rows, key)
    mismatched = [
        col
        for col in sorted(set(source.numeric_sums) | set(target.numeric_sums))
        if abs(source.numeric_sums.get(col, 0.0) - target.numeric_sums.get(col, 0.0)) > 1e-9
    ]
    return ReconciliationResult(
        step_id=step_id,
        source=source,
        target=target,
        row_count_match=source.row_count == target.row_count,
        checksum_match=source.checksum == target.checksum,
        mismatched_columns=mismatched,
    )


def summarize(result: ReconciliationResult) -> str:
    if result.matches:
        return f"{result.step_id}: OK ({result.source.row_count} rows, checksum match)"
    return (
        f"{result.step_id}: MISMATCH source={result.source.row_count} rows "
        f"target={result.target.row_count} rows checksum_match={result.checksum_match} "
        f"mismatched_columns={result.mismatched_columns}"
    )
