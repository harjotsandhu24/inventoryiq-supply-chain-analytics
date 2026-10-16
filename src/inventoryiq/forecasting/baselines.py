"""Vectorised baseline forecasters.

Every forecaster takes an ``origin`` (the last observed day, 1-based) and only
reads ``sales[:, :origin]``. Days before an item was listed are excluded from
averages rather than treated as zero demand. All forecasts are non-negative.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import HORIZON, SEASON


@dataclass
class History:
    """Cumulative sums that make window means O(1) per origin."""

    y: np.ndarray  # (n, T) float, zero where unavailable
    a: np.ndarray  # (n, T) bool listed mask
    csum: np.ndarray  # (n, T+1)
    ccnt: np.ndarray  # (n, T+1)

    @classmethod
    def build(cls, sales: np.ndarray, available: np.ndarray, last_day: int) -> History:
        a = available[:, :last_day].astype(bool)
        y = np.where(a, sales[:, :last_day], 0).astype(np.float64)
        z = np.zeros((len(y), 1))
        return cls(y, a, np.hstack([z, np.cumsum(y, 1)]), np.hstack([z, np.cumsum(a, 1)]))

    def window_mean(self, origin: int, w: int) -> np.ndarray:
        lo = max(origin - w, 0)
        s = self.csum[:, origin] - self.csum[:, lo]
        c = self.ccnt[:, origin] - self.ccnt[:, lo]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(c > 0, s / c, 0.0)


def seasonal_naive(h: History, origin: int, horizon: int = HORIZON) -> np.ndarray:
    """Repeat the last observed week. Unlisted source days fall back to the 28-day mean."""
    src = origin - SEASON + (np.arange(horizon) % SEASON)  # 0-based column of source day
    vals = h.y[:, src]
    ok = h.a[:, src]
    fb = h.window_mean(origin, 28)[:, None]
    return np.where(ok, vals, fb)


def moving_average(h: History, origin: int, window: int, horizon: int = HORIZON) -> np.ndarray:
    return np.repeat(h.window_mean(origin, window)[:, None], horizon, axis=1)


def seasonal_moving_average(
    h: History, origin: int, weeks: int, horizon: int = HORIZON
) -> np.ndarray:
    """Mean of the last ``weeks`` listed observations on the same weekday."""
    out = np.empty((h.y.shape[0], SEASON))
    for k in range(SEASON):
        # target weekday position: days origin+1+k, origin+8+k, ... share weekday with origin+1+k-7j
        cols = origin + 1 + k - SEASON * np.arange(1, weeks + 1) - 1  # 0-based
        cols = cols[cols >= 0]
        s = (h.y[:, cols] * h.a[:, cols]).sum(1)
        c = h.a[:, cols].sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, k] = np.where(c > 0, s / c, h.window_mean(origin, 28))
    return out[:, np.arange(horizon) % SEASON]


def sba_path(h: History, alpha: float) -> np.ndarray:
    """Croston forecast with Syntetos-Boylan bias correction, evaluated after every day.

    Returns ``level[:, t]`` = forecast made at the end of day t+1 (0-based t).
    Size and interval are smoothed only on demand occurrences; the interval
    counts listed days since the previous demand.
    """
    n, T = h.y.shape
    z = np.zeros(n)
    p = np.zeros(n)
    q = np.zeros(n)  # listed days since last demand (incl. current)
    started = np.zeros(n, dtype=bool)
    out = np.zeros((n, T))
    corr = 1 - alpha / 2
    for t in range(T):
        listed = h.a[:, t]
        q = q + listed
        d = h.y[:, t]
        occ = listed & (d > 0)
        first = occ & ~started
        upd = occ & started
        z = np.where(first, d, np.where(upd, z + alpha * (d - z), z))
        p = np.where(first, q, np.where(upd, p + alpha * (q - p), p))
        started |= first
        q = np.where(occ, 0, q)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, t] = np.where(started & (p > 0), corr * z / p, 0.0)
    return out


def sba(path: np.ndarray, origin: int, horizon: int = HORIZON) -> np.ndarray:
    return np.repeat(path[:, origin - 1][:, None], horizon, axis=1)


# Candidate parameter grids, tuned on validation folds only.
MA_WINDOWS = (7, 14, 28, 56)
SMA_WEEKS = (2, 4, 8)
SBA_ALPHAS = (0.05, 0.1, 0.2)
