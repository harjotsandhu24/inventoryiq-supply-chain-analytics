"""Inventory policy, constraints, allocation, and exposure tests."""

from __future__ import annotations

import numpy as np
import pytest

from inventoryiq.inventory.policy import (
    Settings,
    allocate,
    empirical_quantile,
    exposure,
    plan,
    priority_order,
    steady_state,
)
from tests.conftest import line, lines


def test_zero_inventory_is_high_risk_and_orders():
    out = plan(line(on_hand=0.0, on_order=0.0), Settings())
    assert out["risk"][0] == "High"
    assert out["recommended_qty"][0] > 0
    # mu_L = 10*5 = 50, sigma_L = sqrt(5*16 + 100*4) = 21.91 -> P(D_L > 0) = Phi(50/21.91) = Phi(2.282) = 0.9888
    assert out["p_stockout_lead_time"][0] == pytest.approx(0.9888, abs=5e-4)


def test_zero_demand_never_orders_and_has_no_coverage():
    out = plan(line(mu=0.0, sigma=0.0, on_hand=0.0, on_order=0.0), Settings())
    assert out["recommended_qty"][0] == 0
    assert out["risk"][0] == "Low"
    assert np.isnan(out["coverage_days"][0])
    assert out["safety_stock"][0] == 0


def test_high_demand_scales_order():
    lo = plan(line(mu=10.0), Settings())["recommended_qty"][0]
    hi = plan(line(mu=200.0, sigma=40.0), Settings())["recommended_qty"][0]
    assert hi > lo * 5


@pytest.mark.parametrize("lt", [1.0, 30.0, 90.0])
def test_extreme_lead_times_are_finite_and_monotone(lt):
    out = plan(line(lt_mean=lt), Settings())
    for k in ("safety_stock", "reorder_point", "order_up_to", "recommended_qty"):
        assert np.isfinite(out[k][0])
    longer = plan(line(lt_mean=lt + 10), Settings())
    assert longer["reorder_point"][0] > out["reorder_point"][0]


def test_lead_time_shift_floors_at_one_day():
    out = plan(line(lt_mean=2.0), Settings(lead_time_shift=-10))
    assert out["lead_time"][0] == 1.0


def test_existing_orders_in_transit_reduce_the_order():
    no_transit = plan(line(on_hand=20.0, on_order=0.0), Settings())["recommended_qty"][0]
    transit = plan(line(on_hand=20.0, on_order=96.0), Settings())["recommended_qty"][0]
    assert transit == no_transit - 96
    covered = plan(line(on_hand=20.0, on_order=1000.0), Settings())
    assert covered["recommended_qty"][0] == 0


def test_quantities_are_whole_cases_and_respect_moq():
    for case, moq in ((1, 1), (6, 6), (12, 48), (5, 7)):
        q = plan(
            line(on_hand=0.0, on_order=0.0, mu=1.3, case_pack=float(case), moq=float(moq)),
            Settings(),
        )["recommended_qty"][0]
        assert q % case == 0
        assert q >= np.ceil(moq / case) * case
        assert q == int(q) and q >= 0


def test_service_level_increases_safety_stock():
    ss = [
        plan(line(), Settings(service_level=s))["safety_stock"][0] for s in (0.8, 0.9, 0.95, 0.99)
    ]
    assert ss == sorted(ss)
    assert plan(line(), Settings(service_level=0.5))["safety_stock"][0] == pytest.approx(
        0.0, abs=1e-9
    )


def test_lead_time_variability_increases_safety_stock():
    a = plan(line(), Settings(lead_time_sd_multiplier=0.0))["safety_stock"][0]
    b = plan(line(), Settings(lead_time_sd_multiplier=2.0))["safety_stock"][0]
    assert b > a
    # with no lead-time variability the formula reduces to z * sigma * sqrt(P)
    assert a == pytest.approx(plan(line(), Settings())["z"][0] * 4.0 * np.sqrt(12), rel=1e-12)


def test_review_period_extends_protection_period():
    a = plan(line(), Settings(review_period=7))
    b = plan(line(), Settings(review_period=14))
    assert b["protection_period"][0] == a["protection_period"][0] + 7
    assert b["reorder_point"][0] > a["reorder_point"][0]


@pytest.mark.parametrize(
    "bad",
    [
        dict(service_level=1.0),
        dict(service_level=0.2),
        dict(review_period=0),
        dict(review_period=3.5),
        dict(budget=-1.0),
        dict(budget=float("nan")),
        dict(lead_time_sd_multiplier=-1.0),
    ],
)
def test_invalid_settings_rejected(bad):
    with pytest.raises(ValueError):
        plan(line(), Settings(**bad))


def test_intermittent_fallback_raises_reorder_point_conservatively():
    hist = np.zeros((1, 364))
    hist[0, ::20] = 25  # rare large orders
    lin = line(mu=1.25, sigma=1.0, intermittent=True, on_hand=0.0, on_order=0.0)
    normal = plan(lin, Settings(intermittent_fallback=False), history=hist)
    fb = plan(lin, Settings(), history=hist)
    assert fb["reorder_point"][0] >= normal["reorder_point"][0]
    assert fb["rop_basis"][0] == "empirical"
    smooth = plan(dict(lin, intermittent=np.array([False])), Settings(), history=hist)
    assert smooth["rop_basis"][0] == "normal"


