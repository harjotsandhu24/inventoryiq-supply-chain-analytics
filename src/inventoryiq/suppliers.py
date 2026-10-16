"""SIMULATED operational master data: suppliers, case packs, MOQs, costs, capacity.

The M5 dataset contains no supplier, cost, or warehouse data. Every value
produced here is an explicit, deterministic assumption (see
docs/assumptions.md). Rules only use sales observed before ``cutoff_day`` so
assumptions do not encode knowledge of the simulation or holdout periods.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ASSUMPTIONS_VERSION, FIN, SUPPLIERS

CASE_PACK_RULES = (
    (5.0, 12),
    (2.0, 6),
    (0.75, 4),
    (0.25, 2),
    (0.0, 1),
)  # item mean daily units/store -> case pack


def supplier_table() -> pd.DataFrame:
    rows = []
    for s in SUPPLIERS:
        rows.append(
            {
                "supplier_id": s.supplier_id,
                "supplier_name": f"{s.name} (simulated)",
                "departments": ", ".join(s.departments),
                "lead_time_mean_days": s.lead_time_mean,
                "lead_time_sd_days": s.lead_time_sd,
                "moq_cases": s.moq_cases,
                "order_cost_per_line": s.order_cost,
                "capacity_factor": s.capacity_factor,
                "on_time_rate_assumed": s.on_time_rate,
                "assumptions_version": ASSUMPTIONS_VERSION,
            }
        )
    return pd.DataFrame(rows)


def dept_to_supplier() -> dict[str, str]:
    return {d: s.supplier_id for s in SUPPLIERS for d in s.departments}


def case_pack_for(mean_daily: np.ndarray) -> np.ndarray:
    m = np.nan_to_num(np.asarray(mean_daily, float))
    out = np.ones(len(m), dtype=int)
    for threshold, pack in reversed(CASE_PACK_RULES):
        out = np.where(m >= threshold, pack, out)
    return out


def line_master(ds, cutoff_day: int) -> pd.DataFrame:
    """One row per series with simulated supplier terms and cost assumptions."""
    sup = {s.supplier_id: s for s in SUPPLIERS}
    d2s = dept_to_supplier()
    meta = ds.meta.reset_index(drop=True)
    lo = max(cutoff_day - FIN.cost_basis_days + 1, 1)
    a = ds.available[:, lo - 1 : cutoff_day]
    y = np.where(a, ds.sales[:, lo - 1 : cutoff_day], 0)
    # Case pack is set per item from its average listed-day velocity across all stores in scope.
    with np.errstate(invalid="ignore", divide="ignore"):
        series_rate = np.where(a.sum(1) > 0, y.sum(1) / a.sum(1), 0.0)
    item_rate = (
        pd.Series(series_rate).groupby(meta["item_id"].to_numpy()).transform("mean").to_numpy()
    )
    case_pack = case_pack_for(item_rate)
    price_window = ds.price[:, lo - 1 : cutoff_day]
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            list_price = np.nanmedian(price_window, axis=1)
    # Items first listed after the window: fall back to their first listed price (documented rule).
    first_price = np.array(
        [row[np.isfinite(row)][0] if np.isfinite(row).any() else np.nan for row in ds.price]
    )
    list_price = np.where(np.isfinite(list_price), list_price, first_price)
    margin = meta["cat_id"].map(FIN.gross_margin).to_numpy(float)
    supplier_id = meta["dept_id"].map(d2s).to_numpy()
    df = pd.DataFrame(
        {
            "series": meta["id"],
            "item_id": meta["item_id"],
            "store_id": meta["store_id"],
            "dept_id": meta["dept_id"],
            "cat_id": meta["cat_id"],
            "supplier_id": supplier_id,
            "lead_time_mean": [sup[s].lead_time_mean for s in supplier_id],
            "lead_time_sd": [sup[s].lead_time_sd for s in supplier_id],
            "order_cost": [sup[s].order_cost for s in supplier_id],
            "case_pack": case_pack,
            "moq_units": case_pack * np.array([sup[s].moq_cases for s in supplier_id]),
            "unit_price": np.round(list_price, 2),
            "gross_margin": margin,
        }
    )
    df["unit_cost"] = np.round(df["unit_price"] * (1 - df["gross_margin"]), 2)
    df["mean_daily_pre"] = series_rate
    return df


def supplier_capacity(lines: pd.DataFrame, review_period: int = 7) -> dict[str, float]:
    """Units per review period: capacity factor x average volume of the lines in scope."""
    factor = {s.supplier_id: s.capacity_factor for s in SUPPLIERS}
    vol = lines.groupby("supplier_id")["mean_daily_pre"].sum()
    return {sid: float(np.ceil(factor[sid] * v * review_period)) for sid, v in vol.items()}
