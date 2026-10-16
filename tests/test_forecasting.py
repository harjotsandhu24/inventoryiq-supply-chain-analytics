"""Forecasting: chronology, leakage, metrics, sparse demand, selection, intervals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from inventoryiq.config import HORIZON, Windows
from inventoryiq.forecasting import baselines as bl
from inventoryiq.forecasting import gbm
from inventoryiq.forecasting.backtest import (
    BaselineEngine,
    coverage,
    evaluable,
    interval_bounds,
    residual_quantiles,
    select_methods,
)
from inventoryiq.forecasting.metrics import mase_scale, safe_ratio, summarise, window_errors


def test_windows_are_chronological_and_disjoint():
    w = Windows(1941)
    assert w.holdout == (1914, 1941)
    folds = w.validation_folds
    assert len(folds) == 5
    assert folds[-1][1] == 1913
    for (a, b), (c, _d) in zip(folds[:-1], folds[1:], strict=True):
        assert b - a + 1 == HORIZON and b < c
    assert folds[0] == (1774, 1801)
    assert w.simulation == (1760, 1941) and w.simulation[1] - w.simulation[0] + 1 >= 180
    assert all(b < w.simulation[0] for _, b in w.sim_selection_folds)
    assert w.future == (1942, 1969)


@pytest.mark.parametrize(
    "method,param",
    [("seasonal_naive", None), ("moving_average", 28), ("seasonal_ma", 4), ("sba", 0.1)],
)
def test_baselines_do_not_read_future_data(tiny_ds, method, param):
    origin = 1500
    eng = BaselineEngine(tiny_ds.sales, tiny_ds.available, tiny_ds.last_day)
    before = eng.forecast(method, origin, param)
    tampered = tiny_ds.sales.copy()
    tampered[:, origin:] = 999  # change everything after the origin
    eng2 = BaselineEngine(tampered, tiny_ds.available, tiny_ds.last_day)
    np.testing.assert_array_equal(before, eng2.forecast(method, origin, param))
    assert (before >= 0).all() and before.shape == (tiny_ds.n_series, HORIZON)


def test_gbm_features_only_use_data_at_least_28_days_old(tiny_ds):
    cube = gbm.FeatureCube(tiny_ds, tiny_ds.last_day)
    tampered = tiny_ds.sales.copy()
    target = 1700
    tampered[:, target - 28 :] += 50  # alter the 28 days before the target day and everything after
    ds2 = type(tiny_ds)(
        tiny_ds.meta, tiny_ds.calendar, tampered, tiny_ds.price, tiny_ds.available, "t"
    )
    cube2 = gbm.FeatureCube(ds2, ds2.last_day)
    x1, _, _ = cube.rows(np.array([target]), require_target=False)
    x2, _, _ = cube2.rows(np.array([target]), require_target=False)
    sales_feats = [i for i, f in enumerate(gbm.FEATURES) if f not in ("price", "price_ratio")]
    # features for day `target` read only sales <= target-28, which were changed only on day target-28 itself
    changed = [
        gbm.FEATURES[i] for i in sales_feats if not np.allclose(x1[:, i], x2[:, i], equal_nan=True)
    ]
    assert set(changed) <= {"lag28", "smean4", "rm7", "rm28", "rm91", "rstd28", "zero28"}
    tampered2 = tiny_ds.sales.copy()
    tampered2[:, target - 27 :] += 50  # strictly newer than target-28: must not change anything
    ds3 = type(tiny_ds)(
        tiny_ds.meta, tiny_ds.calendar, tampered2, tiny_ds.price, tiny_ds.available, "t"
    )
    x3, _, _ = gbm.FeatureCube(ds3, ds3.last_day).rows(np.array([target]), require_target=False)
    np.testing.assert_allclose(x1, x3, equal_nan=True)


def test_gbm_training_is_reproducible_and_nonnegative(tiny_ds):
    cube = gbm.FeatureCube(tiny_ds, tiny_ds.last_day)
    m1 = gbm.fit(cube, 1800)
    m2 = gbm.fit(cube, 1800)
    days = np.arange(1801, 1829)
    p1 = gbm.predict(cube, m1, days, tiny_ds.n_series)
    p2 = gbm.predict(cube, m2, days, tiny_ds.n_series)
    np.testing.assert_array_equal(p1, p2)
    assert (p1 >= 0).all()


def test_sba_zero_before_first_demand_and_positive_after():
    h = bl.History.build(np.array([[0, 0, 0, 2, 0, 0, 4, 0]]), np.ones((1, 8), bool), 8)
    path = bl.sba_path(h, 0.1)
    assert (path[0, :3] == 0).all()
    assert path[0, 3] > 0 and path[0, -1] > 0


def test_unlisted_days_are_not_treated_as_zero_demand():
    sales = np.array([[0, 0, 0, 0, 5, 5, 5, 5]])
    listed = np.array([[False] * 4 + [True] * 4])
    h = bl.History.build(sales, listed, 8)
    assert bl.moving_average(h, 8, 8)[0, 0] == 5.0  # mean of listed days only, not 20/8


def test_metrics_zero_demand_and_undefined_percentages():
    actual = np.array([[0, 0, 0], [1, 2, 3]], dtype=float)
    fc = np.array([[1, 0, 0], [1, 2, 3]], dtype=float)
    e = window_errors(actual, fc, np.ones_like(actual, bool))
    df = pd.DataFrame(e)
    df["scale"] = [0.0, 1.0]
    assert np.isnan(
        safe_ratio(e["abs_err"], e["actual"])[0]
    )  # WAPE undefined for zero-demand series
    s = summarise(df, [])
    assert s["mae"].iloc[0] == pytest.approx(1 / 6)
    assert s["wape"].iloc[0] == pytest.approx(1 / 6)  # aggregate WAPE is defined
    assert s["mase_defined_share"].iloc[0] == 0.5  # series with zero scale excluded, not infinite
    assert np.isfinite(s.select_dtypes("number").to_numpy(dtype=float)).all()


def test_mase_scale_uses_only_history():
    sales = np.array([[1, 3, 1, 3, 100, 100]])
    av = np.ones_like(sales, bool)
    assert mase_scale(sales, av, 4)[0] == pytest.approx(2.0)


def test_selection_prefers_simpler_method_and_requires_gbm_improvement():
    rows = []
    for s, maes in {
        "a": {"seasonal_naive": 1.0, "moving_average": 1.0, "gbm": 0.99},
        "b": {"seasonal_naive": 2.0, "moving_average": 1.5, "gbm": 1.0},
    }.items():
        for m, v in maes.items():
            rows.append({"series": s, "method": m, "abs_err": v * 28, "n": 28})
    sel = select_methods(pd.DataFrame(rows)).set_index("series")["selected_method"]
    assert sel["a"] == "seasonal_naive"  # tie -> simplest; GBM 1% better is not enough
    assert sel["b"] == "gbm"


def test_interval_bounds_and_coverage():
    resid = np.array([np.linspace(-2, 2, 101)])
    q = residual_quantiles(resid)
    assert q[0, 0] < q[0, 1] < 0 < q[0, 2] < q[0, 3]
    fc = np.full((1, 4), 0.5)
    b = interval_bounds(fc, q)
    assert (
        (b["lo95"] >= 0).all() and (b["lo95"] <= b["lo80"]).all() and (b["hi80"] <= b["hi95"]).all()
    )
    c = coverage(np.array([[0.0, 1.0, 5.0, 2.0]]), b, np.ones((1, 4), bool))
    assert c["n"][0] == 4 and c["covered95"][0] >= c["covered80"][0]


def test_evaluable_requires_history_and_full_window():
    av = np.ones((2, 200), bool)
    av[1, :150] = False
    ok = evaluable(av, 151, 178, 56)
    assert ok.tolist() == [True, False]
