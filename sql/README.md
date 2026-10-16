# SQL

All queries run on DuckDB against `data/processed/<source>/inventoryiq.duckdb`, which the pipeline builds.

```powershell
.\.venv\Scripts\python.exe scripts\run_sql.py sql\analysis\07_immediate_replenishment.sql
```

You can also use the DuckDB CLI: `duckdb data/processed/m5/inventoryiq.duckdb < sql/analysis/01_top_sales_value.sql`.

| File | Business question | Techniques |
|---|---|---|
| `schema/01_create_tables.sql` | Analytical schema: 15 tables, keys, foreign keys, CHECK constraints, lineage tags | DDL |
| `schema/02_integrity_checks.sql` | 19 integrity checks (duplicates, join fan-out, ledger balance and continuity, MOQ and case packs) | UNION ALL checks, LAG, anti-joins |
| `analysis/01_top_sales_value.sql` | Which products have the highest sales value? | joins through the calendar week, RANK, QUALIFY, share of total |
| `analysis/02_demand_volatility.sql` | Which products are most volatile? | weekly roll-up, STDDEV, CV, NTILE, XYZ CASE |
| `analysis/03_rolling_demand_trends.sql` | Is demand growing or declining? | 7- and 28-day window frames, LAG 364, date intervals |
| `analysis/04_lowest_days_of_coverage.sql` | Which items have the lowest modeled coverage? | NULLIF-safe division, CASE, ranking |
| `analysis/05_poor_forecast_accuracy.sql` | Where is forecast accuracy poor? | FILTER pivots, PERCENT_RANK by category |
| `analysis/06_supplier_delivery_risk.sql` | Which simulated suppliers create the most delivery risk? | multi-CTE, conditional aggregates, EXCLUDE |
| `analysis/07_immediate_replenishment.sql` | What needs ordering now? | running totals, date arithmetic |
| `analysis/08_budget_impact.sql` | How does budget change what gets bought? | parameter-table CROSS JOIN, running spend, scenario comparison |
| `analysis/09_policy_comparison_by_category.sql` | Where does each policy win? | ledger aggregation, FILTER pivot, trade-off CASE |
| `analysis/10_abc_xyz_matrix.sql` | How concentrated is value, and how variable is demand? | conditional counts, window share |
| `analysis/11_price_change_response.sql` | Do price cuts lift units? | LAG on weekly prices, price-state classification |
| `analysis/12_event_and_weekday_patterns.sql` | How do weekdays and events change demand? | GROUPING SETS, date functions, indexed demand |

`tests/test_pipeline_outputs.py` runs every query and checks that it returns rows and reconciles with the Python totals.
