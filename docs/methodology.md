# Methodology

This document explains how InventoryIQ turns daily sales history into purchasing decisions, and how each step was validated. Assumptions are in [assumptions.md](assumptions.md). Headline results are in the [README](../README.md). The detailed result tables (`docs/results.md`, `reports/m5/`) are generated locally from the licensed data by `scripts/build_results_md.py` and are not published.

## 1. Data lineage

| Tag | Meaning | Examples |
|---|---|---|
| **Observed** | Loaded from the Walmart M5 files without modification | daily unit sales, weekly shelf prices, calendar events |
| **Derived** | Calculated directly from observed data | demand pattern class, ABC/XYZ, list price (median shelf price) |
| **Modeled** | Forecasts and planning calculations | 28-day forecasts, forecast error, safety stock, reorder points, recommendations |
| **Simulated** | Assumptions standing in for data M5 does not contain | suppliers, lead times, case packs, MOQs, capacity, unit costs, stock on hand, purchase orders, all costs |

M5 records **sales, not demand**. When a store ran out, lost sales were never recorded, so recorded sales understate true demand during stockouts. Many series contain runs of 90+ consecutive zero-sale days while the item was listed; some of these are probably stockouts (counted in the local validation report). InventoryIQ uses recorded sales as a proxy for demand everywhere and states this limitation wherever results are shown.

## 2. Data validation and cleaning

`src/inventoryiq/validate.py` runs 30+ checks before anything else (report: `reports/m5/data_validation.md`, generated locally). Blocking errors stop the pipeline. Warnings are flagged and handled by an explicit rule, never silently "fixed". See [data_cleaning_rules.md](data_cleaning_rules.md). Key confirmations on the real files:

- 30,490 series = 3,049 items x 10 stores; 1,941 observed days (2011-01-29 to 2016-05-22); calendar extends 28 days further (to 2016-06-19).
- `sales_train_validation.csv` is exactly the first 1,913 days of `sales_train_evaluation.csv`.
- No nulls, no negative or non-integer quantities, no duplicate keys, and no gaps in weekly price listings.
- The sales x calendar x price join returns exactly one row per series-day (59,181,090 rows).
- No sales occur on days when an item has no listed price. Days before an item's first listing are treated as **not available**, never as zero demand.

## 3. Evaluation design (leakage control)

```
d_1 ............ d_1773 | 5 validation folds (28 d each) | d_1914-d_1941 holdout | d_1942-d_1969 future
                          d_1774 ............... d_1913       (untouched)          (forecast only)
```

- **Rolling origin.** Each fold forecasts 28 days using only data before the fold. There are no random splits.
- **Tuning and selection.** Baseline parameters (moving-average window, seasonal weeks, SBA alpha) and per-series method selection use only the five validation folds.
- **Holdout.** The final 28 observed days are evaluated once, after all choices were fixed.
- **Features.** Every gradient-boosting feature for a target day uses sales and prices from at least 28 days earlier, the forecast horizon. Leakage is tested directly: `tests/test_forecasting.py` changes future data and asserts that features and forecasts do not move.

## 4. Forecasting methods

| Method | Description |
|---|---|
| Seasonal naive | Repeats the last observed week |
| Moving average | Mean of the last *w* listed days (*w* tuned: 7/14/28/56) |
| Seasonal moving average | Mean of the last *k* same-weekday values (*k* tuned: 2/4/8) |
| Croston-SBA | Syntetos-Boylan bias-corrected Croston method for intermittent demand (alpha tuned) |
| Gradient boosting | One global scikit-learn `HistGradientBoostingRegressor` with Poisson loss, trained on the two model stores (6,098 series, 2 years of history per fit). Features: lags 28-49, rolling means and standard deviations, zero-share, lagged price and price ratio, calendar events, SNAP, store/department/category. |

**Selection.** Each series uses the method with the lowest mean validation MAE. Gradient boosting must beat the best baseline by at least 2% to be chosen, so extra complexity has to earn its place. Ties go to the simpler method.

**Metrics.** MAE; WAPE = sum|error| / sum(actual), aggregated and never computed per day; bias = sum(forecast - actual) / sum(actual); MASE scaled by the in-sample mean absolute one-day change. WAPE and MASE are reported as undefined (not infinite) when their denominator is zero.

**Prediction intervals.** Empirical quantiles of each series' own validation residuals, added to the point forecast and floored at zero. These are *prediction* intervals: they describe the range of a single future day's sales. They are not *confidence* intervals for the mean. Coverage is measured on the holdout, and the intervals proved too narrow: observed coverage fell short of the nominal 80% and 95%. The app says so.

## 5. Inventory policy (reference: `src/inventoryiq/inventory/policy.py`)

The policy is a periodic review (R, s, S) under a **lost-sales** model (no backorders).

| Quantity | Formula |
|---|---|
| Protection period | P = E[L] + R |
| Demand uncertainty | sigma_P = sqrt(P x sigma_d^2 + mu_d^2 x Var[L]) |
| Safety stock | SS = z x sigma_P, z = Phi^-1(target cycle service level) |
| Reorder point | s = mu_d x P + SS |
| Lot size (v2) | min(max(EOQ, mu_d x R), mu_d x 28 days) |
| Order-up-to | S = s + lot size |
| Inventory position | IP = on hand + on order - backorders (backorders = 0 under lost sales) |
| Order | if IP <= s: Q = max(ceil((S - IP) / case) x case, MOQ) |

