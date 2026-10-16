"""Reproducible stratified selection of the demo scope.

Selection uses only data before the holdout so the demo set is not chosen with
knowledge of holdout accuracy. Strata are store x category x demand pattern,
with a guaranteed draw from the high-volume tier so fast movers are present.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .segmentation import demand_stats, sbc_class, volume_tier

MIN_LISTED_DAYS = 365
MIN_PER_STRATUM = 3
HIGH_VOLUME_PER_STORE = 12


def _largest_remainder(sizes: pd.Series, total: int, minimum: int) -> pd.Series:
    sizes = sizes[sizes > 0]
    if total > int(sizes.sum()):
        raise ValueError("demo size larger than the eligible population")
    minimum = min(
        minimum, total // max(len(sizes), 1)
    )  # shrink the floor when strata outnumber slots
    base = sizes.clip(upper=minimum).astype(int)
    remaining = total - int(base.sum())
    spare = (sizes - base).astype(float)
    quota = spare / spare.sum() * remaining if spare.sum() > 0 else spare
    alloc = base + np.floor(quota).astype(int)
    short = total - int(alloc.sum())
    order = (quota - np.floor(quota)).sort_values(ascending=False, kind="stable").index
    for key in order[:short]:
        alloc[key] += 1
    return np.minimum(alloc, sizes).astype(int)


def classify_for_sampling(ds, stores: tuple[str, ...], cutoff_day: int) -> pd.DataFrame:
    """Per-series attributes computed from the 364 days ending at ``cutoff_day``."""
    stats = demand_stats(ds.sales, ds.price, ds.available, cutoff_day - 363, cutoff_day)
    df = pd.concat([ds.meta.reset_index(drop=True), stats], axis=1)
    df["row"] = np.arange(len(df))
    df["pattern"] = sbc_class(df["adi"], df["cv2"])
    start = ds.availability_start()
    df["history_days"] = cutoff_day - start + 1
    df["eligible"] = (
        df["store_id"].isin(stores) & (df["history_days"] >= MIN_LISTED_DAYS) & (df["units"] > 0)
    )
    df["exclusion_reason"] = np.select(
        [~df["store_id"].isin(stores), df["history_days"] < MIN_LISTED_DAYS, df["units"] <= 0],
        [
            "store not in demo scope",
            "fewer than 365 listed days before holdout",
            "no sales in the 364 days before holdout",
        ],
        default="",
    )
    df["volume_tier"] = "low"
    for s in stores:
        m = df["store_id"] == s
        df.loc[m, "volume_tier"] = volume_tier(df.loc[m, "mean_daily"].to_numpy())
    return df


def select_demo_series(df: pd.DataFrame, per_store: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    picks = []
    for store in sorted(df.loc[df["eligible"], "store_id"].unique()):
        pool = df[df["eligible"] & (df["store_id"] == store)]
        hv = pool[pool["volume_tier"] == "high"]
        n_hv = min(HIGH_VOLUME_PER_STORE, len(hv))
        hv_pick = (
            hv.iloc[np.sort(rng.choice(len(hv), size=n_hv, replace=False))] if n_hv else hv.iloc[:0]
        )
        rest = pool.drop(hv_pick.index)
        sizes = rest.groupby(["cat_id", "pattern"]).size()
        alloc = _largest_remainder(sizes, per_store - n_hv, MIN_PER_STRATUM)
        chosen = [hv_pick.assign(selection_rule="high-volume guarantee")]
        for key, k in alloc.items():
            grp = rest[(rest["cat_id"] == key[0]) & (rest["pattern"] == key[1])]
            idx = np.sort(rng.choice(len(grp), size=int(k), replace=False))
            chosen.append(grp.iloc[idx].assign(selection_rule=f"stratum {key[0]} / {key[1]}"))
        picks.append(pd.concat(chosen))
    out = pd.concat(picks).sort_values(["store_id", "dept_id", "item_id"]).reset_index(drop=True)
    if out["id"].duplicated().any():
        raise AssertionError("duplicate series in demo selection")
    return out


def sampling_summary(population: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    pop = population[population["eligible"]]
    rows = []
    for col in ("cat_id", "pattern", "volume_tier", "store_id"):
        p = pop[col].value_counts(normalize=True)
        s = sample[col].value_counts(normalize=True)
        n = sample[col].value_counts()
        for k in sorted(set(p.index) | set(s.index)):
            rows.append(
                {
                    "dimension": col,
                    "group": k,
                    "population_share": float(p.get(k, 0)),
                    "sample_share": float(s.get(k, 0)),
                    "sample_count": int(n.get(k, 0)),
                }
            )
    return pd.DataFrame(rows)
