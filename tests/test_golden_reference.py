"""Golden reference tests: hand-calculated examples for the critical formulas.

Expected values were computed by hand (shown step by step) and are NOT copied
from program output. Tolerances reflect rounding in the hand calculations.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from inventoryiq.inventory.policy import Settings, allocate, plan
from inventoryiq.inventory.simulation import SimInputs, run
from tests.conftest import line


def test_golden_1_safety_stock_rop_order_up_to_and_case_rounding():
    """mu=10/day, sigma=4, E[L]=5d, sd(L)=2d, R=7d, CSL=95% (z=1.644854).

    P = 5 + 7 = 12
    sigma_P = sqrt(12*4^2 + 10^2*2^2) = sqrt(192 + 400) = sqrt(592) = 24.33105
    SS = 1.644854 * 24.33105 = 40.0210
    ROP = 10*12 + 40.0210 = 160.0210
    EOQ = sqrt(2*365*10*6 / (0.25*2)) = sqrt(87600) = 295.9730
    S = 160.0210 + max(295.9730, 10*7) = 455.9940
    IP = 100 + 30 = 130 <= 160.021 -> order
    raw = 455.994 - 130 = 325.994 -> 325.994/12 = 27.17 -> 28 cases = 336 units (MOQ 12 not binding)
    """
    out = plan(
        line(), Settings(service_level=0.95, review_period=7, max_cycle_days=None)
    )  # v1 formula
    assert out["protection_period"][0] == 12
    assert out["sigma_p"][0] == pytest.approx(24.33105, abs=1e-4)
    assert out["safety_stock"][0] == pytest.approx(40.0210, abs=2e-3)
    assert out["reorder_point"][0] == pytest.approx(160.0210, abs=2e-3)
    assert out["eoq"][0] == pytest.approx(295.9730, abs=1e-3)
    assert out["order_up_to"][0] == pytest.approx(455.9940, abs=3e-3)
    assert out["inventory_position"][0] == 130
    assert bool(out["needs_order"][0])
    assert out["recommended_qty"][0] == 336


def test_golden_2_no_order_when_position_above_reorder_point():
    """mu=2, sigma=1, L=3 (no variability), R=7, CSL=90% (z=1.281552).

    P = 10; sigma_P = sqrt(10*1) = 3.16228; SS = 1.281552*3.16228 = 4.0527; ROP = 20 + 4.0527 = 24.0527
    IP = 30 > 24.05 -> no order.  Coverage = 30 / 2 = 15 days.
    Lead-time check: mu_L = 6, sigma_L = sqrt(3) = 1.732; (30-6)/1.732 = 13.9 sd -> P(stockout) ~ 0 -> Low risk.
    """
    out = plan(
        line(
            mu=2.0,
            sigma=1.0,
            lt_mean=3.0,
            lt_sd=0.0,
            on_hand=30.0,
            on_order=0.0,
            case_pack=6.0,
            moq=6.0,
            unit_cost=1.0,
            order_cost=4.0,
        ),
        Settings(service_level=0.90),
    )
    assert out["safety_stock"][0] == pytest.approx(4.0527, abs=1e-3)
    assert out["reorder_point"][0] == pytest.approx(24.0527, abs=1e-3)
    assert not bool(out["needs_order"][0])
    assert out["recommended_qty"][0] == 0
    assert out["coverage_days"][0] == pytest.approx(15.0)
    assert out["p_stockout_lead_time"][0] < 1e-6
    assert out["risk"][0] == "Low"


def test_golden_3_minimum_order_quantity_binds():
    """mu=0.5, sigma=0.8, L=14, sd(L)=4, R=7, CSL=95%, cost $10, order cost $9, case 6, MOQ 60.

    P = 21; sigma_P = sqrt(21*0.64 + 0.25*16) = sqrt(17.44) = 4.17612
    SS = 1.644854*4.17612 = 6.8691; ROP = 0.5*21 + 6.8691 = 17.3691
    EOQ = sqrt(2*365*0.5*9 / 2.5) = sqrt(1314) = 36.2491; S = 17.3691 + 36.2491 = 53.6182
    IP = 5 -> raw = 48.6182 -> /6 = 8.10 -> 9 cases = 54 < MOQ 60 -> order 60.
    """
    out = plan(
        line(
            mu=0.5,
            sigma=0.8,
            lt_mean=14.0,
            lt_sd=4.0,
            on_hand=5.0,
            on_order=0.0,
            case_pack=6.0,
            moq=60.0,
            unit_cost=10.0,
            unit_price=16.0,
            order_cost=9.0,
        ),
        Settings(service_level=0.95, max_cycle_days=None),
    )
    assert out["sigma_p"][0] == pytest.approx(4.17612, abs=1e-4)
    assert out["reorder_point"][0] == pytest.approx(17.3691, abs=2e-3)
    assert out["order_up_to"][0] == pytest.approx(53.6182, abs=3e-3)
    assert out["raw_quantity"][0] == pytest.approx(48.6182, abs=3e-3)
    assert out["recommended_qty"][0] == 60


def test_golden_3b_days_of_supply_cap_policy_v2():
    """Same inputs as golden 1 with the v2 cap of 28 days of supply.

    cycle = min(max(EOQ 295.973, mu*R 70), mu*28 = 280) = 280
    S = 160.0210 + 280 = 440.0210; raw = 440.0210 - 130 = 310.0210 -> /12 = 25.84 -> 26 cases = 312 units.
    """
    out = plan(line(), Settings(service_level=0.95, review_period=7, max_cycle_days=28))
    assert out["cycle_stock"][0] == pytest.approx(280.0)
    assert out["order_up_to"][0] == pytest.approx(440.0210, abs=2e-3)
    assert out["recommended_qty"][0] == 312


def test_golden_4_inventory_position_with_backorders():
    """IP = on hand + on order - backorders = 0 + 20 - 5 = 15."""
    out = plan(line(on_hand=0.0, on_order=20.0, backorders=5.0), Settings())
    assert out["inventory_position"][0] == 15


def test_golden_5_budget_allocation_by_hand():
    """Three orders in priority order: costs $60, $50, $30 (case = 10 units at $1, MOQ 10). Budget $100.

    Line 0: $60 funded (left $40). Line 1: $50 > $40 -> reduce to 4 cases? case=10 units at $1 = $10/case,
    floor(40/10) = 4 cases = 40 units >= MOQ 10 -> funded 40 (left $0). Line 2: $30 > $0 -> deferred.
    """
    qty = np.array([60.0, 50.0, 30.0])
    case = np.array([10.0, 10.0, 10.0])
    moq = np.array([10.0, 10.0, 10.0])
    cost = np.array([1.0, 1.0, 1.0])
    sup = np.array(["S", "S", "S"])
    final, status = allocate(qty, case, moq, cost, sup, np.array([0, 1, 2]), None, 100.0)
    assert final.tolist() == [60.0, 40.0, 0.0]
    assert status.tolist() == ["Order", "Reduced: budget", "Deferred: budget"]


def test_golden_6_ledger_by_hand():
    """One line, opening 5, demand [3, 4, 2, 0, 6], an order of 12 placed on day 1 with a 2-day lead time.

    day0: open 5, recv 0, demand 3 -> fulfil 3, close 2
    day1: open 2, recv 0, demand 4 -> fulfil 2, lost 2, close 0; review -> order 12, arrives day 3
    day2: open 0, recv 0, demand 2 -> lost 2, close 0
    day3: open 0, recv 12, demand 0 -> close 12
    day4: open 12, recv 0, demand 6 -> fulfil 6, close 6
    Fill rate = 11 / 15.
    """
    import pandas as pd

    lines_df = pd.DataFrame(
        {
            "series": ["X"],
            "supplier_id": ["S"],
            "case_pack": [12],
            "moq_units": [12],
            "unit_cost": [1.0],
            "unit_price": [2.0],
            "lead_time_mean": [2.0],
            "order_cost": [5.0],
        }
    )
    inp = SimInputs(
        np.array(["X"]),
        np.array([[3, 4, 2, 0, 6]]),
        100,
        lines_df,
        {"S": 1e9},
        {"S": np.array([2, 2, 2, 2, 2])},
        np.array([5.0]),
        np.array([1]),
    )

    def policy(t, on_hand, on_order):
        return np.array([12.0]), {
            "risk": np.array(["High"], dtype=object),
            "p_stockout": np.zeros(1),
            "value_rate": np.zeros(1),
        }

    res = run(inp, policy, "test")
    led = res["ledger"]
    assert led["closing"][0].tolist() == [2, 0, 0, 12, 6]
    assert led["lost"][0].tolist() == [0, 2, 2, 0, 0]
    assert led["receipts"][0].tolist() == [0, 0, 0, 12, 0]
    assert led["fulfilled"].sum() / led["demand"].sum() == pytest.approx(11 / 15)
    assert res["purchase_orders"]["arrival_day"].tolist() == [103]
    assert math.isclose(
        led["opening"][0][4] + led["receipts"][0][4] - led["fulfilled"][0][4], led["closing"][0][4]
    )
