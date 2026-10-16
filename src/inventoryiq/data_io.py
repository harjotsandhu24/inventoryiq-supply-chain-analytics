"""Load M5-format CSV files into aligned NumPy arrays.

Observed data only: nothing in this module invents or imputes values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ID_COLUMNS


@dataclass
class Dataset:
    """Aligned arrays for a set of series.

    ``sales[i, j]`` is observed unit sales of series ``i`` on day ``j + 1``.
    ``price[i, j]`` is the weekly shelf price for day ``j + 1`` (NaN when the
    item was not listed in the store that week). ``price`` and ``available``
    span the full calendar, including days after the last observed sale.
    """

    meta: pd.DataFrame
    calendar: pd.DataFrame
    sales: np.ndarray
    price: np.ndarray
    available: np.ndarray
    source: str

    @property
    def n_series(self) -> int:
        return len(self.meta)

    @property
    def last_day(self) -> int:
        return self.sales.shape[1]

    @property
    def n_calendar_days(self) -> int:
        return len(self.calendar)

    def subset(self, mask: np.ndarray) -> Dataset:
        idx = np.flatnonzero(mask)
        return Dataset(
            meta=self.meta.iloc[idx].reset_index(drop=True),
            calendar=self.calendar,
            sales=self.sales[idx],
            price=self.price[idx],
            available=self.available[idx],
            source=self.source,
        )

    def availability_start(self) -> np.ndarray:
        """First day (1-based) on which each series has a listed price."""
        return np.argmax(self.available, axis=1) + 1

    def date_of(self, day: int) -> str:
        return str(self.calendar.loc[day - 1, "date"])


def day_columns(columns) -> list[str]:
    return [c for c in columns if c.startswith("d_")]


def load_calendar(source_dir: Path) -> pd.DataFrame:
    cal = pd.read_csv(source_dir / "calendar.csv")
    cal["day"] = cal["d"].str.slice(2).astype(int)
    cal = cal.sort_values("day").reset_index(drop=True)
    return cal


def load_dataset(
    source_dir: Path, source: str = "m5", stores: tuple[str, ...] | None = None
) -> Dataset:
    calendar = load_calendar(source_dir)
    sales_df = pd.read_csv(source_dir / "sales_train_evaluation.csv")
    if stores is not None:
        sales_df = sales_df[sales_df["store_id"].isin(stores)].reset_index(drop=True)
    dcols = day_columns(sales_df.columns)
    expected = [f"d_{i}" for i in range(1, len(dcols) + 1)]
    if dcols != expected:
        raise ValueError("sales day columns are not a contiguous d_1..d_N sequence")
    if sales_df[dcols].isna().to_numpy().any():
        raise ValueError(
            "sales file contains missing quantities; refusing to impute (see data_validation report)"
        )
    meta = sales_df[ID_COLUMNS].copy()
    for col in ID_COLUMNS[1:]:
        meta[col] = meta[col].astype(str)
    meta["id"] = meta["id"].astype(str).str.replace("_evaluation", "", regex=False)
    sales = sales_df[dcols].to_numpy(dtype=np.int32)

    prices = pd.read_csv(source_dir / "sell_prices.csv")
    if stores is not None:
        prices = prices[prices["store_id"].isin(stores)]
    weeks = np.sort(calendar["wm_yr_wk"].unique())
    week_pos = {w: k for k, w in enumerate(weeks)}
    key = meta["item_id"] + "|" + meta["store_id"]
    key_pos = pd.Series(np.arange(len(meta)), index=key.to_numpy())
    pkey = prices["item_id"].astype(str) + "|" + prices["store_id"].astype(str)
    rows = key_pos.reindex(pkey.to_numpy()).to_numpy()
    keep = ~np.isnan(rows)
    weekly = np.full((len(meta), len(weeks)), np.nan, dtype=np.float32)
    cols = prices["wm_yr_wk"].map(week_pos).to_numpy()
    weekly[rows[keep].astype(int), cols[keep]] = prices["sell_price"].to_numpy()[keep]
    day_week = calendar["wm_yr_wk"].map(week_pos).to_numpy()
    price = weekly[:, day_week]
    available = ~np.isnan(price)
    return Dataset(
        meta=meta, calendar=calendar, sales=sales, price=price, available=available, source=source
    )
