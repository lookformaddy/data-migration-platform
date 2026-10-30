"""Plan, mapping and result models. Pure stdlib, typed dataclasses.

A migration plan is declarative data (serialisable to/from JSON), never
code: reviewers approve the plan, the engine only executes it. Keeping the
plan as data is what makes dry-run, audit and rollback trustworthy — the
same plan object drives planning, execution and the run manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunMode(str, Enum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


class RunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_QUARANTINE = "succeeded_with_quarantine"
    FAILED = "failed"
    DRY_RUN_OK = "dry_run_ok"


class Coercion(str, Enum):
    """Type-coercion rules applied to a source value before it lands."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"  # ISO YYYY-MM-DD output
    DECIMAL = "decimal"  # string with exactly two fractional digits
    TRIM = "trim"
    UPPER = "upper"
    LOWER = "lower"


@dataclass
class FieldMapping:
    """One source column -> one target column, with coercion and policy."""

    source: str
    target: str
    coercion: Coercion = Coercion.STRING
    required: bool = False
    default: Any = None
    # Optional transform applied after coercion: "none" | "cents_to_units"
    # (integer cents -> decimal units) | "strip_currency".
    transform: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FieldMapping":
        data = dict(data)
        data["coercion"] = Coercion(data.get("coercion", "string"))
        return cls(**data)


@dataclass
class ValidationCheck:
    """A sample-based check declared on a target column."""

    column: str
    kind: str  # not_null | range | regex | allowed_values | unique
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    allowed: list[Any] | None = None
    sample_size: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationCheck":
        return cls(**data)


@dataclass
class MigrationStep:
    """One table move inside a plan, ordered by dependency, not position."""

    step_id: str
    source_table: str
    target_table: str
    primary_key: str  # target column used for idempotent upsert
    mappings: list[FieldMapping] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    validations: list[ValidationCheck] = field(default_factory=list)
    # Optional row filter: {"column": ..., "equals": ...} applied pre-mapping.
    filter_equals: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "source_table": self.source_table,
            "target_table": self.target_table,
            "primary_key": self.primary_key,
            "mappings": [m.to_dict() for m in self.mappings],
            "depends_on": list(self.depends_on),
            "validations": [v.to_dict() for v in self.validations],
            "filter_equals": self.filter_equals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationStep":
        return cls(
            step_id=data["step_id"],
            source_table=data["source_table"],
            target_table=data["target_table"],
            primary_key=data["primary_key"],
            mappings=[FieldMapping.from_dict(m) for m in data.get("mappings", [])],
            depends_on=list(data.get("depends_on", [])),
            validations=[ValidationCheck.from_dict(v) for v in data.get("validations", [])],
            filter_equals=data.get("filter_equals"),
        )


@dataclass
class MigrationPlan:
    plan_id: str
    steps: list[MigrationStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "steps": [s.to_dict() for s in self.steps]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationPlan":
        return cls(
            plan_id=data["plan_id"],
            steps=[MigrationStep.from_dict(s) for s in data.get("steps", [])],
        )

    @classmethod
    def from_json(cls, text: str) -> "MigrationPlan":
        return cls.from_dict(json.loads(text))

    def ordered_steps(self) -> list[MigrationStep]:
        """Topological order honouring depends_on; raises on cycles/unknowns."""
        by_id = {s.step_id: s for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in by_id:
                    raise ValueError(f"step {step.step_id!r} depends on unknown step {dep!r}")
        visited: dict[str, str] = {}
        ordered: list[MigrationStep] = []

        def visit(step: MigrationStep) -> None:
            state = visited.get(step.step_id)
            if state == "done":
                return
            if state == "visiting":
                raise ValueError(f"dependency cycle involving step {step.step_id!r}")
            visited[step.step_id] = "visiting"
            for dep in step.depends_on:
                visit(by_id[dep])
            visited[step.step_id] = "done"
            ordered.append(step)

        for step in self.steps:
            visit(step)
        return ordered


@dataclass
class QuarantinedRow:
    step_id: str
    row_key: str
    reason: str
    source_row: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepResult:
    step_id: str
    source_rows: int
    applied_rows: int
    quarantined_rows: int
    skipped_as_already_applied: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChecksumResult:
    row_count: int
    checksum: str  # sha256 over canonical row JSON, sorted by primary key
    numeric_sums: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationResult:
    step_id: str
    source: ChecksumResult
    target: ChecksumResult
    row_count_match: bool
    checksum_match: bool
    mismatched_columns: list[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return self.row_count_match and self.checksum_match

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["matches"] = self.matches
        return data


@dataclass
class ValidationResult:
    check: ValidationCheck
    rows_checked: int
    violations: int
    sample_violations: list[Any] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["passed"] = self.passed
        return data


@dataclass
class RunManifest:
    run_id: str
    plan_id: str
    mode: RunMode
    status: RunStatus
    steps: list[StepResult] = field(default_factory=list)
    quarantine: list[QuarantinedRow] = field(default_factory=list)
    reconciliation: list[ReconciliationResult] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)
    resumed_from_checkpoint: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def total_applied(self) -> int:
        return sum(s.applied_rows for s in self.steps)

    @property
    def total_quarantined(self) -> int:
        return sum(s.quarantined_rows for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "mode": self.mode.value,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "quarantine": [q.to_dict() for q in self.quarantine],
            "reconciliation": [r.to_dict() for r in self.reconciliation],
            "validations": [v.to_dict() for v in self.validations],
            "resumed_from_checkpoint": self.resumed_from_checkpoint,
            "total_applied": self.total_applied,
            "total_quarantined": self.total_quarantined,
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def canonical_checksum(rows: list[dict[str, Any]], key: str) -> ChecksumResult:
    """Deterministic checksum: rows sorted by key, keys sorted, JSON-encoded."""
    ordered = sorted(rows, key=lambda r: json.dumps(r.get(key), sort_keys=True, default=str))
    digest = hashlib.sha256()
    sums: dict[str, float] = {}
    for row in ordered:
        digest.update(json.dumps(row, sort_keys=True, default=str).encode())
        for col, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sums[col] = sums.get(col, 0.0) + float(value)
            elif isinstance(value, str):
                # Decimal-typed columns land as strings ("49.99"); summing
                # them lets reconciliation name the diverged column.
                try:
                    from decimal import Decimal

                    sums[col] = sums.get(col, 0.0) + float(Decimal(value))
                except Exception:
                    pass
    return ChecksumResult(
        row_count=len(rows),
        checksum=digest.hexdigest(),
        numeric_sums=sums,
    )
