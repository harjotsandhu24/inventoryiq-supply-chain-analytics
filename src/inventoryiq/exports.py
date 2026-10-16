"""Exports: application JSON, analyst CSVs, database tables, and engine parity fixtures."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .forecasting.backtest import LABELS, METHODS, interval_bounds
from .forecasting.metrics import summarise
from .planning import PRESETS, line_arrays, recommend
from .sim_stage import POLICY_LABELS, WINDOW_LABELS, ledger_frame
from .suppliers import supplier_table
from .util import clean, records, write_json

PARITY_FIELDS = [
    "lead_time",
    "protection_period",
    "z",
    "sigma_p",
    "safety_stock",
    "rop_basis",
    "reorder_point",
    "eoq",
    "order_up_to",
    "inventory_position",
    "needs_order",
    "raw_quantity",
    "moq_units",
    "recommended_qty",
    "coverage_days",
    "lead_time_demand",
    "p_stockout_lead_time",
    "expected_short_lead_time",
    "risk",
    "final_qty",
    "status",
    "order_value",
    "priority_rank",
    "expected_receipt_day",
    "expected_short_units",
    "p_short",
    "expected_ending_units",
    "annual_avg_order_qty",
    "annual_avg_inventory_units",
    "annual_orders_per_year",
    "annual_expected_short_units_per_year",
    "annual_fill_rate",
    "annual_holding_cost",
    "annual_ordering_cost",
    "annual_shortage_cost",
    "annual_total_cost",
    "capacity_limit",
    "capacity_left",
    "budget_left",
    "reason",
]


def _date(ds, day: int) -> str:
    if day <= ds.n_calendar_days:
        return ds.date_of(day)
    base = dt.date.fromisoformat(ds.date_of(ds.n_calendar_days))
    return (base + dt.timedelta(days=day - ds.n_calendar_days)).isoformat()


def _round(a, k=4):
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), k) for v in a]


def settings_dict(s) -> dict:
    return {
        "serviceLevel": s.service_level,
        "reviewPeriod": s.review_period,
        "leadTimeShift": s.lead_time_shift,
        "leadTimeSdMultiplier": s.lead_time_sd_multiplier,
        "budget": s.budget,
        "intermittentFallback": s.intermittent_fallback,
        "holdingRate": s.holding_rate,
        "shortageMultiplier": s.shortage_multiplier,
        "maxCycleDays": s.max_cycle_days,
    }


def line_inputs(L: pd.DataFrame, hist: np.ndarray) -> list[dict]:
    out = []
    for i, r in enumerate(L.itertuples()):
        out.append(
            {
                "id": r.series,
                "mu": float(r.mu),
                "sigma": float(r.sigma),
                "ltMean": float(r.lead_time_mean),
                "ltSd": float(r.lead_time_sd),
                "onHand": float(r.on_hand),
                "onOrder": float(r.on_order),
                "moq": float(r.moq_units),
                "casePack": float(r.case_pack),
                "unitCost": float(r.unit_cost),
                "unitPrice": float(r.unit_price),
                "orderCost": float(r.order_cost),
                "intermittent": bool(r.intermittent),
                "supplier": r.supplier_id,
                "history": _round(hist[i], 0),
            }
        )
    return out


def _metrics_by_series(df: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in df.itertuples():
        mae = r.abs_err / r.n if r.n else np.nan
        out.setdefault(r.series, {})[r.method] = {
            "mae": mae,
            "wape": r.abs_err / r.actual if r.actual > 0 else None,
            "bias": r.err / r.actual if r.actual > 0 else None,
            "mase": mae / r.scale if r.scale and r.scale > 0 else None,
            "actual": r.actual,
            "days": r.n,
        }
    return out


def export_app(ctx: dict, out: Path) -> None:
    ds, W, fr, L, rec, _demo = ctx["ds"], ctx["W"], ctx["fr"], ctx["lines"], ctx["rec"], ctx["demo"]
    if out.exists():
        shutil.rmtree(out)
    (out / "forecasts").mkdir(parents=True)
    T = ds.last_day
    gidx = ctx["gidx"]
    ids = L["series"].to_numpy()
    basic_po = ctx["sim_demo"]["basic"]["purchase_orders"]
    transit = basic_po[basic_po["status"] == "in transit"] if len(basic_po) else basic_po
    hold = _metrics_by_series(fr.holdout_errors[fr.holdout_errors["series"].isin(ids)])
    val = fr.selection.set_index("series")

    lines_json = []
    for i, r in enumerate(L.itertuples()):
        tr = transit[transit["series"] == r.series] if len(transit) else transit
        lines_json.append(
            {
                "id": r.series,
                "item": r.item_id,
                "store": r.store_id,
                "dept": r.dept_id,
                "cat": r.cat_id,
                "supplier": r.supplier_id,
                "abc": r.abc,
                "xyz": r.xyz,
                "pattern": r.pattern,
                "intermittent": bool(r.intermittent),
                "method": r.method,
                "methodLabel": LABELS[r.method],
                "mu": float(r.mu),
                "sigma": float(r.sigma),
                "ltMean": float(r.lead_time_mean),
                "ltSd": float(r.lead_time_sd),
                "orderCost": float(r.order_cost),
                "casePack": int(r.case_pack),
                "moq": int(r.moq_units),
                "unitCost": float(r.unit_cost),
                "unitPrice": float(r.unit_price),
                "onHand": int(r.on_hand),
                "onOrder": int(r.on_order),
                "units364": float(r.units_364),
                "value364": round(float(r.sales_value_364), 2),
                "inTransit": [
                    {
                        "po": p.po_id,
                        "qty": int(p.quantity),
                        "orderDate": _date(ds, int(p.order_day)),
                        "expectedDate": _date(ds, int(p.expected_arrival_day)),
                    }
                    for p in tr.itertuples()
                ],
                "history": _round(ctx["hist"][i], 0),
                "holdout": hold.get(r.series, {}).get("selected"),
                "holdoutNaive": hold.get(r.series, {}).get("seasonal_naive"),
                "validationMae": val.loc[r.series, "validation_mae_selected"]
                if r.series in val.index
                else None,
            }
        )
    write_json(out / "lines.json", lines_json)

    ref = rec.set_index("series")
    write_json(
        out / "reference_plan.json",
        {
            "settings": settings_dict(ctx["settings"]),
            "capacity": ctx["capacity"],
            "planningDay": ctx["plan_day"],
            "results": {sid: {k: ref.loc[sid, k] for k in PARITY_FIELDS} for sid in ids},
        },
    )

    sup = supplier_table()
    sup["capacity_units_per_week"] = sup["supplier_id"].map(ctx["capacity"])
    write_json(out / "suppliers.json", records(sup))

    # ---- forecasts per line
    hs, he = W.holdout
    fs, fe = W.future
    hist_start = hs - 182
    for i, sid in enumerate(ids):
        g = gidx[i]
        q = fr.residual_q["selected"][g : g + 1]
        hb = interval_bounds(fr.holdout_forecasts["selected"][g : g + 1], np.nan_to_num(q))
        fb = interval_bounds(fr.future_forecasts["selected"][g : g + 1], np.nan_to_num(q))
        methods = {
            m: _round(fr.holdout_forecasts[m][g], 3)
            for m in METHODS
            if np.isfinite(fr.holdout_forecasts[m][g]).all()
        }
        fut_methods = {
            m: _round(fr.future_forecasts[m][g], 3)
            for m in METHODS
            if np.isfinite(fr.future_forecasts[m][g]).all()
        }
        write_json(
            out / "forecasts" / f"{sid}.json",
            {
                "id": sid,
                "method": L["method"].iloc[i],
                "methodLabel": LABELS[L["method"].iloc[i]],
                "history": {
                    "start": _date(ds, hist_start),
                    "values": _round(
                        np.where(
                            ds.available[g, hist_start - 1 : hs - 1],
                            ds.sales[g, hist_start - 1 : hs - 1],
                            np.nan,
                        ),
                        0,
                    ),
                },
                "holdout": {
                    "start": _date(ds, hs),
                    "actual": _round(ds.sales[g, hs - 1 : he], 0),
                    "forecast": methods,
                    "selected": _round(fr.holdout_forecasts["selected"][g], 3),
                    "lo80": _round(hb["lo80"][0], 3),
                    "hi80": _round(hb["hi80"][0], 3),
                    "lo95": _round(hb["lo95"][0], 3),
                    "hi95": _round(hb["hi95"][0], 3),
                },
                "future": {
                    "start": _date(ds, fs),
                    "selected": _round(fr.future_forecasts["selected"][g], 3),
                    "forecast": fut_methods,
                    "lo80": _round(fb["lo80"][0], 3),
                    "hi80": _round(fb["hi80"][0], 3),
                    "lo95": _round(fb["lo95"][0], 3),
                    "hi95": _round(fb["hi95"][0], 3),
                },
                "metrics": hold.get(sid, {}),
                "validationMae": {
                    m: val.loc[sid, f"validation_mae_{m}"]
                    for m in METHODS
                    if f"validation_mae_{m}" in val.columns and sid in val.index
                },
            },
        )

    # ---- evaluation tables
    et = ctx["etables"]
    demo_hold = fr.holdout_errors[fr.holdout_errors["series"].isin(ids)]
    demo_by_method = summarise(demo_hold, ["method"])
    demo_by_method["method_label"] = demo_by_method["method"].map(
        lambda m: LABELS.get(m, "Selected per series")
    )
    write_json(
        out / "evaluation.json",
        {
            "params": fr.params,
            "tuning": records(fr.tuning),
            "holdoutModelStores": records(et["holdout_by_method_model_stores"]),
            "holdoutAllStores": records(et["holdout_by_method_all"]),
            "holdoutByCategory": records(et["holdout_by_category_model_stores"]),
            "holdoutByPattern": records(et["holdout_by_pattern_model_stores"]),
            "validationModelStores": records(et["validation_by_method_model_stores"]),
            "coverage": records(et["interval_coverage_model_stores"]),
            "coverageByPattern": records(et["interval_coverage_by_pattern"]),
            "selectionCounts": records(et["selection_counts"]),
            "demoHoldoutByMethod": records(demo_by_method),
        },
    )

    # ---- simulation
    sd = ctx["sim_demo"]
    s0 = W.simulation[0]
    daily = []
    for name in ("basic", "forecast_v1", "forecast"):
        rr = sd[name]["ledger"]
        cost = sd["lines"]["unit_cost"].to_numpy()[:, None]
        val_ = (rr["closing"] * cost).sum(0)
        dem = rr["demand"].sum(0)
        lost = rr["lost"].sum(0)
        for t in range(rr["demand"].shape[1]):
            daily.append(
                {
                    "policy": name,
                    "date": _date(ds, s0 + t),
                    "inventoryValue": round(float(val_[t]), 2),
                    "demand": float(dem[t]),
                    "lost": float(lost[t]),
                }
            )
    write_json(
        out / "simulation.json",
        {
            "window": {
                "start": _date(ds, W.simulation[0]),
                "end": _date(ds, W.simulation[1]),
                "days": W.sim_days,
            },
            "confirmationWindow": {
                "start": _date(ds, ctx["conf"][0]),
                "end": _date(ds, ctx["conf"][1]),
                "days": W.sim_days,
            },
            "policyLabels": POLICY_LABELS,
            "windowLabels": WINDOW_LABELS,
            "summary": records(ctx["sim_summary"]),
            "sensitivity": records(ctx["sim_sens"]),
            "daily": daily,
            "basicPolicy": C.BASIC_POLICY,
        },
    )

    v = ctx["validation"]["summary"]
    write_json(
        out / "manifest.json",
        {
            "source": ctx["source"],
            "sourceLabel": "Walmart M5 sales (local copy)"
            if ctx["source"] == "m5"
            else "Synthetic demo data (not Walmart data)",
            "generatedAt": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "assumptionsVersion": C.ASSUMPTIONS_VERSION,
            "planningDay": ctx["plan_day"],
            "planningDate": _date(ds, ctx["plan_day"]),
            "lastObservedDate": _date(ds, T),
            "holdout": {"start": _date(ds, hs), "end": _date(ds, he)},
            "future": {"start": _date(ds, fs), "end": _date(ds, fe)},
            "simulation": {"start": _date(ds, W.simulation[0]), "end": _date(ds, W.simulation[1])},
            "validation": {
                "series": v["series"],
                "items": v["items"],
                "stores": v["stores"],
                "observedDays": v["observed_days"],
                "firstDate": v["first_date"],
                "lastObservedDate": v["last_observed_date"],
                "errors": v["errors"],
                "warnings": v["warnings"],
            },
            "demo": {
                "lines": int(len(L)),
                "stores": sorted(L["store_id"].unique().tolist()),
                "categories": sorted(L["cat_id"].unique().tolist()),
            },
            "defaults": settings_dict(ctx["settings"]),
            "presets": PRESETS,
            "capacity": ctx["capacity"],
            "financial": {
                "grossMargin": C.FIN.gross_margin,
                "holdingRate": C.FIN.annual_holding_rate,
                "shortageMultiplier": C.FIN.shortage_penalty_multiplier,
            },
        },
    )


def export_csvs(ctx: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rec = ctx["rec"].copy()
    ds = ctx["ds"]
    rec["planning_date"] = _date(ds, ctx["plan_day"])
    rec["expected_receipt_date"] = [
        (_date(ds, int(d)) if d > 0 else "") for d in rec["expected_receipt_day"]
    ]
    rec.to_csv(out / "replenishment_recommendations.csv", index=False)
    ctx["sim_summary"].to_csv(out / "simulation_summary.csv", index=False)
    ctx["sim_sens"].to_csv(out / "simulation_sensitivity.csv", index=False)
    ctx["scen_summary"].to_csv(out / "scenario_summary.csv", index=False)
    L = ctx["lines"]
    L.drop(columns=[c for c in ("history",) if c in L.columns]).to_csv(
        out / "planning_inputs.csv", index=False
    )
    po = pd.concat(
        [ctx["sim_demo"][k]["purchase_orders"] for k in POLICY_LABELS], ignore_index=True
    )
    po.to_csv(out / "simulated_purchase_orders_demo.csv", index=False)
    ids = ctx["sim_demo"]["lines"]["series"].to_numpy()
    led = pd.concat(
        [
            ledger_frame(ctx["sim_demo"][k], ids, ctx["W"].simulation[0], "demo")
            for k in POLICY_LABELS
        ]
    )
    led.to_csv(out / "inventory_ledger_demo.csv", index=False)
    supplier_table().to_csv(out / "suppliers.csv", index=False)
    write_json(
        out / "planning_settings.json",
        {
            "defaults": settings_dict(ctx["settings"]),
            "capacity": ctx["capacity"],
            "planningDate": _date(ds, ctx["plan_day"]),
        },
        indent=2,
    )


def database_tables(ctx: dict) -> dict[str, pd.DataFrame]:
    ds, fr, W = ctx["ds"], ctx["fr"], ctx["W"]
    meta = ds.meta
    t = {}
    t["stores"] = meta[["store_id", "state_id"]].drop_duplicates().reset_index(drop=True)
    t["products"] = meta[["item_id", "dept_id", "cat_id"]].drop_duplicates().reset_index(drop=True)
    cal = ds.calendar.copy()
    t["calendar"] = pd.DataFrame(
        {
            "day": cal["day"],
            "date": pd.to_datetime(cal["date"]).dt.date,
            "wm_yr_wk": cal["wm_yr_wk"],
            "weekday": cal["weekday"],
            "wday": cal["wday"],
            "month": cal["month"],
            "year": cal["year"],
            "event_name_1": cal["event_name_1"],
            "event_type_1": cal["event_type_1"],
            "event_name_2": cal["event_name_2"],
            "event_type_2": cal["event_type_2"],
            "snap_ca": cal["snap_CA"],
            "snap_tx": cal["snap_TX"],
            "snap_wi": cal["snap_WI"],
        }
    )
    cls = ctx["demo"]  # noqa: F841
    from .sampling import classify_for_sampling

    pre = classify_for_sampling(ds, C.DEMO_STORES, W.holdout[0] - 1)
    model_mask = meta["store_id"].isin(C.MODEL_STORES)
    t["series"] = pd.DataFrame(
        {
            "series_id": meta["id"],
            "item_id": meta["item_id"],
            "store_id": meta["store_id"],
            "availability_start_day": ds.availability_start(),
            "pattern": pre["pattern"].astype(str),
            "in_model_scope": model_mask.to_numpy(),
            "in_demo": meta["id"].isin(ctx["demo"]["id"]).to_numpy(),
        }
    )
    sup = supplier_table()
    t["suppliers"] = sup
    ml = ctx["sim_all"]["lines"]
    t["supplier_assumptions"] = pd.DataFrame(
        {
            "series_id": ml["series"],
            "supplier_id": ml["supplier_id"],
            "case_pack": ml["case_pack"],
            "moq_units": ml["moq_units"],
            "unit_price": ml["unit_price"],
            "unit_cost": ml["unit_cost"],
            "gross_margin": ml["gross_margin"],
            "order_cost": ml["order_cost"],
            "lead_time_mean": ml["lead_time_mean"],
            "lead_time_sd": ml["lead_time_sd"],
        }
    )
    led, pos = [], []
    for scope, res in (("demo", ctx["sim_demo"]), ("model_stores", ctx["sim_all"])):
        ids = res["lines"]["series"].to_numpy()
        for k in POLICY_LABELS:
            led.append(ledger_frame(res[k], ids, W.simulation[0], scope))
            po = res[k]["purchase_orders"].copy()
            if len(po):
                po.insert(0, "scope", scope)
                pos.append(po)
    t["inventory_ledger"] = pd.concat(led, ignore_index=True).rename(
        columns={"series": "series_id"}
    )
    t["purchase_orders"] = pd.concat(pos, ignore_index=True).rename(columns={"series": "series_id"})
    # forecasts for model-store series: holdout + future, every method, intervals for 'selected'
    rows = fr.gbm_rows
    ids = meta["id"].to_numpy()[rows]
    frames = []
    for phase, fc, (a, _b) in (
        ("holdout", fr.holdout_forecasts, W.holdout),
        ("future", fr.future_forecasts, W.future),
    ):
        days = np.arange(a, a + C.HORIZON)
        for m in list(METHODS) + ["selected"]:
            f = fc[m][rows]
            ok = np.isfinite(f).all(1)
            df = pd.DataFrame(
                {
                    "series_id": np.repeat(ids[ok], C.HORIZON),
                    "phase": phase,
                    "day": np.tile(days, ok.sum()),
                    "method": m,
                    "forecast": f[ok].reshape(-1),
                }
            )
            if m == "selected":
                b = interval_bounds(f, np.nan_to_num(fr.residual_q["selected"][rows]))
                for k in ("lo80", "hi80", "lo95", "hi95"):
                    df[k] = b[k][ok].reshape(-1)
            else:
                for k in ("lo80", "hi80", "lo95", "hi95"):
                    df[k] = np.nan
            frames.append(df)
    t["forecast_results"] = pd.concat(frames, ignore_index=True)
    v = fr.validation_errors.assign(phase="validation")
    h = fr.holdout_errors.assign(phase="holdout", fold=-1)
    ev = pd.concat([v, h], ignore_index=True)
    t["forecast_evaluation"] = ev.rename(
        columns={"series": "series_id", "n": "n_days", "scale": "mase_scale"}
    )
    rec = ctx["rec"]
    t["replenishment_recommendations"] = rec.rename(columns={"series": "series_id"}).assign(
        coverage_days=lambda d: d["coverage_days"].where(np.isfinite(d["coverage_days"])),
        on_hand=lambda d: d["on_hand"].astype(int),
        on_order=lambda d: d["on_order"].astype(int),
        recommended_qty=lambda d: d["recommended_qty"].astype(int),
        final_qty=lambda d: d["final_qty"].astype(int),
    )
    sl = ctx["scen_long"]
    t["scenario_results"] = sl.rename(columns={"series": "series_id"}).assign(
        final_qty=lambda d: d["final_qty"].astype(int)
    )
    t["simulation_summary"] = ctx["sim_summary"]
    return t


def parity_fixture(ctx: dict, path: Path) -> None:
    """Inputs + expected outputs for the TypeScript engine, generated by the Python reference."""
    L, hist = ctx["lines"], ctx["hist"]
    cases = []
    for key, s in ctx["scenario_defs"].items():
        r = recommend(L, hist, s, ctx["capacity"], ctx["plan_day"])
        cases.append(
            {
                "name": key,
                "settings": _settings_full(s),
                "capacity": ctx["capacity"],
                "planningDay": ctx["plan_day"],
                "lines": line_inputs(L, hist),
                "expected": [
                    {k: clean(v) for k, v in row.items()}
                    for row in r[["series"] + PARITY_FIELDS].to_dict("records")
                ],
            }
        )
    cases.append(_edge_case())
    write_json(path, {"generatedBy": "inventoryiq.exports.parity_fixture", "cases": cases})


def _settings_full(s) -> dict:
    return settings_dict(s)


def _edge_case() -> dict:
    """Hand-built boundary lines: zero stock, zero demand, extreme lead time, in-transit, MOQ, capacity."""
    from .inventory.policy import Settings

    rows = [
        # id, mu, sigma, lt, ltsd, on_hand, on_order, moq, case, cost, price, order_cost, intermittent, supplier
        ("EDGE_zero_stock", 4.0, 2.0, 5, 1.0, 0, 0, 12, 12, 2.0, 3.0, 6.0, False, "SUP-01"),
        ("EDGE_zero_demand", 0.0, 0.0, 5, 1.0, 10, 0, 6, 6, 2.0, 3.0, 6.0, False, "SUP-01"),
        ("EDGE_long_lead", 2.0, 1.5, 45, 10.0, 20, 0, 4, 4, 5.0, 8.0, 9.0, False, "SUP-04"),
        ("EDGE_in_transit", 3.0, 1.0, 6, 1.5, 5, 60, 6, 6, 1.0, 1.5, 6.0, False, "SUP-02"),
        ("EDGE_moq", 0.3, 0.6, 7, 2.0, 0, 0, 24, 12, 3.0, 5.0, 7.0, False, "SUP-05"),
        ("EDGE_high_demand", 120.0, 40.0, 3, 0.8, 50, 0, 12, 12, 1.5, 2.2, 4.0, False, "SUP-03"),
        ("EDGE_capacity_a", 10.0, 3.0, 3, 0.8, 0, 0, 12, 12, 1.0, 1.4, 4.0, False, "SUP-03"),
        ("EDGE_capacity_b", 10.0, 3.0, 3, 0.8, 5, 0, 12, 12, 1.0, 1.4, 4.0, False, "SUP-03"),
        ("EDGE_intermittent", 0.2, 0.9, 10, 3.5, 1, 0, 2, 2, 6.0, 10.0, 8.0, True, "SUP-06"),
    ]
    L = pd.DataFrame(
        rows,
        columns=[
            "series",
            "mu",
            "sigma",
            "lead_time_mean",
            "lead_time_sd",
            "on_hand",
            "on_order",
            "moq_units",
            "case_pack",
            "unit_cost",
            "unit_price",
            "order_cost",
            "intermittent",
            "supplier_id",
        ],
    )
    for c in ("item_id", "store_id", "dept_id", "cat_id"):
        L[c] = "EDGE"
    rng = np.random.default_rng(1)
    hist = np.zeros((len(L), 364))
    hist[-1] = (rng.random(364) < 0.1) * rng.integers(1, 6, 364)
    hist[1] = 0
    hist[0, :] = 4
    s = Settings(service_level=0.97, review_period=7, budget=150.0)
    cap = {
        "SUP-01": 1000.0,
        "SUP-02": 1000.0,
        "SUP-03": 60.0,
        "SUP-04": 1000.0,
        "SUP-05": 1000.0,
        "SUP-06": 1000.0,
    }
    r = recommend(L, hist, s, cap, 100)
    _ = line_arrays(L)
    return {
        "name": "edge_cases",
        "settings": settings_dict(s),
        "capacity": cap,
        "planningDay": 100,
        "lines": line_inputs(L, hist),
        "expected": [
            {k: clean(v) for k, v in row.items()}
            for row in r[["series"] + PARITY_FIELDS].to_dict("records")
        ],
    }