- **mu_d** is the mean of the selected model's 28-day forecast. **sigma_d** is the RMSE of that model's daily validation errors, so it measures forecast error, not raw demand variability.
- **Assumptions:** daily demand errors independent across days, lead time independent of demand, fixed review interval.
- **Fallback for intermittent and lumpy items.** The normal approximation is poor for these items, so the reorder point is raised to the empirical CSL-quantile of observed P-day demand totals (last 364 days) whenever that is larger. This is a conservative choice.
- **Risk tiers.** **High** means the item is expected to run out before any new order could arrive (P(lead-time demand > on hand + in transit) >= 50%, or no stock). **Medium** means the position is at or below the reorder point. **Low** covers everything else.
- **Constraints.** Supplier capacity (units per review) is applied first, then the purchasing budget. Both are allocated greedily in priority order: risk tier, then stockout probability, then margin at risk per day. A line that cannot be fully funded is cut to the largest whole-case quantity that still meets its MOQ, or deferred. This is a **transparent heuristic, not a proven optimum**.
- **Duplicate prevention.** One recommendation per line per review. Open orders count in the inventory position, and database constraints enforce one purchase order per line per day.

**Cycle service level vs fill rate.** The target cycle service level is the probability that a replenishment cycle has no stockout. Fill rate is the share of demand units served from stock. The simulation reports both, because they differ.

## 6. Historical simulation (`src/inventoryiq/inventory/simulation.py`)

Each simulated day runs these steps for every line:

1. Receive purchase orders that are due.
2. Use recorded sales as demand.
3. Fulfil from stock and record unmet demand as lost.
4. Close the day: closing = opening + receipts - fulfilled.
5. On review days, run the policy using only information up to that day.
6. Apply capacity, place purchase orders, and draw a lead time.

The invariant is checked inside the simulator and again in SQL, along with ledger continuity and the reconciliation of receipts to purchase orders.

All three policies share starting stock, demand, supplier terms, costs, and lead-time draws. The draws use common random numbers (seeded per supplier and day).

| Policy | Rule |
|---|---|
| Basic (status quo) | Weekly review; order up to 28 days of cover (beyond lead time) when the position falls below 14 days, based on the trailing 28-day average |
| Forecast-informed v1 | The section 5 policy with an uncapped EOQ lot size. **Specified before the simulation was run.** |
| Forecast-informed v2 | v1 plus a 28-day lot-size cap |

**Why v2 exists.** In the first run, v1 placed EOQ lots several times larger on average than the basic rule's orders. These exhausted each simulated supplier's weekly capacity, so other lines were deferred and stocked out. An *exploratory diagnostic run*, outside the published pipeline and not reproduced in the reports, removed the capacity limit, and v1's fill rate rose above the basic rule's. That pointed to lot sizing against capacity as the cause, not the forecasts or safety stock.

v2 caps lot sizes at 28 days of supply, a common retail shelf and space rule. The 28-day value was chosen once and not tuned; no alternative cap was tried.

**Evidence status.**

| Result | Status |
|---|---|
| v1, development window (2015-11-23 to 2016-05-22) | Genuine first test of a pre-specified policy |
| v2, development window | **Not independent.** v2 was designed after seeing v1 fail here. |
| v2, confirmation window (2014-11-24 to 2015-05-24) | Out-of-sample check. Excluded from the redesign and evaluated once, with its own model selection and a gradient-boosting model trained only on prior data. It is an earlier period, not a future one, and it is a single window. |

Both versions remain in every report.

**Costs.** The modeled total is holding + ordering + shortage penalty. Purchasing spend is reported separately and is *not* treated as a cost. The ending inventory value is reported as well. A sensitivity analysis varies gross margin, the shortage-penalty multiplier, and the per-line ordering cost while holding decisions fixed. The ordering-cost dimension matters most. Every component is linear in its assumption, so break-even values are exact given fixed decisions: v2 is cheaper than the basic rule only if a purchase-order line costs more than a break-even amount, which in both windows is well below the assumed $4-$9. With different assumptions the policies would also make different decisions (EOQ uses order and holding cost), which this accounting sensitivity does not capture.

## 7. Scenario analysis

Every scenario reruns `recommend()` from the same immutable inputs, so no state carries over between scenarios. The scenario lab reports two kinds of output:

- **Today's purchasing:** spend, lines funded or deferred, and expected shortage after ordering, E[(D_P - IP_after)+] = sigma_P x G(k).
- **Steady-state annual economics:** average stock = SS + Q/2, orders = 365 x mu / Q, shortage per cycle from the normal loss function. These are textbook approximations, labeled as modeled.

## 8. Python and TypeScript parity

The browser engine (`app/src/lib/engine`) mirrors the Python reference operation for operation. Both use the same inverse-normal (Acklam) and erfc algorithms, so results agree to floating-point precision. The checks:

- `app/tests/unit/parity.test.ts` compares every output field for 9 scenario cases (synthetic fixture plus hand-built edge cases) and for the live 300-line M5 plan.
- `tests/test_pipeline_outputs.py` recomputes the exported plan in Python.
- The Excel workbook is recalculated with the `formulas` engine and compared line by line.

## 9. Known limitations

- Recorded sales are censored demand, so true demand during stockouts is unknown.
- All supplier, cost and inventory values are simulated. They show how decisions respond to assumptions; they do not estimate Walmart's performance.
- Prediction intervals under-cover (too narrow), most of all for lumpy items.
- Gradient boosting was trained only for the two California stores; the other stores use baseline methods.
- Steady-state cost formulas assume roughly stationary demand.
- Budget and capacity allocation is greedy; a mixed-integer model could find better allocations.
- v2's lot-size rule was chosen after diagnosing v1. Its only independent evidence is one earlier 182-day window.
- All published results were recomputed independently by `scripts/release_audit.py` (SQL over the stored ledger and forecasts). The confirmation window was re-executed rather than recomputed from a stored ledger.
