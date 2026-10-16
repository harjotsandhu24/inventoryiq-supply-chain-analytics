"""Rolling-origin backtesting, parameter tuning, model selection, and residual intervals."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..config import HORIZON
from . import baselines as bl
from .metrics import mase_scale, safe_ratio, window_errors

log = logging.getLogger(__name__)

METHODS = ["seasonal_naive", "moving_average", "seasonal_ma", "sba", "gbm"]
SIMPLICITY = {m: k for k, m in enumerate(METHODS)}
GBM_MIN_IMPROVEMENT = 0.02  # GBM must beat the best baseline's validation MAE by 2% to be selected
INTERVAL_LEVELS = (0.025, 0.10, 0.90, 0.975)
LABELS = {
    "seasonal_naive": "Seasonal naive",
    "moving_average": "Moving average",
    "seasonal_ma": "Seasonal moving average",
    "sba": "Croston-SBA",
    "gbm": "Gradient boosting",
}


class BaselineEngine:
    """Baseline forecasts for any origin using only data up to that origin."""

    def __init__(
        self, sales: np.ndarray, available: np.ndarray, last_day: int, sba_alphas=bl.SBA_ALPHAS
    ):
        self.hist = bl.History.build(sales, available, last_day)
        self.sba_paths = {a: bl.sba_path(self.hist, a).astype(np.float32) for a in sba_alphas}

    def forecast(self, method: str, origin: int, param) -> np.ndarray:
        if method == "seasonal_naive":
            return bl.seasonal_naive(self.hist, origin)
        if method == "moving_average":
            return bl.moving_average(self.hist, origin, param)
        if method == "seasonal_ma":
            return bl.seasonal_moving_average(self.hist, origin, param)
        if method == "sba":
            return bl.sba(self.sba_paths[param], origin).astype(np.float64)
        raise ValueError(method)


def _error_rows(ids, fold_id, method, actual, fc, listed, scale):
    e = window_errors(actual, fc, listed)
    df = pd.DataFrame(e)
    df.insert(0, "series", ids)
    df.insert(1, "fold", fold_id)
    df.insert(2, "method", method)
    df["scale"] = scale
    return df


def evaluable(available: np.ndarray, start: int, end: int, min_history: int = 56) -> np.ndarray:
    """Series listed on every day of the window with at least ``min_history`` listed days before it."""
    hist_ok = available[:, : start - 1].sum(1) >= min_history
    return hist_ok & available[:, start - 1 : end].all(1)


def tune_baselines(engine: BaselineEngine, sales, available, folds) -> dict:
    """Choose one parameter per baseline family by mean validation MASE (validation folds only)."""
    grid = {
        "moving_average": bl.MA_WINDOWS,
        "seasonal_ma": bl.SMA_WEEKS,
        "sba": tuple(engine.sba_paths),
    }
    chosen, table = {}, []
    for fam, values in grid.items():
        scores = {}
        for v in values:
            mases = []
            for s, e in folds:
                ok = evaluable(available, s, e)
                fc = engine.forecast(fam, s - 1, v)
                act = sales[:, s - 1 : e]
                mae = np.abs(fc - act).mean(1)
                scale = mase_scale(sales, available, s - 1)
                m = safe_ratio(mae, scale)
                mases.append(m[ok & np.isfinite(m)])
            scores[v] = float(np.mean(np.concatenate(mases)))
            table.append({"method": fam, "parameter": v, "validation_mase": scores[v]})
        chosen[fam] = min(scores, key=lambda k: (scores[k], k))
    chosen["seasonal_naive"] = None
    return {"params": chosen, "table": table}


def run_backtest(
    sales: np.ndarray,
    available: np.ndarray,
    series_ids: np.ndarray,
    folds: list[tuple[int, int]],
    engine: BaselineEngine,
    params: dict,
    gbm_forecasts: dict[int, np.ndarray] | None = None,
    gbm_rows: np.ndarray | None = None,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Evaluate each method on each window.

    ``gbm_forecasts`` maps fold index -> (len(gbm_rows), HORIZON) forecasts for the
    subset of series in ``gbm_rows``. Returns long error rows and residual arrays
    of shape (n_series, n_folds * HORIZON) with NaN for non-evaluable days.
    """
    n = len(series_ids)
    rows = []
    residuals = {m: np.full((n, len(folds) * HORIZON), np.nan, dtype=np.float32) for m in METHODS}
    for k, (s, e) in enumerate(folds):
        ok = evaluable(available, s, e)
        act = sales[:, s - 1 : e].astype(float)
        listed = available[:, s - 1 : e] & ok[:, None]
        scale = mase_scale(sales, available, s - 1)
        fcs = {m: engine.forecast(m, s - 1, params.get(m)) for m in METHODS[:-1]}
        if gbm_forecasts is not None:
            g = np.full((n, HORIZON), np.nan)
            g[gbm_rows] = gbm_forecasts[k]
            fcs["gbm"] = g
        for m, fc in fcs.items():
            fc = np.clip(fc, 0, None)
            lm = listed & np.isfinite(fc)
            rows.append(_error_rows(series_ids, k, m, act, np.nan_to_num(fc), lm, scale))
            r = np.where(lm, act - np.nan_to_num(fc), np.nan)
            residuals[m][:, k * HORIZON : (k + 1) * HORIZON] = r
    df = pd.concat(rows, ignore_index=True)
    df = df[df["n"] > 0].reset_index(drop=True)
    return df, residuals


