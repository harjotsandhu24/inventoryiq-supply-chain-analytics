"""Forecasting stage: tuning, rolling-origin validation, selection, holdout, future forecasts."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HORIZON, Windows
from .data_io import Dataset
from .forecasting import gbm
from .forecasting.backtest import (
    LABELS,
    METHODS,
    BaselineEngine,
    coverage,
    evaluable,
    interval_bounds,
    residual_quantiles,
    residual_rmse,
    run_backtest,
    select_methods,
    tune_baselines,
)
from .forecasting.metrics import mase_scale, summarise, window_errors

log = logging.getLogger(__name__)


@dataclass
class ForecastResults:
    params: dict
    tuning: pd.DataFrame
    validation_errors: pd.DataFrame  # long, all scope series, all methods
    selection: pd.DataFrame  # per series (full scope)
    holdout_errors: pd.DataFrame  # long, per series x method (incl. 'selected')
    holdout_forecasts: dict[str, np.ndarray]  # method -> (n, 28)
    future_forecasts: dict[str, np.ndarray]  # method -> (n, 28)
    residual_q: dict[str, np.ndarray]  # method -> (n, 4)
    sigma: dict[str, np.ndarray]  # method -> (n,) validation RMSE
    coverage: pd.DataFrame
    gbm_rows: np.ndarray  # indices of series covered by GBM
    timings: dict = field(default_factory=dict)
    cube: gbm.FeatureCube | None = None  # GBM feature arrays for the model-store subset


def gbm_predictions(
    cube: gbm.FeatureCube,
    origins: list[int],
    n: int,
    cache_dir: Path,
    tag: str,
    extra_days: dict[int, np.ndarray] | None = None,
) -> dict[int, np.ndarray]:
    """Fit one model per origin and predict the following 28 days (or ``extra_days``)."""
    out = {}
    for origin in origins:
        days = (
            extra_days[origin]
            if extra_days and origin in extra_days
            else np.arange(origin + 1, origin + HORIZON + 1)
        )
        path = cache_dir / f"gbm_{tag}_{origin}_{days[0]}_{days[-1]}.npy"
        if path.exists():
            out[origin] = np.load(path)
            continue
        t0 = time.time()
        model = gbm.fit(cube, origin)
        pred = gbm.predict(cube, model, days, n)
        np.save(path, pred)
        log.info("GBM origin d_%d fitted+predicted in %.0fs", origin, time.time() - t0)
        out[origin] = pred
    return out


def run_forecasting(
    ds: Dataset, windows: Windows, gbm_mask: np.ndarray, cache_dir: Path, tag: str
) -> ForecastResults:
    cache_dir.mkdir(parents=True, exist_ok=True)
    timings = {}
    ids = ds.meta["id"].to_numpy()
    n = ds.n_series
    T = ds.last_day
    t0 = time.time()
    engine = BaselineEngine(ds.sales, ds.available, T)
    timings["baseline_engine_s"] = time.time() - t0
    folds = windows.validation_folds
    tuned = tune_baselines(engine, ds.sales, ds.available, folds)
    params = tuned["params"]
    log.info("tuned baseline parameters: %s", params)

    gbm_rows = np.flatnonzero(gbm_mask)
    t0 = time.time()
    sub = ds.subset(gbm_mask)
    cube = gbm.FeatureCube(sub, T)
    timings["gbm_features_s"] = time.time() - t0
    t0 = time.time()
    val_origins = [s - 1 for s, _ in folds]
    gpred = gbm_predictions(cube, val_origins, len(gbm_rows), cache_dir, tag)
    timings["gbm_validation_s"] = time.time() - t0
    gbm_fold = {k: gpred[o] for k, o in enumerate(val_origins)}
    val_err, residuals = run_backtest(
        ds.sales, ds.available, ids, folds, engine, params, gbm_fold, gbm_rows
    )
    selection = select_methods(val_err)
    selection = pd.DataFrame({"series": ids}).merge(selection, on="series", how="left")
    sel = selection["selected_method"].fillna("moving_average").to_numpy()

    # ---- holdout: models refit / recomputed with data through the day before the holdout
    hs, he = windows.holdout
    t0 = time.time()
    g_hold = gbm_predictions(cube, [hs - 1], len(gbm_rows), cache_dir, tag)[hs - 1]
    g_future = gbm_predictions(cube, [T], len(gbm_rows), cache_dir, tag)[T]
    timings["gbm_holdout_future_s"] = time.time() - t0
    hold_fc, fut_fc = {}, {}
    for m in METHODS[:-1]:
        hold_fc[m] = np.clip(engine.forecast(m, hs - 1, params.get(m)), 0, None)
        fut_fc[m] = np.clip(engine.forecast(m, T, params.get(m)), 0, None)
    hold_fc["gbm"] = np.full((n, HORIZON), np.nan)
    hold_fc["gbm"][gbm_rows] = g_hold
    fut_fc["gbm"] = np.full((n, HORIZON), np.nan)
    fut_fc["gbm"][gbm_rows] = g_future
    pick = {m: sel == m for m in METHODS}
    hold_fc["selected"] = np.zeros((n, HORIZON))
    fut_fc["selected"] = np.zeros((n, HORIZON))
    for m in METHODS:
        hold_fc["selected"][pick[m]] = hold_fc[m][pick[m]]
        fut_fc["selected"][pick[m]] = fut_fc[m][pick[m]]
    # The future window extends beyond observed sales; mask days the item is not listed.
    fut_listed = (
        ds.available[:, T : T + HORIZON]
        if ds.available.shape[1] >= T + HORIZON
        else np.ones((n, HORIZON), bool)
    )
    for m in fut_fc:
        fut_fc[m] = np.where(fut_listed, fut_fc[m], 0.0)

    ok = evaluable(ds.available, hs, he)
    act = ds.sales[:, hs - 1 : he].astype(float)
    listed = ds.available[:, hs - 1 : he] & ok[:, None]
    scale = mase_scale(ds.sales, ds.available, hs - 1)
    rows = []
    for m, fc in hold_fc.items():
        lm = listed & np.isfinite(fc)
        e = pd.DataFrame(window_errors(act, np.nan_to_num(fc), lm))
        e.insert(0, "series", ids)
        e.insert(1, "method", m)
        e["scale"] = scale
        rows.append(e[e["n"] > 0])
    hold_err = pd.concat(rows, ignore_index=True)

    # ---- intervals from validation residuals; coverage measured on the holdout
    rq = {m: residual_quantiles(residuals[m]) for m in METHODS}
    sig = {m: residual_rmse(residuals[m]) for m in METHODS}
    rq["selected"] = np.zeros((n, 4))
    sig["selected"] = np.zeros(n)
    for m in METHODS:
        rq["selected"][pick[m]] = rq[m][pick[m]]
        sig["selected"][pick[m]] = sig[m][pick[m]]
    cov_rows = []
    for m in list(METHODS) + ["selected"]:
        b = interval_bounds(np.nan_to_num(hold_fc[m]), np.nan_to_num(rq[m]))
        lm = listed & np.isfinite(hold_fc[m]) & np.isfinite(rq[m]).all(1)[:, None]
        c = coverage(act, b, lm)
        cov_rows.append(pd.DataFrame({"series": ids, "method": m, **c}))
    cov = pd.concat(cov_rows, ignore_index=True)
    cov = cov[cov["n"] > 0]
    return ForecastResults(
        params=params,
        tuning=pd.DataFrame(tuned["table"]),
        validation_errors=val_err,
        selection=selection,
        holdout_errors=hold_err,
        holdout_forecasts=hold_fc,
        future_forecasts=fut_fc,
        residual_q=rq,
        sigma=sig,
        coverage=cov,
        gbm_rows=gbm_rows,
        timings=timings,
        cube=cube,
    )


def evaluation_tables(
    fr: ForecastResults, meta: pd.DataFrame, classes: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Aggregate accuracy tables for reporting."""
    attrs = (
        meta[["id", "store_id", "cat_id", "dept_id"]]
        .rename(columns={"id": "series"})
        .merge(classes[["series", "pattern", "volume_tier"]], on="series", how="left")
    )
    gset = set(meta["id"].to_numpy()[fr.gbm_rows])
    out = {}
    v = fr.validation_errors.merge(attrs, on="series")
    h = fr.holdout_errors.merge(attrs, on="series")
    for name, df in (("validation", v), ("holdout", h)):
        df = df.copy()
        df["scope"] = np.where(df["series"].isin(gset), "model_stores", "other_stores")
        out[f"{name}_by_method_all"] = summarise(df[df["method"] != "gbm"], ["method"])
        ms = df[df["scope"] == "model_stores"]
        out[f"{name}_by_method_model_stores"] = summarise(ms, ["method"])
        out[f"{name}_by_category_model_stores"] = summarise(ms, ["method", "cat_id"])
        out[f"{name}_by_pattern_model_stores"] = summarise(ms, ["method", "pattern"])
    cov = fr.coverage.merge(attrs, on="series")
    cov["scope"] = np.where(cov["series"].isin(gset), "model_stores", "other_stores")

    def cov_agg(g):
        return pd.Series(
            {
                "days": int(g["n"].sum()),
                "coverage80": g["covered80"].sum() / g["n"].sum(),
                "coverage95": g["covered95"].sum() / g["n"].sum(),
            }
        )

    out["interval_coverage_model_stores"] = (
        cov[cov["scope"] == "model_stores"]
        .groupby("method")
        .apply(cov_agg, include_groups=False)
        .reset_index()
    )
    out["interval_coverage_by_pattern"] = (
        cov[(cov["scope"] == "model_stores") & (cov["method"] == "selected")]
        .groupby("pattern")
        .apply(cov_agg, include_groups=False)
        .reset_index()
    )
    sel = fr.selection.merge(attrs, on="series")
    sel["scope"] = np.where(sel["series"].isin(gset), "model_stores", "other_stores")
    out["selection_counts"] = (
        sel.groupby(["scope", "selected_method"]).size().rename("series").reset_index()
    )
    for _k, df in out.items():
        if "method" in df.columns:
            df["method_label"] = df["method"].map(lambda m: LABELS.get(m, "Selected per series"))
    return out
