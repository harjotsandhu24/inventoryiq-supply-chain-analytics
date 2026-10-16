"""Run a SQL file against the InventoryIQ DuckDB database and print the result.

Usage: python scripts/run_sql.py sql/analysis/01_top_sales_value.sql [m5|synthetic]
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sql_path = Path(sys.argv[1])
    source = sys.argv[2] if len(sys.argv) > 2 else "m5"
    db = ROOT / "data" / "processed" / source / "inventoryiq.duckdb"
    if not db.exists():
        raise SystemExit(
            f"{db} not found - run `python -m inventoryiq.pipeline --source {source}` first"
        )
    con = duckdb.connect(str(db), read_only=True)
    df = con.execute(sql_path.read_text()).df()
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.max_rows", 60):
        print(df)


if __name__ == "__main__":
    main()
