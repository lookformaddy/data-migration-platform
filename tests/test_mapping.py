import pytest

from data_migration_platform.mapping import MappingError, coerce, map_row
from data_migration_platform.models import Coercion, FieldMapping


def test_coercions():
    assert coerce("42", Coercion.INTEGER, "x") == 42
    assert coerce("1,000", Coercion.INTEGER, "x") == 1000
    assert coerce("3.5", Coercion.FLOAT, "x") == 3.5
    assert coerce("YES", Coercion.BOOLEAN, "x") is True
    assert coerce("no", Coercion.BOOLEAN, "x") is False
    assert coerce("2024/02/20", Coercion.DATE, "x") == "2024-02-20"
    assert coerce("$42.5", Coercion.DECIMAL, "x") == "42.50"
    assert coerce("  Ada ", Coercion.TRIM, "x") == "Ada"
    assert coerce("ada", Coercion.UPPER, "x") == "ADA"


def test_coercion_failures_raise():
    with pytest.raises(MappingError):
        coerce("abc", Coercion.INTEGER, "x")
    with pytest.raises(MappingError):
        coerce("maybe", Coercion.BOOLEAN, "x")
    with pytest.raises(MappingError):
        coerce("not-a-date", Coercion.DATE, "x")
    with pytest.raises(MappingError):
        coerce(True, Coercion.INTEGER, "x")


def test_map_row_required_default_and_transform():
    mappings = [
        FieldMapping("id", "id", Coercion.INTEGER, required=True),
        FieldMapping("cents", "amount", Coercion.DECIMAL, transform="cents_to_units"),
        FieldMapping("missing", "status", Coercion.STRING, default="unknown"),
        FieldMapping("gone", "note", Coercion.STRING),
    ]
    out = map_row({"id": "7", "cents": 4999}, mappings)
    assert out == {"id": 7, "amount": "49.99", "status": "unknown", "note": None}
    with pytest.raises(MappingError):
        map_row({"cents": 1}, mappings)


def test_map_row_unknown_transform():
    with pytest.raises(MappingError):
        map_row({"a": "1"}, [FieldMapping("a", "b", Coercion.STRING, transform="bogus")])
