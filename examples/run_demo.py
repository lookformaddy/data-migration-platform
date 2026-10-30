"""End-to-end demo: run with `python3 examples/run_demo.py` from the
project directory. Delegates to the CLI demo (dry-run, apply with one
quarantined row, then a deliberate tamper caught by reconciliation).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_migration_platform.cli import run_demo  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_demo())