def select_methods(errors: pd.DataFrame) -> pd.DataFrame:
    """Per-series selection by mean validation MAE, preferring simpler methods.

    GBM is selected only when it beats the best baseline by GBM_MIN_IMPROVEMENT.
    """
    g = errors.groupby(["series", "method"], observed=True)[["abs_err", "n"]].sum()
    mae = (g["abs_err"] / g["n"]).unstack("method")
    base_cols = [m for m in METHODS[:-1] if m in mae.columns]
    best_base = mae[base_cols].idxmin(axis=1)  # idxmin returns first (simplest) on ties
    best_base_mae = mae[base_cols].min(axis=1)
    selected = best_base.copy()
    if "gbm" in mae.columns:
        use_gbm = mae["gbm"] < best_base_mae * (1 - GBM_MIN_IMPROVEMENT)
        selected[use_gbm.fillna(False)] = "gbm"
    out = pd.DataFrame({"series": mae.index, "selected_method": selected.to_numpy()})
    out["validation_mae_selected"] = [
        mae.loc[s, m] for s, m in zip(out["series"], out["selected_method"], strict=True)
    ]
    for m in mae.columns:
        out[f"validation_mae_{m}"] = mae[m].to_numpy()
    return out


def residual_quantiles(residuals: np.ndarray) -> np.ndarray:
    """Empirical residual quantiles per series, shape (n, len(INTERVAL_LEVELS))."""
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanquantile(residuals, INTERVAL_LEVELS, axis=1).T


def residual_rmse(residuals: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        cnt = np.isfinite(residuals).sum(1)
        return np.where(
            cnt > 0,
            np.sqrt(np.nansum(residuals.astype(float) ** 2, 1) / np.maximum(cnt, 1)),
            np.nan,
        )


def interval_bounds(forecast: np.ndarray, q: np.ndarray) -> dict[str, np.ndarray]:
    """80% and 95% prediction intervals for individual days, floored at zero."""
    return {
        "lo95": np.clip(forecast + q[:, [0]], 0, None),
        "lo80": np.clip(forecast + q[:, [1]], 0, None),
        "hi80": np.clip(forecast + q[:, [2]], 0, None),
        "hi95": np.clip(forecast + q[:, [3]], 0, None),
    }


def coverage(
    actual: np.ndarray, bounds: dict[str, np.ndarray], listed: np.ndarray
) -> dict[str, np.ndarray]:
    c80 = ((actual >= bounds["lo80"]) & (actual <= bounds["hi80"]) & listed).sum(1)
    c95 = ((actual >= bounds["lo95"]) & (actual <= bounds["hi95"]) & listed).sum(1)
    n = listed.sum(1)
    return {"n": n, "covered80": c80, "covered95": c95}
