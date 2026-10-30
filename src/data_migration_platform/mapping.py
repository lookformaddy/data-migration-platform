"""Declarative mapping + type coercion. Raises MappingError, never guesses.

Coercion is strict by design: a value that cannot be coerced quarantines
the row with a reason instead of silently landing as NULL or a wrong
type. That is the difference between a migration and a data-loss event.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from data_migration_platform.models import Coercion, FieldMapping

_TRUE = {"true", "1", "yes", "y", "t"}
_FALSE = {"false", "0", "no", "n", "f"}


class MappingError(ValueError):
    """A single field could not be mapped/coerced; the row is quarantined."""


def coerce(value: Any, coercion: Coercion, field_name: str) -> Any:
    if value is None:
        return None
    try:
        if coercion == Coercion.STRING:
            return value if isinstance(value, str) else str(value)
        if coercion == Coercion.TRIM:
            return str(value).strip()
        if coercion == Coercion.UPPER:
            return str(value).strip().upper()
        if coercion == Coercion.LOWER:
            return str(value).strip().lower()
        if coercion == Coercion.INTEGER:
            if isinstance(value, bool):
                raise MappingError(f"{field_name}: boolean is not an integer")
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            text = str(value).strip().replace(",", "")
            return int(text)
        if coercion == Coercion.FLOAT:
            if isinstance(value, bool):
                raise MappingError(f"{field_name}: boolean is not a float")
            return float(value)
        if coercion == Coercion.BOOLEAN:
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise MappingError(f"{field_name}: cannot coerce {value!r} to boolean")
        if coercion == Coercion.DATE:
            if isinstance(value, datetime):
                return value.date().isoformat()
            if isinstance(value, date):
                return value.isoformat()
            text = str(value).strip()
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(text, fmt).date().isoformat()
                except ValueError:
                    continue
            raise MappingError(f"{field_name}: cannot parse date {value!r}")
        if coercion == Coercion.DECIMAL:
            cleaned = re.sub(r"[$,\s]", "", str(value))
            return format(Decimal(cleaned).quantize(Decimal("0.01")), "f")
    except MappingError:
        raise
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise MappingError(f"{field_name}: cannot coerce {value!r} via {coercion.value}: {exc}") from exc
    raise MappingError(f"{field_name}: unknown coercion {coercion!r}")


def apply_transform(value: Any, transform: str, field_name: str) -> Any:
    if value is None or transform == "none":
        return value
    if transform == "cents_to_units":
        try:
            return format((Decimal(str(value)) / 100).quantize(Decimal("0.01")), "f")
        except InvalidOperation as exc:
            raise MappingError(f"{field_name}: cents_to_units failed on {value!r}") from exc
    if transform == "strip_currency":
        return re.sub(r"[$,\s]", "", str(value))
    raise MappingError(f"{field_name}: unknown transform {transform!r}")


def map_row(row: dict[str, Any], mappings: list[FieldMapping]) -> dict[str, Any]:
    """Map one source row; raises MappingError naming the offending field."""
    out: dict[str, Any] = {}
    for mapping in mappings:
        raw = row.get(mapping.source)
        if raw is None:
            if mapping.required:
                raise MappingError(f"{mapping.source}: required field is missing/NULL")
            if mapping.default is not None:
                out[mapping.target] = mapping.default
                continue
            out[mapping.target] = None
            continue
        coerced = coerce(raw, mapping.coercion, mapping.source)
        out[mapping.target] = apply_transform(coerced, mapping.transform, mapping.source)
    return out
