"""Historical simulation: ledger invariants, timing, determinism, leakage, and cost accounting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from inventoryiq.inventory import simulation as sim
from inventoryiq.inventory.policy import Settings
from inventoryiq.suppliers import supplier_table


def _inputs(n=3, days=30, seed=0, lt=3):
    rng = np.random.default_rng(seed)
    demand = rng.poisson(4, (n, days))
    lines = pd.DataFrame(
        {
            "series": [f"S{i}" for i in range(n)],
            "supplier_id": "SUP-01",
            "case_pack": 6,
            "moq_units": 6,
            "unit_cost": 1.5,
            "unit_price": 2.5,
            "lead_time_mean": float(lt),
            "lead_time_sd": 1.0,
            "order_cost": 5.0,
            "gross_margin": 0.4,
        }
    )
    draws = {"SUP-01": np.full(days, lt)}
    return sim.SimInputs(
        lines["series"].to_numpy(),
        demand,
        500,
        lines,
        {"SUP-01": 1e9},
        draws,
        np.full(n, 20.0),
        np.arange(0, days, 7),
    )


def _order_up_to(level):
    def policy(t, on_hand, on_order):
        q = np.maximum(level - on_hand - on_order, 0)
        q = np.ceil(q / 6) * 6
        return q, {
            "risk": np.array(["Medium"] * len(q), dtype=object),
            "p_stockout": np.zeros(len(q)),
            "value_rate": np.zeros(len(q)),
        }

    return policy


def test_ledger_balances_and_never_negative():
    inp = _inputs()
    res = sim.run(inp, _order_up_to(40), "p")
    L = res["ledger"]
    np.testing.assert_allclose(L["opening"] + L["receipts"] - L["fulfilled"], L["closing"])
    np.testing.assert_allclose(L["fulfilled"] + L["lost"], L["demand"])
    assert (L["closing"] >= 0).all()
    np.testing.assert_allclose(L["opening"][:, 1:], L["closing"][:, :-1])  # continuity


def test_receipts_arrive_exactly_after_lead_time():
    inp = _inputs(lt=4)
    res = sim.run(inp, _order_up_to(60), "p")
    po = res["purchase_orders"]
    assert ((po["arrival_day"] - po["order_day"]) == 4).all()
    rec = res["ledger"]["receipts"]
    for r in po.itertuples():
        i = int(r.series[1:])
        assert r.arrival_day - 500 >= rec.shape[1] or rec[i, r.arrival_day - 500] >= r.quantity


def test_no_duplicate_orders_per_line_and_day():
    res = sim.run(_inputs(n=5), _order_up_to(50), "p")
    po = res["purchase_orders"]
    assert not po.duplicated(["series", "order_day"]).any()


def test_zero_inventory_and_zero_demand_edge():
    inp = _inputs()
    inp.demand[:] = 0
    inp.initial_on_hand[:] = 0
    res = sim.run(inp, _order_up_to(0), "p")
    assert res["ledger"]["lost"].sum() == 0 and len(res["purchase_orders"]) == 0


def test_policy_only_sees_information_up_to_review_day():
    """The forecast policy reads history through the review day; altering later demand must not change day-0 decisions."""
    inp = _inputs(days=30)
    hist = np.hstack([np.full((3, 364), 4.0), inp.demand.astype(float)])
    listed = np.ones_like(hist, bool)
    mu = {int(t): np.full(3, 4.0) for t in inp.review_days}
    pol = sim.forecast_policy_factory(
        inp, mu, np.full(3, 2.0), np.zeros(3, bool), hist, listed, Settings()
    )
    q1, _ = pol(0, np.full(3, 5.0), np.zeros(3))
    hist2 = hist.copy()
    hist2[:, 364 + 1 :] = 1000
    pol2 = sim.forecast_policy_factory(
        inp, mu, np.full(3, 2.0), np.zeros(3, bool), hist2, listed, Settings()
    )
    q2, _ = pol2(0, np.full(3, 5.0), np.zeros(3))
    np.testing.assert_array_equal(q1, q2)
    basic1 = sim.basic_policy_factory(
        inp,
        hist,
        listed,
        {"avg_window": 28, "min_days_after_lead_time": 14, "max_days_after_lead_time": 28},
    )
    basic2 = sim.basic_policy_factory(
        inp,
        hist2,
        listed,
        {"avg_window": 28, "min_days_after_lead_time": 14, "max_days_after_lead_time": 28},
    )
    np.testing.assert_array_equal(
        basic1(0, np.zeros(3), np.zeros(3))[0], basic2(0, np.zeros(3), np.zeros(3))[0]
    )


def test_lead_time_draws_are_deterministic_and_valid():
    sup = supplier_table()
    a = sim.draw_lead_times(sup, 200, 42)
    b = sim.draw_lead_times(sup, 200, 42)
    for k in a:
        np.testing.assert_array_equal(a[k], b[k])
        assert a[k].min() >= 1
    c = sim.draw_lead_times(sup, 200, 43)
    assert any((a[k] != c[k]).any() for k in a)
    m = sup.set_index("supplier_id")["lead_time_mean_days"]
    for k, v in a.items():
        assert abs(v.mean() - m[k]) < 1.5


def test_cost_accounting_reconciles_and_excludes_purchase_spend():
    inp = _inputs()
    res = sim.run(inp, _order_up_to(40), "p")
    s = sim.summarise(res, inp.lines, inp.review_days, 0.25, 1.5)
    assert s["modeled_total_cost"] == pytest.approx(
        s["holding_cost"] + s["ordering_cost"] + s["shortage_penalty"], abs=0.011
    )
    assert s["purchasing_spend"] == pytest.approx(res["ledger"]["ordered"].sum() * 1.5)
    # hand check: holding = sum(closing) * cost * rate / 365; shortage = lost * margin * multiplier
    L = res["ledger"]
    assert s["holding_cost"] == pytest.approx(round(L["closing"].sum() * 1.5 * 0.25 / 365, 2))
    assert s["shortage_penalty"] == pytest.approx(round(L["lost"].sum() * 1.0 * 1.5, 2))
    assert s["ordering_cost"] == pytest.approx(len(res["purchase_orders"]) * 5.0)
    for k in ("holding_cost", "ordering_cost", "shortage_penalty", "purchasing_spend"):
        assert round(s[k], 2) == s[k]  # currency precision: cents
    assert 0 <= s["fill_rate"] <= 1 and 0 <= s["cycle_service_level"] <= 1


def test_sensitivity_is_monotone_in_shortage_multiplier():
    inp = _inputs()
    res = sim.run(inp, _order_up_to(15), "p")
    costs = [
        sim.summarise(res, inp.lines, inp.review_days, 0.25, m)["shortage_penalty"]
        for m in (0.5, 1, 2, 3)
    ]
    assert costs == sorted(costs)
    assert res["ledger"]["lost"].sum() > 0


def test_capacity_constraint_limits_orders():
    inp = _inputs(n=4)
    inp.capacity["SUP-01"] = 12.0
    res = sim.run(inp, _order_up_to(100), "p")
    by_day = res["purchase_orders"].groupby("order_day")["quantity"].sum()
    assert (by_day <= 12).all()
