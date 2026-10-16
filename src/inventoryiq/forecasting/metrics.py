"""Forecast accuracy metrics with explicit handling of zero demand.

* MAE  - mean absolute error, units/day. Always defined.
* WAPE - sum|e| / sum(actual). Undefined (NaN) when actual demand sums to 0;
  never computed per day, so zero-demand days do not explode it.
* Bias - sum(forecast - actual) / sum(actual). Positive = over-forecast.
* MASE - MAE scaled by the in-sample mean absolute one-day change over listed
  history before the origin. Undefined (NaN) when that scale is 0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def mase_scale(sales: np.ndarray, available: np.ndarray, origin: int) -> np.ndarray:
    y = sales[:, :origin].astype(float)
    a = available[:, :origin]
    both = a[:, 1:] & a[:, :-1]
    d = np.abs(np.diff(y, axis=1)) * both
    cnt = both.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, d.sum(1) / cnt, np.nan)


def window_errors(
    actual: np.ndarray, forecast: np.ndarray, listed: np.ndarray
) -> dict[str, np.ndarray]:
    """Per-series error sums over the listed days of one evaluation window."""
    e = np.where(listed, forecast - actual, 0.0)
    return {
        "n": listed.sum(1),
        "abs_err": np.abs(e).sum(1),
        "err": e.sum(1),
        "actual": np.where(listed, actual, 0).sum(1),
        "forecast": np.where(listed, forecast, 0).sum(1),
        "sq_err": (e**2).sum(1),
    }


def safe_ratio(num, den):
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def summarise(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Aggregate per-series-window error rows (columns from ``window_errors`` + ``scale``)."""

    def agg(g: pd.DataFrame) -> pd.Series:
        n = g["n"].sum()
        mae_series = safe_ratio(g["abs_err"], g["n"])
        mase = safe_ratio(mae_series, g["scale"])
        valid = np.isfinite(mase)
        return pd.Series(
            {
                "series_windows": len(g),
                "days": int(n),
                "actual_units": float(g["actual"].sum()),
                "mae": float(g["abs_err"].sum() / n) if n else np.nan,
                "rmse": float(np.sqrt(g["sq_err"].sum() / n)) if n else np.nan,
                "wape": float(safe_ratio(g["abs_err"].sum(), g["actual"].sum())),
                "bias": float(safe_ratio(g["err"].sum(), g["actual"].sum())),
                "mase": float(np.mean(mase[valid])) if valid.any() else np.nan,
                "mase_defined_share": float(valid.mean()) if len(valid) else np.nan,
            }
        )

    if not by:
        return agg(df).to_frame().T
    return df.groupby(by, observed=True).apply(agg, include_groups=False).reset_index()
