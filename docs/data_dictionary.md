# Data dictionary

DuckDB database: `data/processed/<source>/inventoryiq.duckdb`, built from `sql/schema/01_create_tables.sql`. Lineage: **O** observed, **D** derived, **M** modeled, **S** simulated.

## Observed and derived tables

| Table | Grain / key | Columns (lineage) |
|---|---|---|
| `stores` | `store_id` | state_id (O) |
| `products` | `item_id` | dept_id, cat_id (O) |
| `calendar` | `day` (M5 `d_N`) | date, wm_yr_wk, weekday, wday, month, year, event_name/type 1-2, snap_ca/tx/wi (O) |
| `series` | `series_id` = item_store | item_id -> products, store_id -> stores (O); availability_start_day, pattern (D); in_model_scope, in_demo (design flags) |
| `daily_sales` | (series_id, day), uniqueness checked | units (O). 59.2M rows for M5. |
| `prices` | (store_id, item_id, wm_yr_wk) | sell_price (O) |

## Simulated tables

| Table | Grain / key | Columns |
|---|---|---|
| `suppliers` | `supplier_id` | name, departments, lead_time_mean_days, lead_time_sd_days, moq_cases, order_cost_per_line, capacity_factor, on_time_rate_assumed, assumptions_version |
| `supplier_assumptions` | `series_id` | supplier_id, case_pack, moq_units, unit_price (O median), unit_cost, gross_margin, order_cost, lead_time_mean, lead_time_sd |
| `inventory_ledger` | (scope, policy, series_id, day) | opening, receipts, demand, fulfilled, lost, closing, on_order, ordered. Invariants: opening + receipts - fulfilled = closing; fulfilled + lost = demand; all >= 0. |
| `purchase_orders` | (scope, po_id); unique (scope, policy, series_id, order_day) | quantity, unit_cost, supplier_id, lead_time_realised, expected_arrival_day, arrival_day, status |
| `simulation_summary` | (scope, window, policy) | fill_rate, cycle_service_level, lost_units, stockout_days, avg_inventory_units/value, purchase_orders, purchasing_spend, holding_cost, ordering_cost, shortage_penalty, modeled_total_cost |

## Modeled tables

| Table | Grain / key | Columns |
|---|---|---|
| `forecast_results` | (series_id, phase, day, method) | forecast; lo80, hi80, lo95, hi95 (for `selected`). Phase = holdout or future. |
| `forecast_evaluation` | (series_id, phase, fold, method) | n_days, abs_err, err, actual, forecast, sq_err, mase_scale. Error sums, so any aggregate can be rebuilt exactly. |
| `replenishment_recommendations` | `series_id` | mu, sigma, lead_time, protection_period, safety_stock, reorder_point, order_up_to, on_hand, on_order, inventory_position, coverage_days, p_stockout_lead_time, risk, recommended_qty, final_qty, status, unit_cost, order_value, priority_rank, abc, xyz, reason |
| `scenario_results` | (scenario_id, series_id) | settings (service_level, review_period, lead_time_shift, lead_time_sd_mult, budget), reorder_point, final_qty, order_value, status, expected_short_units, annual_total_cost |

## Glossary

| Term | Definition |
|---|---|
| mu (expected daily demand) | Mean of the selected model's 28-day forecast |
| sigma (forecast error) | RMSE of daily validation errors for the selected model |
| Protection period P | Expected lead time + review interval |
| Safety stock | z x sigma_P (or empirical fallback minus mu x P) |
| Reorder point s | Inventory position at or below which an order is placed |
| Order-up-to S | Target position after ordering: s + lot size |
| Inventory position | On hand + on order - backorders |
| Coverage (days) | On hand / mu |
| Cycle service level | Probability of no stockout in a replenishment cycle |
| Fill rate | Share of demand units served from stock |
| WAPE | sum abs error / sum actual |
| MASE | MAE / mean absolute one-day change in history |
| ABC | Value classes: A = first 80% of cumulative sales value, B = next 15%, C = rest |
| XYZ | Weekly-demand CV: X <= 0.5, Y <= 1.0, Z > 1.0 |
| Demand pattern | Syntetos-Boylan: smooth, erratic, intermittent, lumpy (ADI 1.32, CV^2 0.49) |

## Application data (`app/public/data/`)

| File | Contents |
|---|---|
| `manifest.json` | Source label, planning date, windows, default settings, presets, supplier capacity |
| `lines.json` | Per demo line: engine inputs (mu, sigma, lead time, case pack, MOQ, costs, stock, in-transit POs, 364-day history), classes, holdout metrics |
| `reference_plan.json` | Python reference recommendations for the default settings (parity tests) |
| `forecasts/<series>.json` | 182-day history, holdout actuals and forecasts (all methods), next-28-day forecast with 80% and 95% intervals |
| `evaluation.json`, `simulation.json`, `suppliers.json` | Aggregate accuracy tables, simulation summaries and sensitivity, supplier table |
