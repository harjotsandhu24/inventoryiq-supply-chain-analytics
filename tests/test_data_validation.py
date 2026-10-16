"""Data validation, joins, sampling, and segmentation."""

from __future__ import annotations

import shutil

import numpy as np
import pandas as pd
import pytest

from inventoryiq.config import Windows
from inventoryiq.data_io import load_dataset
from inventoryiq.sampling import classify_for_sampling, select_demo_series
from inventoryiq.segmentation import abc_class, sbc_class, xyz_class
from inventoryiq.validate import run_validation, validate_calendar


def test_clean_synthetic_data_passes(tiny_source, tiny_ds, tmp_path):
    rep = run_validation(tiny_source, tiny_ds, Windows(tiny_ds.last_day), tmp_path)
    assert rep["summary"]["passed"]
    names = {c["name"]: c for c in rep["checks"]}
    assert names["join_price_no_fanout"]["passed"]
    assert names["validation_file_is_prefix"]["passed"]
    assert (tmp_path / "data_validation.md").exists()


def _copy(src, dst):
    shutil.copytree(src, dst)
    return dst


@pytest.mark.parametrize(
    "corruption,check",
    [
        ("duplicate_price", "prices_unique_key"),
        ("negative_sales", "sales_nonnegative"),
        ("null_sales", "sales_no_nulls"),
        ("zero_price", "prices_positive"),
        ("duplicate_series", "sales_unique_id"),
    ],
)
def test_corrupted_inputs_fail_validation(tiny_source, tmp_path, corruption, check):
    src = _copy(tiny_source, tmp_path / "src")
    ev = pd.read_csv(src / "sales_train_evaluation.csv")
    pr = pd.read_csv(src / "sell_prices.csv")
    if corruption == "duplicate_price":
        pr = pd.concat([pr, pr.iloc[[0]]])
    elif corruption == "negative_sales":
        ev.loc[0, "d_10"] = -3
    elif corruption == "null_sales":
        ev.loc[0, "d_10"] = np.nan
    elif corruption == "zero_price":
        pr.loc[pr.index[0], "sell_price"] = 0
    elif corruption == "duplicate_series":
        ev = pd.concat([ev, ev.iloc[[0]]])
    ev.to_csv(src / "sales_train_evaluation.csv", index=False)
    pr.to_csv(src / "sell_prices.csv", index=False)
    try:
        ds = load_dataset(src, "corrupt")
    except Exception:
        return  # refusing to load corrupted input is also an acceptable, non-silent outcome
    with pytest.raises(RuntimeError, match=check):
        run_validation(src, ds, Windows(ds.last_day), tmp_path / "rep")


def test_calendar_gap_detected(tiny_ds):
    cal = tiny_ds.calendar.drop(index=10).reset_index(drop=True)
    checks = {c.name: c for c in validate_calendar(cal)}
    assert (
        not checks["calendar_daily_dates"].passed or not checks["calendar_contiguous_days"].passed
    )


def test_prices_align_to_days_without_duplication(tiny_ds):
    assert tiny_ds.price.shape == (tiny_ds.n_series, tiny_ds.n_calendar_days)
    # sales never occur on unlisted days
    assert (tiny_ds.sales * ~tiny_ds.available[:, : tiny_ds.last_day]).sum() == 0
    # each day maps to exactly one weekly price
    wk = tiny_ds.calendar["wm_yr_wk"].to_numpy()
    same_week = wk[1:] == wk[:-1]
    p = np.nan_to_num(tiny_ds.price, nan=-1)
    assert (p[:, 1:][:, same_week] == p[:, :-1][:, same_week]).all()


def test_aggregation_consistency(tiny_source, tiny_ds):
    ev = pd.read_csv(tiny_source / "sales_train_evaluation.csv")
    dcols = [c for c in ev.columns if c.startswith("d_")]
    assert ev[dcols].to_numpy().sum() == tiny_ds.sales.sum()
    by_store = pd.Series(tiny_ds.sales.sum(1)).groupby(tiny_ds.meta["store_id"]).sum()
    assert by_store.sum() == tiny_ds.sales.sum()


def test_sampling_is_reproducible_and_stratified(tiny_ds):
    w = Windows(tiny_ds.last_day)
    pop = classify_for_sampling(tiny_ds, ("CA_1", "CA_2"), w.holdout[0] - 1)
    a = select_demo_series(pop, 10, 123)
    b = select_demo_series(pop, 10, 123)
    assert a["id"].tolist() == b["id"].tolist()
    assert not a["id"].duplicated().any()
    assert set(a["store_id"]) <= {"CA_1", "CA_2"}
    assert a["eligible"].all()
    assert a["cat_id"].nunique() >= 2
    c = select_demo_series(pop, 10, 124)
    assert c["id"].tolist() != a["id"].tolist() or len(pop[pop.eligible]) <= 20


def test_segmentation_rules():
    assert sbc_class(
        np.array([1.0, 1.0, 2.0, 2.0, np.inf]), np.array([0.1, 0.9, 0.1, 0.9, np.nan])
    ).tolist() == ["smooth", "erratic", "intermittent", "lumpy", "no_demand"]
    assert xyz_class(np.array([0.2, 0.5, 0.8, 1.5, np.inf])).tolist() == ["X", "X", "Y", "Z", "Z"]
    abc = abc_class(np.array([50.0, 30.0, 10.0, 6.0, 4.0, 0.0]))
    # cumulative share before each item: 0, .5, .8, .9, .96 -> A, A, B, B, C; zero value -> C
    assert abc.tolist() == ["A", "A", "B", "B", "C", "C"]
