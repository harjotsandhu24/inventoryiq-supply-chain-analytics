"""Build the DuckDB analytical database and run integrity checks."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from .config import SQL_DIR

log = logging.getLogger(__name__)


def _insert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{table}: missing columns {missing}")
    con.register("_src", df[cols])
    con.execute(f"INSERT INTO {table} SELECT * FROM _src")
    con.unregister("_src")


def build(
    db_path: Path,
    source_dir: Path,
    tables: dict[str, pd.DataFrame],
    series_scope: list[str] | None = None,
) -> list[tuple]:
    """Create the database from scratch. ``daily_sales`` is unpivoted directly from the CSV.

    ``series_scope`` limits daily_sales to a subset of series ids (None = all).
    Returns integrity-check results as (check_name, violations).
    """
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute((SQL_DIR / "schema" / "01_create_tables.sql").read_text())
    for name in ("stores", "products", "calendar", "series"):
        _insert(con, name, tables[name])
    sales_csv = (source_dir / "sales_train_evaluation.csv").as_posix()
    where = ""
    if series_scope is not None:
        con.register("_scope", pd.DataFrame({"series_id": series_scope}))
        where = "WHERE series_id IN (SELECT series_id FROM _scope)"
    con.execute(
        f"""
        INSERT INTO daily_sales
        SELECT series_id, day, units FROM (
            SELECT replace(id, '_evaluation', '') AS series_id,
                   CAST(substr(d, 3) AS INTEGER) AS day,
                   CAST(units AS INTEGER) AS units
            FROM (UNPIVOT (SELECT * EXCLUDE (item_id, dept_id, cat_id, store_id, state_id)
                           FROM read_csv('{sales_csv}', header = true, auto_detect = true))
                  ON COLUMNS('^d_') INTO NAME d VALUE units)
        ) {where}
        """
    )
    prices_csv = (source_dir / "sell_prices.csv").as_posix()
    con.execute(
        f"""
        INSERT INTO prices
        SELECT store_id, item_id, wm_yr_wk, CAST(sell_price AS DECIMAL(10, 2))
        FROM read_csv('{prices_csv}', header = true, auto_detect = true)
        """
    )
    for name in (
        "suppliers",
        "supplier_assumptions",
        "inventory_ledger",
        "purchase_orders",
        "forecast_results",
        "forecast_evaluation",
        "replenishment_recommendations",
        "scenario_results",
        "simulation_summary",
    ):
        _insert(con, name, tables[name])
    results = run_integrity_checks(con)
    con.close()
    return results


def run_integrity_checks(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    sql = (SQL_DIR / "schema" / "02_integrity_checks.sql").read_text()
    return [tuple(r) for r in con.execute(sql).fetchall()]
