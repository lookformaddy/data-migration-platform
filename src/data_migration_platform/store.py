"""In-memory table store with JSON snapshots, checkpoints and rollback.

The store is deliberately boring: tables are lists of dicts, keyed by
table name. Production adapters (warehouse, database) would sit behind
this same interface; the migration logic never sees a real connection,
which is what makes it fully testable without infrastructure.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class TableStore:
    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = copy.deepcopy(tables or {})

    def rows(self, table: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.tables.get(table, []))

    def set_table(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.tables[table] = copy.deepcopy(rows)

    def upsert(self, table: str, key: str, row: dict[str, Any]) -> bool:
        """Insert or replace by primary key. Returns True if it was an insert."""
        existing = self.tables.setdefault(table, [])
        for index, current in enumerate(existing):
            if current.get(key) == row.get(key):
                existing[index] = copy.deepcopy(row)
                return False
        existing.append(copy.deepcopy(row))
        return True

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return copy.deepcopy(self.tables)

    def restore(self, snapshot: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = copy.deepcopy(snapshot)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())
