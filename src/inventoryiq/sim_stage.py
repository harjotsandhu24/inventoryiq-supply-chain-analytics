"""Historical policy simulation and the planning snapshot used by the application."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BASIC_POLICY, FIN, HORIZON, RANDOM_SEED, Windows
from .data_io import Dataset
from .forecast_stage import gbm_predictions
from .forecasting import gbm
from .forecasting.backtest import (
    METHODS,
    BaselineEngine,
    residual_rmse,
    run_backtest,
    select_methods,
    tune_baselines,
)
from .inventory import simulation as sim
from .inventory.policy import Settings
from .segmentation import demand_stats, sbc_class
from .suppliers import supplier_capacity, supplier_table

log = logging.getLogger(__name__)
INTERMITTENT = ("intermittent", "lumpy")


@dataclass
class SimForecasts:
    """Forecast inputs for the simulation, built only from data before the simulation start."""

    selection: pd.DataFrame
    params: dict
    sigma: np.ndarray
    mu_by_day: np.ndarray  # (n, sim_days) mean 28-day forecast made at the end of each sim day
    intermittent: np.ndarray


def build_sim_forecasts(
    ds: Dataset,
    windows: Windows,
    cube: gbm.FeatureCube,
    cache_dir: Path,
    tag: str,
    window: tuple[int, int] | None = None,
) -> SimForecasts:
    s0, s1 = window or windows.simulation
    folds = windows.selection_folds_before(s0)
    ids = ds.meta["id"].to_numpy()
    n = ds.n_series
    engine = BaselineEngine(ds.sales, ds.available, ds.last_day)
    tuned = tune_baselines(engine, ds.sales, ds.available, folds)
    params = tuned["params"]
    origins = [s - 1 for s, _ in folds]
    gp = gbm_predictions(cube, origins, n, cache_dir, tag + "_simsel")
    errs, resid = run_backtest(
        ds.sales,
        ds.available,
        ids,
        folds,
        engine,
        params,
        {k: gp[o] for k, o in enumerate(origins)},
        np.arange(n),
    )
    selection = pd.DataFrame({"series": ids}).merge(select_methods(errs), on="series", how="left")
    sel = selection["selected_method"].fillna("moving_average").to_numpy()
    sigma = np.zeros(n)
    rm = {m: residual_rmse(resid[m]) for m in METHODS}
    for m in METHODS:
        sigma[sel == m] = rm[m][sel == m]
    sigma = np.nan_to_num(sigma)
    # GBM trained once on data through the day before the simulation; predicts every later day.
    days = np.arange(s0, min(s1 + HORIZON, ds.n_calendar_days) + 1)
    g = gbm_predictions(cube, [s0 - 1], n, cache_dir, tag + "_sim", extra_days={s0 - 1: days})[
        s0 - 1
    ]
    n_days = s1 - s0 + 1
    mu = np.zeros((n, n_days))
    for t in range(n_days):
        origin = s0 + t  # forecast made at the end of this day
        for m in METHODS[:-1]:
            rows = sel == m
            if rows.any():
                mu[rows, t] = engine.forecast(m, origin, params.get(m))[rows].mean(1)
        rows = sel == "gbm"
        if rows.any():
            lo = origin + 1 - s0
            mu[rows, t] = g[rows, lo : lo + HORIZON].mean(1)
    st = demand_stats(ds.sales, ds.price, ds.available, s0 - 364, s0 - 1)
    inter = np.isin(sbc_class(st["adi"], st["cv2"]), INTERMITTENT)
    return SimForecasts(selection, params, sigma, np.clip(mu, 0, None), inter)


POLICY_LABELS = {
    "basic": "Basic min/max rule (status quo)",
    "forecast_v1": "Forecast policy v1 (pre-specified)",
    "forecast": "Forecast policy v2 (28-day lot cap, revised after v1)",
}
# Evidence status of each simulation window (see docs/methodology.md, section 6)
WINDOW_LABELS = {
    "main": "Development window: v1 tested as pre-specified; v2 designed after seeing it (not independent)",
    "confirmation": "Confirmation window: excluded from the v2 redesign and evaluated once",
}


def run_policies(
    ds: Dataset,
    windows: Windows,
    lines: pd.DataFrame,
    sf: SimForecasts,
    rows: np.ndarray,
    settings: Settings,
    scope: str,
    window: tuple[int, int] | None = None,
    window_name: str = "main",
) -> dict:
    """Simulate the basic, v1 and v2 policies for the series in ``rows`` over ``window``."""
    s0, s1 = window or windows.simulation
    n_days = s1 - s0 + 1
    L = lines.iloc[rows].reset_index(drop=True)
    ids = L["series"].to_numpy()
    sales = ds.sales[rows]
    listed = ds.available[rows, : ds.last_day]
    demand = np.where(listed[:, s0 - 1 : s1], sales[:, s0 - 1 : s1], 0)
    hist_lo = s0 - 1 - 364
    history = sales[:, hist_lo:s1].astype(float)
    hist_listed = listed[:, hist_lo:s1]
    # Reviews every R days, aligned so that the final review falls on the day after the window
    review_cols = np.array(
        [t for t in range(n_days) if (s0 + t - s1) % settings.review_period == 0 and s0 + t < s1]
    )
    pre = ds.sales[rows, s0 - 29 : s0 - 1]
    pre_l = listed[:, s0 - 29 : s0 - 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        a28 = np.where(pre_l.sum(1) > 0, (pre * pre_l).sum(1) / pre_l.sum(1), 0.0)
    case = L["case_pack"].to_numpy(float)
    init = (
        np.ceil(
            np.round(
                a28 * (L["lead_time_mean"].to_numpy(float) + settings.review_period + 7) / case, 6
            )
        )
        * case
    )
    cap = supplier_capacity(L, settings.review_period)
    draws = sim.draw_lead_times(
        supplier_table(), n_days, RANDOM_SEED if window_name == "main" else RANDOM_SEED + s0
    )
    inputs = sim.SimInputs(ids, demand, s0, L, cap, draws, init, review_cols)
    mu_by_review = {int(t): sf.mu_by_day[rows, t] for t in review_cols}
    results = {
        "basic": sim.run(
            inputs, sim.basic_policy_factory(inputs, history, hist_listed, BASIC_POLICY), "basic"
        )
    }
    for name, st in (
        ("forecast_v1", replace(settings, max_cycle_days=None)),
        ("forecast", settings),
    ):
        pol = sim.forecast_policy_factory(
            inputs, mu_by_review, sf.sigma[rows], sf.intermittent[rows], history, hist_listed, st
        )
        results[name] = sim.run(inputs, pol, name)
    summaries = [
        sim.summarise(r, L, review_cols, FIN.annual_holding_rate, FIN.shortage_penalty_multiplier)
        for r in results.values()
    ]
    for s in summaries:
        s["scope"] = scope
        s["window"] = window_name
        s["window_start_day"] = s0
        s["window_end_day"] = s1
        s["policy_label"] = POLICY_LABELS[s["policy"]]
    # Accounting sensitivity: decisions held fixed, cost assumptions varied.
    sens = []
    base_margin = L["gross_margin"].to_numpy(float)
    for dm in (-0.10, 0.0, 0.10):
        for mult in (0.5, 1.0, 1.5, 2.0, 3.0):
            for oc in (0.25, 0.5, 1.0):
                for r in results.values():
                    Lm = L.copy()
                    Lm["unit_cost"] = np.round(Lm["unit_price"] * (1 - (base_margin + dm)), 2)
                    Lm["order_cost"] = Lm["order_cost"] * oc
                    s = sim.summarise(r, Lm, review_cols, FIN.annual_holding_rate, mult)
                    sens.append(
                        {
                            "scope": scope,
                            "window": window_name,
                            "policy": r["name"],
                            "margin_shift": dm,
                            "shortage_multiplier": mult,
                            "order_cost_multiplier": oc,
                            "holding_cost": s["holding_cost"],
                            "ordering_cost": s["ordering_cost"],
                            "shortage_penalty": s["shortage_penalty"],
                            "modeled_total_cost": s["modeled_total_cost"],
                            "purchasing_spend": s["purchasing_spend"],
                        }
                    )
    return {
        **results,
        "summary": pd.DataFrame(summaries),
        "sensitivity": pd.DataFrame(sens),
        "lines": L,
        "review_cols": review_cols,
        "capacity": cap,
        "initial_on_hand": init,
        "lead_time_draws": draws,
        "window": (s0, s1),
    }


LEDGER_FIELDS = (
    "opening",
    "receipts",
    "demand",
    "fulfilled",
    "lost",
    "closing",
    "on_order",
    "ordered",
)


def ledger_frame(result: dict, ids: np.ndarray, start_day: int, scope: str) -> pd.DataFrame:
    """Long inventory ledger: one row per policy x series x simulated day."""
    rec = result["ledger"]
    n, days = rec["demand"].shape
    df = pd.DataFrame(
        {
            "scope": scope,
            "policy": result["name"],
            "series": np.repeat(ids, days),
            "day": np.tile(np.arange(start_day, start_day + days), n),
        }
    )
    for k in LEDGER_FIELDS:
        df[k] = rec[k].reshape(-1).astype(np.int64)
    return df
