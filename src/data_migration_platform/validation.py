"""Sample-based value validation on migrated (target) rows.

Full-table validation is expensive on large migrations, so checks run on
a deterministic sample (first N rows in primary-key order, or the whole
table when smaller). A failed check does not fail the run by itself — it
is recorded on the manifest so operators decide, because a validation
failure is a signal, not proof the load was wrong. Quarantine, by
contrast, is per-row and happens at map time.
"""

from __future__ import annotations

import re
from typing import Any

from data_migration_platform.models import ValidationCheck, ValidationResult


def run_check(rows: list[dict[str, Any]], check: ValidationCheck) -> ValidationResult:
    sample = rows[: max(check.sample_size, 0)] if check.sample_size else rows
    violations: list[Any] = []
    for row in sample:
        value = row.get(check.column)
        bad = False
        if check.kind == "not_null":
            bad = value is None or (isinstance(value, str) and value.strip() == "")
        elif check.kind == "range":
            try:
                number = float(value)  # type: ignore[arg-type]
                bad = (check.min_value is not None and number < check.min_value) or (
                    check.max_value is not None and number > check.max_value
                )
            except (TypeError, ValueError):
                bad = True
        elif check.kind == "regex":
            bad = not (isinstance(value, str) and check.pattern and re.search(check.pattern, value))
        elif check.kind == "allowed_values":
            bad = value not in (check.allowed or [])
        elif check.kind == "unique":
            seen = {r.get(check.column) for r in sample}
            # unique is evaluated once, below; per-row loop cannot judge it.
            bad = False
            _ = seen
        else:
            raise ValueError(f"unknown validation kind {check.kind!r}")
        if bad:
            violations.append(value)
    if check.kind == "unique":
        values = [r.get(check.column) for r in sample]
        duplicates = sorted({v for v in values if values.count(v) > 1}, key=str)
        violations = duplicates
    return ValidationResult(
        check=check,
        rows_checked=len(sample),
        violations=len(violations),
        sample_violations=violations[:5],
    )


def run_validations(rows: list[dict[str, Any]], checks: list[ValidationCheck]) -> list[ValidationResult]:
    return [run_check(rows, check) for check in checks]
