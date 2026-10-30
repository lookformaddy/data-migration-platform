"""data_migration_platform — governed, resumable data migration.

Original code, synthetic data only. See README.md for the architecture.
"""

from data_migration_platform.models import (
    ChecksumResult,
    Coercion,
    FieldMapping,
    MigrationPlan,
    MigrationStep,
    QuarantinedRow,
    ReconciliationResult,
    RunManifest,
    RunMode,
    RunStatus,
    StepResult,
    ValidationCheck,
    ValidationResult,
)

__all__ = [
    "ChecksumResult",
    "Coercion",
    "FieldMapping",
    "MigrationPlan",
    "MigrationStep",
    "QuarantinedRow",
    "ReconciliationResult",
    "RunManifest",
    "RunMode",
    "RunStatus",
    "StepResult",
    "ValidationCheck",
    "ValidationResult",
]

__version__ = "0.1.0"