def test_empirical_quantile_nearest_rank():
    h = np.array([0, 1, 0, 3, np.nan, 2, 0], dtype=float)  # NaN (unlisted) is dropped
    # 2-day rolling sums of [0,1,0,3,2,0] = [1,1,3,5,2] -> sorted [1,1,2,3,5]; 80% nearest rank = ceil(4)=4th -> 3
    assert empirical_quantile(h, 2, 0.8) == 3
    assert np.isnan(empirical_quantile(np.array([1.0]), 3, 0.9))


def _alloc_case(budget=None, capacity=None):
    qty = np.array([24.0, 12.0, 36.0])
    case = np.array([12.0, 6.0, 12.0])
    moq = np.array([12.0, 6.0, 12.0])
    cost = np.array([2.0, 5.0, 1.0])
    sup = np.array(["A", "A", "B"])
    return allocate(qty, case, moq, cost, sup, np.array([2, 0, 1]), capacity, budget)


def test_budget_zero_defers_everything():
    final, status = _alloc_case(budget=0.0)
    assert final.sum() == 0
    assert all(s == "Deferred: budget" for s in status)


def test_negative_budget_raises():
    with pytest.raises(ValueError):
        _alloc_case(budget=-5.0)


def test_budget_never_exceeded_and_priority_respected():
    for b in (10, 40, 75, 1000):
        final, status = _alloc_case(budget=float(b))
        spend = (final * np.array([2.0, 5.0, 1.0])).sum()
        assert spend <= b + 1e-9
    final, status = _alloc_case(budget=40.0)
    # priority order is [2, 0, 1]: line 2 costs 36 -> funded; line 0 needs 48 > 4 left -> deferred (1 case = 24 > 4)
    assert final[2] == 36 and final[0] == 0 and status[0] == "Deferred: budget"


def test_supplier_capacity_reduces_lower_priority_lines():
    final, status = _alloc_case(capacity={"A": 30.0, "B": 1000.0})
    # priority within supplier A: line 0 (24 units) then line 1 (12) -> only 6 left -> 6 >= MOQ 6
    assert final[0] == 24 and final[1] == 6 and status[1] == "Reduced: supplier capacity"
    final, status = _alloc_case(capacity={"A": 20.0, "B": 1000.0})
    assert final[0] == 12 and status[0] == "Reduced: supplier capacity"
    assert final[1] == 6


def test_allocation_never_increases_quantities():
    qty = np.array([24.0, 12.0, 36.0])
    final, _ = _alloc_case(budget=55.0, capacity={"A": 25.0, "B": 30.0})
    assert (final <= qty).all() and (final >= 0).all()


def test_priority_order_is_deterministic():
    risk = np.array(["Low", "High", "Medium", "High"], dtype=object)
    p = np.array([0.0, 0.6, 0.2, 0.9])
    v = np.array([1.0, 1.0, 1.0, 1.0])
    ids = np.array(["d", "b", "c", "a"])
    assert priority_order(risk, p, v, ids).tolist() == [3, 1, 2, 0]


def test_one_recommendation_per_line_no_duplicates():
    rows = [
        dict(
            mu=5.0,
            sigma=2.0,
            lt_mean=5.0,
            lt_sd=1.0,
            on_hand=0.0,
            on_order=0.0,
            backorders=0.0,
            moq=6.0,
            case_pack=6.0,
            unit_cost=1.0,
            unit_price=2.0,
            order_cost=5.0,
            intermittent=False,
        )
    ] * 4
    out = plan(lines(rows), Settings())
    assert len(out["recommended_qty"]) == 4
    assert (
        len(set(out["recommended_qty"])) == 1
    )  # identical inputs -> identical, independent results


def test_exposure_and_steady_state_are_consistent():
    lin = line()
    s = Settings()
    p = plan(lin, s)
    ex = exposure(
        p["inventory_position"] + p["recommended_qty"],
        lin["mu"],
        p["protection_period"],
        p["sigma_p"],
    )
    ex_none = exposure(p["inventory_position"], lin["mu"], p["protection_period"], p["sigma_p"])
    assert ex["expected_short_units"][0] < ex_none["expected_short_units"][0]
    assert ex["p_short"][0] < ex_none["p_short"][0]
    st = steady_state(p, lin, s)
    assert st["total_cost"][0] == pytest.approx(
        st["holding_cost"][0] + st["ordering_cost"][0] + st["shortage_cost"][0]
    )
    assert 0 <= st["fill_rate"][0] <= 1
    hi = steady_state(plan(lin, Settings(service_level=0.99)), lin, Settings(service_level=0.99))
    assert hi["holding_cost"][0] > st["holding_cost"][0]
    assert hi["shortage_cost"][0] < st["shortage_cost"][0]


def test_deterministic_demand_no_variability():
    out = plan(line(sigma=0.0, lt_sd=0.0, on_hand=0.0, on_order=0.0), Settings())
    assert out["safety_stock"][0] == 0
    assert out["p_stockout_lead_time"][0] == 1.0
    ex = exposure(np.array([0.0]), np.array([10.0]), out["protection_period"], out["sigma_p"])
    assert ex["expected_short_units"][0] == pytest.approx(120.0)
