"""Global gradient-boosting demand model (scikit-learn HistGradientBoosting, Poisson loss).

Leakage control: every feature for target day ``d`` is computed from sales
and prices observed on or before day ``d - 28``. Calendar attributes of ``d``
(weekday, month, published holidays, SNAP schedule) are known in advance.
Because the minimum lag equals the 28-day horizon, a single model can
forecast all 28 days from any origin without recursion.
"""

from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ..config import HORIZON

LAG = HORIZON
TRAIN_DAYS = 730
FEATURES = [
    "lag28",
    "lag35",
    "lag42",
    "lag49",
    "smean4",
    "rm7",
    "rm28",
    "rm91",
    "rstd28",
    "zero28",
    "price",
    "price_ratio",
    "age",
    "wday",
    "month",
    "mday",
    "event",
    "snap",
    "store",
    "dept",
    "cat",
]
CATEGORICAL = ["wday", "month", "event", "store", "dept", "cat"]
PARAMS = dict(
    loss="poisson",
    learning_rate=0.08,
    max_iter=300,
    max_leaf_nodes=63,
    min_samples_leaf=200,
    l2_regularization=1.0,
    early_stopping=False,
    random_state=0,
)


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[:, k:] = x[:, :-k]
    return out


def _rolling(csum: np.ndarray, ccnt: np.ndarray, end_col: np.ndarray, w: int) -> np.ndarray:
    """Mean over the ``w`` days ending at 0-based column ``end_col`` (per target column)."""
    hi = end_col + 1
    hi_c = np.clip(hi, 0, csum.shape[1] - 1)
    lo = np.minimum(np.maximum(hi - w, 0), hi_c)
    s = csum[:, hi_c] - csum[:, lo]
    c = ccnt[:, hi_c] - ccnt[:, lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(c > 0, s / c, np.nan)
    out[:, end_col < 0] = np.nan
    return out


class FeatureCube:
    """Feature arrays of shape (n_series, n_calendar_days)."""

    def __init__(self, ds, last_observed: int):
        t0 = time.time()
        n, D = ds.n_series, ds.n_calendar_days
        T = last_observed
        a = ds.available[:, :T]
        y = np.full((n, D), np.nan, dtype=np.float32)
        y[:, :T] = np.where(a, ds.sales[:, :T], np.nan)
        self.y = y
        self.listed = ds.available
        yz = np.nan_to_num(y[:, :T])
        z = np.zeros((n, 1))
        csum = np.hstack([z, np.cumsum(yz, 1)])
        csq = np.hstack([z, np.cumsum(yz**2, 1)])
        ccnt = np.hstack([z, np.cumsum(a, 1)])
        czero = np.hstack([z, np.cumsum(a & (yz == 0), 1)])
        end = np.arange(D) - LAG  # last usable 0-based column for each target column
        f: dict[str, np.ndarray] = {}
        for k in (28, 35, 42, 49):
            f[f"lag{k}"] = _shift(y, k)
        with warnings.catch_warnings():
            # all-NaN lags before an item is listed -> NaN, as intended
            warnings.simplefilter("ignore", RuntimeWarning)
            f["smean4"] = np.nanmean(
                np.stack([f["lag28"], f["lag35"], f["lag42"], f["lag49"]]), axis=0
            )
        for w in (7, 28, 91):
            f[f"rm{w}"] = _rolling(csum, ccnt, end, w)
        m2 = _rolling(csq, ccnt, end, 28)
        with np.errstate(invalid="ignore"):
            f["rstd28"] = np.sqrt(np.maximum(m2 - f["rm28"] ** 2, 0))
        f["zero28"] = _rolling(czero, ccnt, end, 28)  # share of zero days among listed days
        price = ds.price.astype(np.float32)
        f["price"] = _shift(price, LAG)
        pz = np.nan_to_num(price)
        pc = np.hstack([z, np.cumsum(pz, 1)])
        pn = np.hstack([z, np.cumsum(~np.isnan(price), 1)])
        with np.errstate(invalid="ignore", divide="ignore"):
            f["price_ratio"] = f["price"] / _rolling(pc, pn, end, 364)
        start = ds.availability_start()
        f["age"] = (np.arange(1, D + 1)[None, :] - start[:, None]).astype(np.float32)
        cal = ds.calendar
        date = pd.to_datetime(cal["date"])
        ev = cal["event_type_1"].astype("category")
        ev_code = ev.cat.codes.to_numpy().astype(np.float32)  # -1 = no event
        ev_code[ev_code < 0] = np.nan
        f["wday"] = np.broadcast_to(cal["wday"].to_numpy(np.float32), (n, D))
        f["month"] = np.broadcast_to(cal["month"].to_numpy(np.float32), (n, D))
        f["mday"] = np.broadcast_to(date.dt.day.to_numpy(np.float32), (n, D))
        f["event"] = np.broadcast_to(ev_code, (n, D))
        state = ds.meta["state_id"].to_numpy()
        snap = np.zeros((n, D), dtype=np.float32)
        for s in np.unique(state):
            snap[state == s] = cal[f"snap_{s}"].to_numpy(np.float32)
        f["snap"] = snap
        for col, name in (("store_id", "store"), ("dept_id", "dept"), ("cat_id", "cat")):
            codes = pd.Categorical(ds.meta[col]).codes.astype(np.float32)
            f[name] = np.broadcast_to(codes[:, None], (n, D))
        self.f = {k: np.asarray(v, dtype=np.float32) for k, v in f.items()}
        self.seconds = time.time() - t0

    def rows(
        self, days: np.ndarray, require_target: bool
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Stack features for 1-based ``days``; returns X, y, and (series, day) index."""
        cols = np.asarray(days) - 1
        listed = self.listed[:, cols]
        if require_target:
            listed = listed & ~np.isnan(self.y[:, cols])
        si, cj = np.nonzero(listed)
        X = np.column_stack([self.f[k][si, cols[cj]] for k in FEATURES])
        y = self.y[si, cols[cj]]
        return X, y, np.column_stack([si, cols[cj] + 1])


def fit(cube: FeatureCube, origin: int) -> HistGradientBoostingRegressor:
    days = np.arange(max(origin - TRAIN_DAYS + 1, LAG + 1), origin + 1)
    X, y, _ = cube.rows(days, require_target=True)
    cat_mask = [k in CATEGORICAL for k in FEATURES]
    model = HistGradientBoostingRegressor(categorical_features=cat_mask, **PARAMS)
    model.fit(X, y)
    return model


def predict(cube: FeatureCube, model, days: np.ndarray, n_series: int) -> np.ndarray:
    """Predictions for 1-based ``days``; unlisted series-days are 0."""
    out = np.zeros((n_series, len(days)))
    X, _, idx = cube.rows(days, require_target=False)
    if len(X):
        pred = np.clip(model.predict(X), 0, None)
        pos = {d: j for j, d in enumerate(days)}
        out[idx[:, 0], [pos[d] for d in idx[:, 1]]] = pred
    return out
