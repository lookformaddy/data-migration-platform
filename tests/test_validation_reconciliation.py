from data_migration_platform.models import ValidationCheck, canonical_checksum
from data_migration_platform.reconciliation import reconcile
from data_migration_platform.validation import run_check

ROWS = [
    {"id": 1, "email": "a@example.com", "amount": "10.00"},
    {"id": 2, "email": "bad-email", "amount": "-5.00"},
    {"id": 3, "email": "a@example.com", "amount": "20.00"},
]


def test_validation_kinds():
    assert run_check(ROWS, ValidationCheck("email", "regex", pattern=r"^[^@]+@[^@]+$")).violations == 1
    assert run_check(ROWS, ValidationCheck("amount", "range", min_value=0.0)).violations == 1
    assert run_check(ROWS, ValidationCheck("email", "unique")).violations == 1
    assert run_check(ROWS, ValidationCheck("email", "not_null")).violations == 0
    assert run_check(ROWS, ValidationCheck("amount", "allowed_values", allowed=["10.00"])).violations == 2
    assert run_check(ROWS, ValidationCheck("email", "regex", pattern=r"^[^@]+@[^@]+$"), ).sample_violations == ["bad-email"]


def test_validation_sample_size_limits_scope():
    check = ValidationCheck("email", "regex", pattern=r"^[^@]+@[^@]+$", sample_size=1)
    assert run_check(ROWS, check).rows_checked == 1
    assert run_check(ROWS, check).violations == 0  # bad row is outside the sample


def test_checksum_is_order_insensitive_but_value_sensitive():
    a = canonical_checksum(ROWS, "id")
    b = canonical_checksum(list(reversed(ROWS)), "id")
    assert a.checksum == b.checksum and a.row_count == 3
    changed = [dict(r, amount="11.00") if r["id"] == 1 else r for r in ROWS]
    assert canonical_checksum(changed, "id").checksum != a.checksum


def test_reconcile_matches_and_mismatches():
    assert reconcile("s", ROWS, ROWS, "id").matches
    short = ROWS[:2]
    result = reconcile("s", ROWS, short, "id")
    assert not result.matches and not result.row_count_match
