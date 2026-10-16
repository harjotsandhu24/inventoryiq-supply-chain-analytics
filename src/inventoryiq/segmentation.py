"""Demand-pattern and value segmentation (derived from observed data only)."""

from __future__ import annotations

import numpy as np
import pandas as pd

ADI_CUTOFF = 1.32  # Syntetos-Boylan-Croston classification cut-offs
CV2_CUTOFF = 0.49
XYZ_CUTOFFS = (0.5, 1.0)  # coefficient of variation of weekly demand
ABC_CUTOFFS = (0.80, 0.95)  # cumulative share of sales value


def demand_stats(
    sales: np.ndarray, price: np.ndarray, available: np.ndarray, start: int, end: int
) -> pd.DataFrame:
    """Per-series statistics over listed days in the inclusive day window [start, end]."""
    sl = slice(start - 1, end)
    y = sales[:, sl].astype(float)
    a = available[:, sl]
    p = price[:, sl]
    n_days = a.sum(1)
    y_av = np.where(a, y, 0.0)
    nonzero = (y_av > 0).sum(1)
    total = y_av.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n_days > 0, total / n_days, np.nan)
        var = np.where(
            n_days > 1, ((np.where(a, y - mean[:, None], 0.0)) ** 2).sum(1) / (n_days - 1), np.nan
        )
        adi = np.where(nonzero > 0, n_days / nonzero, np.inf)
        nz_mean = np.where(nonzero > 0, total / nonzero, np.nan)
        nz_var = np.where(
            nonzero > 1,
            ((np.where(y_av > 0, y_av - nz_mean[:, None], 0.0)) ** 2).sum(1) / (nonzero - 1),
            0.0,
        )
        cv2 = np.where(nonzero > 0, nz_var / nz_mean**2, np.nan)
    value = np.nansum(np.where(a, y * p, 0.0), axis=1)
    # Weekly CV over complete listed weeks (window assumed to be a multiple of 7 days).
    n_weeks = y.shape[1] // 7
    wk = y_av[:, -n_weeks * 7 :].reshape(len(y), n_weeks, 7).sum(2)
    wk_av = a[:, -n_weeks * 7 :].reshape(len(y), n_weeks, 7).all(2)
    with np.errstate(invalid="ignore", divide="ignore"):
        cnt = wk_av.sum(1)
        wmean = np.where(cnt > 0, (wk * wk_av).sum(1) / cnt, np.nan)
        wvar = np.where(cnt > 1, (((wk - wmean[:, None]) ** 2) * wk_av).sum(1) / (cnt - 1), np.nan)
        wcv = np.where(wmean > 0, np.sqrt(wvar) / wmean, np.inf)
    return pd.DataFrame(
        {
            "listed_days": n_days,
            "units": total,
            "sales_value": value,
            "mean_daily": mean,
            "std_daily": np.sqrt(var),
            "zero_share": np.where(n_days > 0, 1 - nonzero / np.maximum(n_days, 1), np.nan),
            "adi": adi,
            "cv2": cv2,
            "weekly_cv": wcv,
        }
    )


def sbc_class(adi: np.ndarray, cv2: np.ndarray) -> np.ndarray:
    adi = np.asarray(adi, dtype=float)
    cv2 = np.nan_to_num(np.asarray(cv2, dtype=float), nan=0.0)
    out = np.where(
        adi < ADI_CUTOFF,
        np.where(cv2 < CV2_CUTOFF, "smooth", "erratic"),
        np.where(cv2 < CV2_CUTOFF, "intermittent", "lumpy"),
    ).astype(object)
    out[~np.isfinite(adi)] = "no_demand"
    return out


def xyz_class(weekly_cv: np.ndarray) -> np.ndarray:
    cv = np.asarray(weekly_cv, dtype=float)
    return np.where(cv <= XYZ_CUTOFFS[0], "X", np.where(cv <= XYZ_CUTOFFS[1], "Y", "Z")).astype(
        object
    )


def abc_class(sales_value: np.ndarray) -> np.ndarray:
    """Pareto classification on cumulative share of sales value (ties broken by position)."""
    v = np.nan_to_num(np.asarray(sales_value, dtype=float))
    order = np.argsort(-v, kind="stable")
    total = v.sum()
    out = np.empty(len(v), dtype=object)
    if total <= 0:
        out[:] = "C"
        return out
    # Share of value *before* the item is added, so the item that crosses 80% is still A.
    cum_before = np.concatenate(([0.0], np.cumsum(v[order])[:-1])) / total
    cls = np.where(
        cum_before < ABC_CUTOFFS[0], "A", np.where(cum_before < ABC_CUTOFFS[1], "B", "C")
    )
    out[order] = cls
    out[v <= 0] = "C"
    return out


def volume_tier(mean_daily: np.ndarray) -> np.ndarray:
    m = np.nan_to_num(np.asarray(mean_daily, dtype=float))
    q = np.quantile(m, [0.5, 0.9]) if len(m) else [0, 0]
    return np.where(m >= q[1], "high", np.where(m >= q[0], "medium", "low")).astype(object)
