"""Release-readiness audit: recompute published results by an independent route.

Forecast accuracy is recomputed in SQL from `forecast_results` x `daily_sales`
(not from the pipeline's error sums). Main-window simulation results are
recomputed in SQL from the stored daily ledger and purchase orders. The
confirmation window (whose ledger is not stored) is re-executed
deterministically and its ledger re-aggregated the same way. Cost sensitivity
uses the fact that every modeled cost component is linear in its assumption,
with purchasing decisions held fixed.

Usage: python scripts/release_audit.py   (writes reports/m5/release_audit.json)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "reports" / "m5"
DB = ROOT / "data" / "processed" / "m5" / "inventoryiq.duckdb"
HOLDOUT = (1914, 1941)


def close(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def forecast_checks(con) -> dict:
    sql = f"""
    WITH f AS (SELECT series_id, day, method, forecast FROM forecast_results WHERE phase = 'holdout'),
         a AS (SELECT series_id, day, units FROM daily_sales WHERE day BETWEEN {HOLDOUT[0]} AND {HOLDOUT[1]}),
         listed AS (
            SELECT d.series_id, d.day, d.units
            FROM daily_sales d JOIN series s USING (series_id) JOIN calendar c USING (day)
            JOIN prices p ON p.item_id = s.item_id AND p.store_id = s.store_id AND p.wm_yr_wk = c.wm_yr_wk
            WHERE s.in_model_scope AND d.day < {HOLDOUT[0]}),
         diffs AS (
            SELECT series_id, ABS(units - LAG(units) OVER w) AS ad, day - LAG(day) OVER w AS gap
            FROM listed WINDOW w AS (PARTITION BY series_id ORDER BY day)),
         scale AS (SELECT series_id, AVG(ad) FILTER (WHERE gap = 1) AS sc FROM diffs GROUP BY 1),
         per_series AS (
            SELECT method, series_id, AVG(ABS(forecast - units)) AS mae
            FROM f JOIN a USING (series_id, day) GROUP BY 1, 2)
    SELECT f.method, COUNT(*) AS days, SUM(units) AS actual,
           SUM(ABS(forecast - units)) / COUNT(*) AS mae,
           SUM(ABS(forecast - units)) / SUM(units) AS wape,
           SUM(forecast - units) / SUM(units) AS bias,
           (SELECT AVG(p.mae / s.sc) FROM per_series p JOIN scale s USING (series_id)
             WHERE p.method = f.method AND s.sc > 0) AS mase
    FROM f JOIN a USING (series_id, day) GROUP BY f.method ORDER BY wape
    """
    sql_res = con.execute(sql).df()
    rep = pd.read_csv(REP / "forecast_holdout_by_method_model_stores.csv").set_index("method")
    rows, ok = [], True
    for r in sql_res.itertuples():
        p = rep.loc[r.method]
        match = (
            all(close(getattr(r, k), p[k], 1e-6) for k in ("mae", "wape", "bias", "mase"))
            and r.days == p["days"]
        )
        ok &= match
        rows.append(
            {
                "method": r.method,
                "days": int(r.days),
                "wape_sql": r.wape,
                "wape_report": p["wape"],
                "mase_sql": r.mase,
                "mase_report": p["mase"],
                "bias_sql": r.bias,
                "match": bool(match),
            }
        )

    # Selection must be reproducible from validation errors alone (no holdout information).
    sel_sql = """
    WITH v AS (
        SELECT series_id, method, SUM(abs_err) / SUM(n_days) AS mae
        FROM forecast_evaluation WHERE phase = 'validation' GROUP BY 1, 2),
    base AS (
        SELECT series_id, method, mae,
               ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY mae,
                 CASE method WHEN 'seasonal_naive' THEN 0 WHEN 'moving_average' THEN 1
                             WHEN 'seasonal_ma' THEN 2 WHEN 'sba' THEN 3 END) AS rk
        FROM v WHERE method <> 'gbm'),
    best AS (SELECT series_id, method AS best_base, mae AS best_mae FROM base WHERE rk = 1),
    rule AS (
        SELECT b.series_id,
               CASE WHEN g.mae < b.best_mae * 0.98 THEN 'gbm' ELSE b.best_base END AS chosen
        FROM best b LEFT JOIN v g ON g.series_id = b.series_id AND g.method = 'gbm'),
    hold AS (SELECT series_id, day, method, forecast FROM forecast_results WHERE phase = 'holdout')
    SELECT COUNT(DISTINCT r.series_id) AS series,
           SUM(CASE WHEN ABS(s.forecast - c.forecast) > 1e-9 THEN 1 ELSE 0 END) AS mismatched_days
    FROM rule r
    JOIN hold s ON s.series_id = r.series_id AND s.method = 'selected'
    JOIN hold c ON c.series_id = r.series_id AND c.method = r.chosen AND c.day = s.day
    """
    sel = con.execute(sel_sql).fetchone()
    return {
        "holdout_by_method": rows,
        "all_match": bool(ok),
        "selection_reproducible_from_validation_only": {
            "series": int(sel[0]),
            "mismatched_days": int(sel[1]),
        },
    }


LEDGER_SQL = """
WITH l AS (SELECT * FROM {ledger}),
     a AS (SELECT series_id, unit_cost, unit_price, order_cost FROM {lines}),
     po AS (SELECT * FROM {pos})
