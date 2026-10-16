"""End-to-end pipeline: validate -> sample -> forecast -> simulate -> plan -> export.

Usage:
    python -m inventoryiq.pipeline --source m5          # licensed files in data/raw
    python -m inventoryiq.pipeline --source synthetic   # generated demo data (CI)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .data_io import load_dataset
from .database import build as build_database
from .forecast_stage import evaluation_tables, run_forecasting
from .inventory.policy import Settings
from .planning import PRESETS, recommend, summarise_recommendations
from .sampling import classify_for_sampling, sampling_summary, select_demo_series
from .segmentation import abc_class, demand_stats, sbc_class, xyz_class
from .sim_stage import INTERMITTENT, build_sim_forecasts, run_policies
from .suppliers import line_master
from .util import records, write_json
from .validate import run_validation

log = logging.getLogger("inventoryiq")


def paths_for(source: str) -> dict[str, Path]:
    return {
        "src": C.RAW_DIR if source == "m5" else C.SYNTHETIC_DIR,
        "processed": C.PROCESSED_DIR / source,
        "reports": C.REPORTS_DIR / source,
        "deliverables": C.DELIVERABLES_DIR / source,
        "cache": C.PROCESSED_DIR / source / "cache",
    }


def run(
    source: str,
    skip_db: bool = False,
    skip_excel: bool = False,
    app_dir: Path | None = None,
    update_fixtures: bool = False,
) -> dict:
    t_start = time.time()
    P = paths_for(source)
    if source == "synthetic" and not (P["src"] / "calendar.csv").exists():
        from .synthetic import generate

        generate(P["src"])
    for p in (P["processed"], P["reports"], P["deliverables"], P["cache"]):
        p.mkdir(parents=True, exist_ok=True)

    # ---- 1. load + validate -------------------------------------------------------------
    log.info("loading %s data from %s", source, P["src"])
    ds = load_dataset(P["src"], source)
    W = C.Windows(ds.last_day)
    validation = run_validation(P["src"], ds, W, P["reports"])
    log.info(
        "validation: %s errors, %s warnings",
        validation["summary"]["errors"],
        validation["summary"]["warnings"],
    )

    # ---- 2. demo scope (pre-holdout information only) ------------------------------------
    hold0 = W.holdout[0]
    cls_pre = classify_for_sampling(ds, C.DEMO_STORES, hold0 - 1)
    per_store = C.DEMO_ITEMS_PER_STORE if source == "m5" else 40
    demo = select_demo_series(cls_pre, per_store, C.RANDOM_SEED)
    samp = sampling_summary(cls_pre, demo)
    samp.to_csv(P["reports"] / "demo_sampling_summary.csv", index=False)
    excl = (
        cls_pre[cls_pre["store_id"].isin(C.DEMO_STORES)]["exclusion_reason"]
        .replace("", "eligible")
        .value_counts()
    )
    log.info("demo scope: %d series", len(demo))

    # ---- 3. forecasting ------------------------------------------------------------------
    model_mask = ds.meta["store_id"].isin(C.MODEL_STORES).to_numpy()
    fr = run_forecasting(ds, W, model_mask, P["cache"], source)
    classes = cls_pre.rename(columns={"id": "series"})
    etables = evaluation_tables(fr, ds.meta, classes)
    for k, df in etables.items():
        df.to_csv(P["reports"] / f"forecast_{k}.csv", index=False)
    log.info("forecasting done")

    # ---- 4. simulation (model-store subset) -----------------------------------------------
    ms_idx = np.flatnonzero(model_mask)
    ms = ds.subset(model_mask)
    sf = build_sim_forecasts(ms, W, fr.cube, P["cache"], source)
    lines_ms = line_master(ms, W.simulation[0] - 1)
    ms_pos = {s: k for k, s in enumerate(ms.meta["id"])}
    demo_rows = np.array([ms_pos[s] for s in demo["id"]])
    settings = Settings(
        service_level=0.95,
        review_period=7,
        holding_rate=C.FIN.annual_holding_rate,
        shortage_multiplier=C.FIN.shortage_penalty_multiplier,
    )
    sim_demo = run_policies(ms, W, lines_ms, sf, demo_rows, settings, "demo")
    sim_all = run_policies(ms, W, lines_ms, sf, np.arange(ms.n_series), settings, "model_stores")
    # Out-of-sample confirmation window for the v2 policy revision (see docs/methodology.md)
    conf = W.confirmation
    sf_conf = build_sim_forecasts(ms, W, fr.cube, P["cache"], source, window=conf)
    lines_conf = line_master(ms, conf[0] - 1)
    conf_demo = run_policies(
        ms, W, lines_conf, sf_conf, demo_rows, settings, "demo", conf, "confirmation"
    )
    conf_all = run_policies(
        ms,
        W,
        lines_conf,
        sf_conf,
        np.arange(ms.n_series),
        settings,
        "model_stores",
        conf,
        "confirmation",
    )
    sim_summary = pd.concat(
        [r["summary"] for r in (sim_demo, sim_all, conf_demo, conf_all)], ignore_index=True
    )
    sim_sens = pd.concat(
        [r["sensitivity"] for r in (sim_demo, sim_all, conf_demo, conf_all)], ignore_index=True
    )
    sim_summary.to_csv(P["reports"] / "simulation_summary.csv", index=False)
    sim_sens.to_csv(P["reports"] / "simulation_sensitivity.csv", index=False)
    log.info("simulation done")

    # ---- 5. planning snapshot (end of the last observed day) -------------------------------
    T = ds.last_day
    plan_day = T + 1
    gidx = ms_idx[demo_rows]  # indices into ds
    stats_now = demand_stats(ds.sales, ds.price, ds.available, T - 363, T)
    st_demo = stats_now.iloc[gidx].reset_index(drop=True)
    L = sim_demo["lines"].copy()
    L["mu"] = fr.future_forecasts["selected"][gidx].mean(1)
    L["sigma"] = np.nan_to_num(fr.sigma["selected"][gidx])
    sel = fr.selection.set_index("series").loc[L["series"]]
    L["method"] = sel["selected_method"].fillna("moving_average").to_numpy()
    L["pattern"] = sbc_class(st_demo["adi"], st_demo["cv2"])
    L["intermittent"] = np.isin(L["pattern"], INTERMITTENT)
    L["abc"] = abc_class(st_demo["sales_value"].to_numpy())
    L["xyz"] = xyz_class(st_demo["weekly_cv"].to_numpy())
    L["weekly_cv"] = st_demo["weekly_cv"].to_numpy()
    hold = fr.holdout_errors.set_index(["series", "method"])
    for m, col in (("selected", "holdout_wape_selected"), ("seasonal_naive", "holdout_wape_naive")):
        h = hold.xs(m, level="method").reindex(L["series"])
        L[col] = np.where(
            h["actual"] > 0, h["abs_err"] / h["actual"].where(h["actual"] > 0), np.nan
        )
    h = hold.xs("selected", level="method").reindex(L["series"])
    L["holdout_mae_selected"] = (h["abs_err"] / h["n"]).to_numpy()
    L["forecast_28d_total"] = fr.future_forecasts["selected"][gidx].sum(1)
    L["units_364"] = st_demo["units"].to_numpy()
    L["sales_value_364"] = st_demo["sales_value"].to_numpy()
    L["on_hand"] = sim_demo["basic"]["final_on_hand"]
    L["on_order"] = sim_demo["basic"]["final_on_order"]
    hist = np.where(ds.available[gidx, T - 364 : T], ds.sales[gidx, T - 364 : T], np.nan).astype(
        float
    )
    capacity = sim_demo["capacity"]
    rec = recommend(L, hist, settings, capacity, plan_day)
    rec["abc"] = L["abc"].to_numpy()
    rec["xyz"] = L["xyz"].to_numpy()
    rec["planning_day"] = plan_day
    balanced_spend = float(rec["order_value"].sum())
    scenario_defs = {}
    for key, pr in PRESETS.items():
        budget = (
            None if pr["budget_share"] is None else round(balanced_spend * pr["budget_share"], 2)
        )
        scenario_defs[key] = replace(
            settings,
            service_level=pr["service_level"],
            review_period=pr["review_period"],
            lead_time_shift=pr["lead_time_shift"],
            lead_time_sd_multiplier=pr["lead_time_sd_multiplier"],
            budget=budget,
        )
    extra = {
        "lead_time_plus_5": replace(settings, lead_time_shift=5.0),
        "variability_x2": replace(settings, lead_time_sd_multiplier=2.0),
        "review_14": replace(settings, review_period=14),
        "zero_budget": replace(settings, budget=0.0),
        "csl_80": replace(settings, service_level=0.80),
    }
    scen_frames, scen_summary = [], []
    for key, s in {**scenario_defs, **extra}.items():
        r = recommend(L, hist, s, capacity, plan_day)
        summ = summarise_recommendations(r)
        summ.update(
            {
                "scenario_id": key,
                "service_level": s.service_level,
                "review_period": s.review_period,
                "lead_time_shift": s.lead_time_shift,
                "lead_time_sd_mult": s.lead_time_sd_multiplier,
                "budget": s.budget,
            }
        )
        scen_summary.append(summ)
        scen_frames.append(
            r.assign(
                scenario_id=key,
                service_level=s.service_level,
                review_period=s.review_period,
                lead_time_shift=s.lead_time_shift,
                lead_time_sd_mult=s.lead_time_sd_multiplier,
                budget=s.budget,
            )
        )
    scen_long = pd.concat(scen_frames, ignore_index=True)
    scen_summary = pd.DataFrame(scen_summary)
    scen_summary.to_csv(P["reports"] / "scenario_summary.csv", index=False)
    log.info("planning snapshot done: %s", summarise_recommendations(rec))

    # ---- 6. exports ------------------------------------------------------------------------
    from .exports import export_app, export_csvs, parity_fixture

    ctx = dict(
        source=source,
        ds=ds,
        W=W,
        validation=validation,
        demo=demo,
        samp=samp,
        excl=excl,
        fr=fr,
        etables=etables,
        lines=L,
        rec=rec,
        hist=hist,
        capacity=capacity,
        settings=settings,
        sim_demo=sim_demo,
        sim_all=sim_all,
        sim_summary=sim_summary,
        sim_sens=sim_sens,
        scen_summary=scen_summary,
        scen_long=scen_long,
        scenario_defs={**scenario_defs, **extra},
        gidx=gidx,
        plan_day=plan_day,
        sf=sf,
        ms=ms,
        demo_rows=demo_rows,
        conf=conf,
    )
    # Only the licensed M5 run writes the live app data; synthetic runs never overwrite it.
    if app_dir is not None:
        app_out = app_dir
    elif source == "m5":
        app_out = C.APP_DATA_DIR
    else:
        app_out = P["processed"] / "app-data"
    export_app(ctx, app_out)
    export_csvs(ctx, P["deliverables"] / "csv")
    parity_fixture(ctx, P["processed"] / "parity_cases.json")
    if source == "synthetic" and update_fixtures:
        fixture = C.ROOT / "app" / "fixtures" / "demo-data"
        if fixture.exists():
            shutil.rmtree(fixture)
        shutil.copytree(app_out, fixture)
        shutil.copy(
            P["processed"] / "parity_cases.json", C.ROOT / "app" / "fixtures" / "parity_cases.json"
        )

    integrity = None
    if not skip_db:
        from .exports import database_tables

        tables = database_tables(ctx)
        integrity = build_database(P["processed"] / "inventoryiq.duckdb", P["src"], tables)
        bad = [r for r in integrity if r[1] != 0]
        (P["reports"] / "integrity_checks.json").write_text(
            json.dumps([{"check": a, "violations": int(b)} for a, b in integrity], indent=2)
        )
        if bad:
            raise RuntimeError(f"integrity checks failed: {bad}")
        log.info("database built; %d integrity checks passed", len(integrity))
    if not skip_excel:
        from .excel_workbook import build_workbook

        build_workbook(ctx, P["deliverables"] / "InventoryIQ_Analysis.xlsx")
        log.info("excel workbook written")

    summary = {
        "source": source,
        "seconds": round(time.time() - t_start, 1),
        "validation": validation["summary"],
        "baseline_params": fr.params,
        "timings": fr.timings,
        "planning": summarise_recommendations(rec),
        "simulation": records(sim_summary),
        "integrity_checks": None if integrity is None else len(integrity),
    }
    write_json(P["reports"] / "run_summary.json", summary, indent=2)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="InventoryIQ pipeline")
    ap.add_argument("--source", choices=["m5", "synthetic"], default="m5")
    ap.add_argument("--skip-db", action="store_true")
    ap.add_argument("--skip-excel", action="store_true")
    ap.add_argument(
        "--update-fixtures",
        action="store_true",
        help="copy synthetic outputs into app/fixtures (committed demo data)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = run(args.source, args.skip_db, args.skip_excel, update_fixtures=args.update_fixtures)
    print(json.dumps({k: s[k] for k in ("source", "seconds", "planning")}, indent=2))


if __name__ == "__main__":
    main()