SELECT l.policy,
       COUNT(DISTINCT l.series_id) AS lines,
       SUM(l.demand) AS demand_units, SUM(l.fulfilled) AS fulfilled_units, SUM(l.lost) AS lost_units,
       SUM(l.fulfilled) / SUM(l.demand) AS fill_rate,
       SUM(CASE WHEN l.lost > 0 THEN 1 ELSE 0 END) AS stockout_days,
       SUM(l.closing * a.unit_cost) / COUNT(DISTINCT l.day) AS avg_inventory_value,
       SUM(l.closing * a.unit_cost) * 0.25 / 365 AS holding_cost,
       SUM(l.lost * GREATEST(a.unit_price - a.unit_cost, 0)) * 1.5 AS shortage_penalty,
       SUM(l.ordered * a.unit_cost) AS purchasing_spend,
       (SELECT COUNT(*) FROM po WHERE po.policy = l.policy) AS purchase_orders,
       (SELECT SUM(a2.order_cost) FROM po JOIN a a2 USING (series_id) WHERE po.policy = l.policy) AS ordering_cost
FROM l JOIN a USING (series_id)
GROUP BY l.policy ORDER BY l.policy
"""


def recompute(con, ledger: str, lines: str, pos: str) -> pd.DataFrame:
    d = con.execute(LEDGER_SQL.format(ledger=ledger, lines=lines, pos=pos)).df()
    d["modeled_total_cost"] = d["holding_cost"] + d["ordering_cost"] + d["shortage_penalty"]
    return d


def compare_sim(recomp: pd.DataFrame, rep: pd.DataFrame) -> list[dict]:
    out = []
    keys = [
        "lines",
        "demand_units",
        "lost_units",
        "fill_rate",
        "stockout_days",
        "avg_inventory_value",
        "purchase_orders",
        "holding_cost",
        "ordering_cost",
        "shortage_penalty",
        "purchasing_spend",
        "modeled_total_cost",
    ]
    rep = rep.set_index("policy")
    for r in recomp.itertuples():
        p = rep.loc[r.policy]
        diffs = {
            k: (float(getattr(r, k)), float(p[k]))
            for k in keys
            if not close(getattr(r, k), p[k], 1e-5) and abs(getattr(r, k) - p[k]) > 0.011
        }
        out.append({"policy": r.policy, "match": not diffs, "differences": diffs})
    return out


def simulation_checks(con) -> dict:
    rep = pd.read_csv(REP / "simulation_summary.csv")
    res = {}
    con.execute(
        "CREATE TEMP VIEW sa AS SELECT series_id, unit_cost, unit_price, order_cost FROM supplier_assumptions"
    )
    for scope in ("demo", "model_stores"):
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW led AS SELECT * FROM inventory_ledger WHERE scope = '{scope}'"
        )
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW pos AS SELECT * FROM purchase_orders WHERE scope = '{scope}'"
        )
        r = recompute(con, "led", "sa", "pos")
        res[f"main/{scope}"] = compare_sim(
            r, rep[(rep["scope"] == scope) & (rep["window"] == "main")]
        )
        res[f"main/{scope}/recomputed"] = r.round(4).to_dict("records")
    inv = con.execute("""
        SELECT SUM(CASE WHEN opening + receipts - fulfilled <> closing THEN 1 ELSE 0 END),
               SUM(CASE WHEN fulfilled + lost <> demand THEN 1 ELSE 0 END),
               SUM(CASE WHEN closing < 0 THEN 1 ELSE 0 END), COUNT(*) FROM inventory_ledger""").fetchone()
    res["ledger_invariants"] = {
        "balance_violations": int(inv[0]),
        "demand_split_violations": int(inv[1]),
        "negative_stock": int(inv[2]),
        "rows": int(inv[3]),
    }
    return res


def confirmation_rerun(con) -> dict:
    """Deterministically re-execute the confirmation window and re-aggregate its ledger in SQL."""
    sys.path.insert(0, str(ROOT / "src"))
    from inventoryiq import config as C
    from inventoryiq.data_io import load_dataset
    from inventoryiq.forecasting import gbm
    from inventoryiq.inventory.policy import Settings
    from inventoryiq.sim_stage import build_sim_forecasts, ledger_frame, run_policies
    from inventoryiq.suppliers import line_master

    ds = load_dataset(C.RAW_DIR, "m5", stores=C.MODEL_STORES)
    W = C.Windows(ds.last_day)
    conf = W.confirmation
    cube = gbm.FeatureCube(ds, ds.last_day)
    sf = build_sim_forecasts(ds, W, cube, C.PROCESSED_DIR / "m5" / "cache", "m5", window=conf)
    lines = line_master(ds, conf[0] - 1)
    settings = Settings(
        service_level=0.95,
        review_period=7,
        holding_rate=C.FIN.annual_holding_rate,
        shortage_multiplier=C.FIN.shortage_penalty_multiplier,
    )
    r = run_policies(
        ds, W, lines, sf, np.arange(ds.n_series), settings, "model_stores", conf, "confirmation"
    )
    ids = r["lines"]["series"].to_numpy()
    led = pd.concat(
        [
            ledger_frame(r[k], ids, conf[0], "model_stores")
            for k in ("basic", "forecast_v1", "forecast")
        ]
    )
    led = led.rename(columns={"series": "series_id"})
    pos = pd.concat([r[k]["purchase_orders"] for k in ("basic", "forecast_v1", "forecast")]).rename(
        columns={"series": "series_id"}
    )
    la = r["lines"].rename(columns={"series": "series_id"})[
        ["series_id", "unit_cost", "unit_price", "order_cost"]
    ]
    con.register("cled", led)
    con.register("cpos", pos)
    con.register("clines", la)
    recomp = recompute(con, "cled", "clines", "cpos")
    rep = pd.read_csv(REP / "simulation_summary.csv")
    return {
        "window_days": [int(conf[0]), int(conf[1])],
        "comparison": compare_sim(
            recomp, rep[(rep["scope"] == "model_stores") & (rep["window"] == "confirmation")]
        ),
        "recomputed": recomp.round(4).to_dict("records"),
    }


def cost_sensitivity() -> dict:
    """Break-even multipliers: each modeled cost component is linear in its own assumption (decisions fixed)."""
    rep = pd.read_csv(REP / "simulation_summary.csv")
    out = {}
    for (window, scope), g in rep.groupby(["window", "scope"]):
        g = g.set_index("policy")
        b, v = g.loc["basic"], g.loc["forecast"]
        d_hold, d_order, d_short = (
            (v["holding_cost"] - b["holding_cost"]),
            (v["ordering_cost"] - b["ordering_cost"]),
            (v["shortage_penalty"] - b["shortage_penalty"]),
        )
        # v2 - basic = d_hold*h + d_order*o + d_short*s ; break-even order-cost multiplier with h = s = 1
        be_order = -(d_hold + d_short) / d_order if d_order != 0 else None
        grid = []
        for o in (0.1, 0.25, 0.5, 0.75, 1.0):
            for h in (0.5, 1.0, 1.5, 2.0):
                for s in (0.5, 1.0, 2.0):
                    grid.append(
                        {
                            "order_cost_x": o,
                            "holding_rate_x": h,
                            "shortage_penalty_x": s,
                            "v2_minus_basic": round(d_hold * h + d_order * o + d_short * s, 2),
                        }
                    )
        gd = pd.DataFrame(grid)
        out[f"{window}/{scope}"] = {
            "basic": {
                k: float(b[k])
                for k in ("holding_cost", "ordering_cost", "shortage_penalty", "modeled_total_cost")
            },
            "v2": {
                k: float(v[k])
                for k in ("holding_cost", "ordering_cost", "shortage_penalty", "modeled_total_cost")
            },
            "components_reconcile": bool(
                close(
                    b["modeled_total_cost"],
                    b["holding_cost"] + b["ordering_cost"] + b["shortage_penalty"],
                    1e-6,
                )
                and close(
                    v["modeled_total_cost"],
                    v["holding_cost"] + v["ordering_cost"] + v["shortage_penalty"],
                    1e-6,
                )
            ),
            "v2_minus_basic_by_component": {
                "holding": round(d_hold, 2),
                "ordering": round(d_order, 2),
                "shortage": round(d_short, 2),
            },
            "break_even_order_cost_multiplier": None
            if be_order is None
            else round(float(be_order), 3),
            "break_even_order_cost_per_line_usd_range": None
            if be_order is None
            else [round(4 * be_order, 2), round(9 * be_order, 2)],
            "v2_cheaper_share_of_grid": round(float((gd["v2_minus_basic"] < 0).mean()), 3),
            "grid": grid,
        }
    return out


def deferred_analysis() -> dict:
    rec = pd.read_csv(ROOT / "deliverables" / "m5" / "csv" / "replenishment_recommendations.csv")
    cap = json.loads((ROOT / "deliverables" / "m5" / "csv" / "planning_settings.json").read_text())[
        "capacity"
    ]
    by = (
        rec[rec["needs_order"]]
        .groupby("supplier_id")
        .agg(
            lines_needing=("series", "size"),
            units_requested=("recommended_qty", "sum"),
            units_funded=("final_qty", "sum"),
            deferred=("status", lambda s: int(s.str.startswith("Deferred").sum())),
            reduced=("status", lambda s: int(s.str.startswith("Reduced").sum())),
            high_risk_deferred=("risk", lambda s: 0),
        )
    )
    hr = (
        rec[rec["status"].str.startswith("Deferred") & (rec["risk"] == "High")]
        .groupby("supplier_id")
        .size()
    )
    by["high_risk_deferred"] = hr.reindex(by.index).fillna(0).astype(int)
    by["capacity_units"] = by.index.map(cap)
    by["requested_vs_capacity"] = (by["units_requested"] / by["capacity_units"]).round(2)
    d = rec[rec["status"].str.startswith("Deferred")]
    return {
        "deferred_total": int(len(d)),
        "by_risk": d["risk"].value_counts().to_dict(),
        "by_supplier": by.reset_index().to_dict("records"),
        "deferred_with_zero_stock": int((d["on_hand"] == 0).sum()),
        "median_coverage_days_deferred": float(d["coverage_days"].median()),
    }


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    result = {"forecast": forecast_checks(con), "simulation": simulation_checks(con)}
    result["confirmation_window"] = confirmation_rerun(con)
    result["cost_sensitivity"] = cost_sensitivity()
    result["deferred"] = deferred_analysis()
    (REP / "release_audit.json").write_text(json.dumps(result, indent=2, default=float))
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "cost_sensitivity"}, indent=1, default=float
        )[:6000]
    )
    for k, v in result["cost_sensitivity"].items():
        print(
            k,
            {
                x: v[x]
                for x in (
                    "v2_minus_basic_by_component",
                    "break_even_order_cost_multiplier",
                    "break_even_order_cost_per_line_usd_range",
                    "v2_cheaper_share_of_grid",
                    "components_reconcile",
                )
            },
        )


if __name__ == "__main__":
    main()
