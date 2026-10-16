"""Reference replenishment policy: periodic review (R, s, S) with supplier constraints.

This module is the reference implementation. ``app/src/lib/engine`` mirrors it
operation-for-operation and is verified against fixtures generated here.

Notation (per product-store line)
    mu        expected daily demand (mean of the 28-day forecast)
    sigma     standard deviation of daily forecast error (validation RMSE)
    L, VarL   expected supplier lead time (days) and its variance (days^2)
    R         review interval (days)
    P = L + R protection period: an order placed now must cover demand until the
              order placed at the *next* review can arrive
    z         standard-normal quantile of the target cycle service level (CSL)

    sigma_P   = sqrt(P * sigma^2 + mu^2 * VarL)
    SS        = z * sigma_P
    s (ROP)   = mu * P + SS
    S         = s + min(max(EOQ, mu * R), mu * D)   order-up-to level; D = max days of supply (28)
    IP        = on_hand + on_order - backorders (backorders = 0 under lost sales)
    order if IP <= s:  Q = S - IP, rounded up to whole cases, at least the MOQ

Policy versions: v1 (pre-specified) used an uncapped EOQ cycle stock. In the
historical simulation its large lots exhausted the simulated supplier capacity,
so v2 caps cycle stock at 28 days of supply. v2 was designed after seeing v1's
results and is therefore also tested on an earlier, untouched confirmation
window (see docs/methodology.md).

Assumptions: daily demand independent and identically distributed over the
protection period, lead time independent of demand, review interval fixed.
For intermittent or lumpy demand the normal approximation is unreliable, so the
reorder point is raised to the empirical CSL-quantile of observed P-day demand
totals over the last 364 days whenever that is larger (conservative fallback).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .stats import loss_function_v, norm_cdf_v, norm_ppf

RISK_RANK = {"High": 0, "Medium": 1, "Low": 2}
EPS = 1e-9


@dataclass(frozen=True)
class Settings:
    service_level: float = 0.95
    review_period: int = 7
    lead_time_shift: float = 0.0
    lead_time_sd_multiplier: float = 1.0
    budget: float | None = None
    intermittent_fallback: bool = True
    holding_rate: float = 0.25
    shortage_multiplier: float = 1.5
    # Policy v2: cap cycle stock at this many days of expected demand (None = v1, uncapped EOQ).
    max_cycle_days: float | None = 28.0

    def validate(self) -> None:
        if not (0.5 <= self.service_level <= 0.999):
            raise ValueError("service level must be between 50% and 99.9%")
        if self.review_period not in range(1, 29):
            raise ValueError("review period must be an integer between 1 and 28 days")
        if not (-30 <= self.lead_time_shift <= 60):
            raise ValueError("lead-time shift must be between -30 and +60 days")
        if not (0 <= self.lead_time_sd_multiplier <= 5):
            raise ValueError("lead-time variability multiplier must be between 0 and 5")
        if self.budget is not None and (not math.isfinite(self.budget) or self.budget < 0):
            raise ValueError("budget must be a non-negative number")
        if self.holding_rate < 0 or self.shortage_multiplier < 0:
            raise ValueError("cost rates must be non-negative")
        if self.max_cycle_days is not None and not (self.max_cycle_days >= self.review_period):
            raise ValueError("maximum cycle days must be at least the review period")


def empirical_quantile(history: np.ndarray, window: int, level: float) -> float:
    """Nearest-rank ``level`` quantile of rolling ``window``-day sums (NaN days excluded)."""
    h = history[np.isfinite(history)]
    if window <= 0 or len(h) < window:
        return math.nan
    c = np.concatenate(([0.0], np.cumsum(h)))
    sums = np.sort(c[window:] - c[:-window])
    k = max(int(math.ceil(level * len(sums))) - 1, 0)
    return float(sums[k])


def plan(
    lines: dict[str, np.ndarray], settings: Settings, history: np.ndarray | None = None
) -> dict[str, np.ndarray]:
    """Unconstrained recommendation for every line (vectorised, reference arithmetic).

    ``lines`` keys: mu, sigma, lt_mean, lt_sd, on_hand, on_order, backorders, moq,
    case_pack, unit_cost, unit_price, order_cost, intermittent (bool).
    ``history``: optional (n, 364) array of recent daily demand for the fallback.
    """
    settings.validate()
    mu = np.maximum(np.asarray(lines["mu"], float), 0.0)
    sigma = np.maximum(np.nan_to_num(np.asarray(lines["sigma"], float)), 0.0)
    L = np.maximum(np.asarray(lines["lt_mean"], float) + settings.lead_time_shift, 1.0)
    sdL = np.asarray(lines["lt_sd"], float) * settings.lead_time_sd_multiplier
    varL = sdL * sdL
    R = float(settings.review_period)
    P = L + R
    z = norm_ppf(settings.service_level)
    sigma_p = np.sqrt(P * sigma * sigma + mu * mu * varL)
    ss_normal = z * sigma_p
    rop_normal = mu * P + ss_normal
    rop_emp = np.full(len(mu), np.nan)
    use_emp = np.zeros(len(mu), dtype=bool)
    if settings.intermittent_fallback and history is not None:
        inter = np.asarray(lines["intermittent"], bool)
        for i in np.flatnonzero(inter):
            rop_emp[i] = empirical_quantile(
                history[i], int(math.ceil(P[i])), settings.service_level
            )
        use_emp = inter & np.isfinite(rop_emp) & (rop_emp > rop_normal)
    rop = np.where(use_emp, rop_emp, rop_normal)
    ss = rop - mu * P
    unit_cost = np.asarray(lines["unit_cost"], float)
    order_cost = np.asarray(lines["order_cost"], float)
    h = settings.holding_rate * unit_cost
    with np.errstate(invalid="ignore", divide="ignore"):
        eoq = np.where(
            (mu > 0) & (h > 0),
            np.sqrt(2.0 * 365.0 * mu * order_cost / np.where(h > 0, h, 1.0)),
            0.0,
        )
    cycle = np.maximum(eoq, mu * R)
    if settings.max_cycle_days is not None:
        # v2: lot size limited to a maximum days of supply (shelf space / supplier capacity)
        cycle = np.minimum(cycle, mu * settings.max_cycle_days)
    order_up_to = rop + cycle
    on_hand = np.asarray(lines["on_hand"], float)
    on_order = np.asarray(lines["on_order"], float)
    backorders = np.asarray(lines.get("backorders", np.zeros(len(mu))), float)
    ip = on_hand + on_order - backorders
    case = np.maximum(np.asarray(lines["case_pack"], float), 1.0)
    moq_units = np.ceil(np.asarray(lines["moq"], float) / case) * case
    needs = (ip <= rop + EPS) & (order_up_to - ip > EPS)
    raw = np.where(needs, order_up_to - ip, 0.0)
    cases = np.ceil(np.round(raw / case, 6))
    qty = np.where(needs, np.maximum(cases * case, moq_units), 0.0)

    # Risk before any new order can arrive (lead-time demand only).
    mu_l = mu * L
    sigma_l = np.sqrt(L * sigma * sigma + mu * mu * varL)
    avail_l = on_hand + on_order
    with np.errstate(invalid="ignore", divide="ignore"):
        k_l = np.where(sigma_l > 0, (avail_l - mu_l) / np.where(sigma_l > 0, sigma_l, 1.0), 0.0)
    p_stockout = np.where(
        sigma_l > 0, 1.0 - norm_cdf_v(k_l), np.where(avail_l < mu_l - EPS, 1.0, 0.0)
    )
    p_stockout = np.where(mu > 0, p_stockout, 0.0)
    # Expected units short before any order placed now could arrive (not fixable by this order).
    short_l = np.where(sigma_l > 0, sigma_l * loss_function_v(k_l), np.maximum(mu_l - avail_l, 0.0))
    short_l = np.where(mu > 0, short_l, 0.0)
    high = (mu > 0) & ((on_hand <= 0) | (p_stockout >= 0.5))
    medium = ~high & (mu > 0) & (ip <= rop + EPS)
    risk = np.where(high, "High", np.where(medium, "Medium", "Low")).astype(object)
    with np.errstate(invalid="ignore", divide="ignore"):
        coverage = np.where(mu > 0, on_hand / np.where(mu > 0, mu, 1.0), np.nan)
    return {
        "lead_time": L,
        "lead_time_sd": sdL,
        "protection_period": P,
        "z": np.full(len(mu), z),
        "sigma_p": sigma_p,
        "safety_stock": ss,
        "safety_stock_normal": ss_normal,
        "rop_normal": rop_normal,
        "rop_empirical": rop_emp,
        "rop_basis": np.where(use_emp, "empirical", "normal").astype(object),
        "reorder_point": rop,
        "eoq": eoq,
        "cycle_stock": cycle,
        "order_up_to": order_up_to,
        "inventory_position": ip,
        "needs_order": needs,
        "raw_quantity": raw,
        "moq_units": moq_units,
        "recommended_qty": qty,
        "coverage_days": coverage,
        "lead_time_demand": mu_l,
        "p_stockout_lead_time": p_stockout,
        "expected_short_lead_time": short_l,
        "risk": risk,
    }


def priority_order(
    risk: np.ndarray, p_stockout: np.ndarray, value_rate: np.ndarray, ids: np.ndarray
) -> np.ndarray:
    """Allocation priority: risk tier, then stockout probability, then margin at risk per day, then id."""
    rank = np.array([RISK_RANK[r] for r in risk])
    return np.lexsort(
        (
            np.asarray(ids).astype(str),
            -np.asarray(value_rate, float),
            -np.round(np.asarray(p_stockout, float), 9),
            rank,
        )
    )


def allocate(
    qty: np.ndarray,
    case_pack: np.ndarray,
    moq_units: np.ndarray,
    unit_cost: np.ndarray,
    supplier: np.ndarray,
    order: np.ndarray,
    capacity: dict[str, float] | None,
    budget: float | None,
    trace: dict[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Greedy constrained allocation in priority order (a transparent heuristic, not an optimum).

    Supplier capacity is applied first, then the purchasing budget. A line that
    cannot be fully funded is reduced to the largest whole-case quantity that
    still meets its MOQ; otherwise it is deferred. Later, cheaper lines may
    still be funded from the remaining budget.

    If ``trace`` is a dict, it receives ``capacity_left`` and ``budget_left``: the
    supplier capacity (units) and budget ($) remaining when each line was considered
    (NaN when the constraint was not evaluated for that line).
    """
    if budget is not None and (not math.isfinite(budget) or budget < 0):
        raise ValueError("budget must be a non-negative number")
    n = len(qty)
    final = np.asarray(qty, float).copy()
    status = np.where(final > 0, "Order", "No order needed").astype(object)
    cap_left = dict(capacity) if capacity is not None else None
    cap_trace = np.full(n, np.nan)
    bud_trace = np.full(n, np.nan)
    for i in order:
        if final[i] <= 0 or cap_left is None:
            continue
        left = cap_left.get(supplier[i], math.inf)
        cap_trace[i] = left
        if final[i] > left + EPS:
            q = math.floor(round(left / case_pack[i], 6)) * case_pack[i]
            if q >= moq_units[i] and q > 0:
                final[i] = q
                status[i] = "Reduced: supplier capacity"
            else:
                final[i] = 0.0
                status[i] = "Deferred: supplier capacity"
        cap_left[supplier[i]] = left - final[i]
    if budget is not None:
        left = float(budget)
        for i in order:
            if final[i] <= 0:
                continue
            cost = final[i] * unit_cost[i]
            bud_trace[i] = left
            if cost > left + 1e-6:
                q = (
                    math.floor(round(left / (case_pack[i] * unit_cost[i]), 6)) * case_pack[i]
                    if unit_cost[i] > 0
                    else final[i]
                )
                if q >= moq_units[i] and q > 0:
                    final[i] = q
                    status[i] = "Reduced: budget"
                else:
                    final[i] = 0.0
                    status[i] = "Deferred: budget"
            left -= final[i] * unit_cost[i]
    assert len(final) == n
    if trace is not None:
        trace["capacity_left"] = cap_trace
        trace["budget_left"] = bud_trace
    return final, status


def exposure(
    ip_after: np.ndarray, mu: np.ndarray, P: np.ndarray, sigma_p: np.ndarray
) -> dict[str, np.ndarray]:
    """Expected shortage and ending stock over the protection period given a post-order position."""
    mu_p = mu * P
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(sigma_p > 0, (ip_after - mu_p) / np.where(sigma_p > 0, sigma_p, 1.0), 0.0)
    esc = np.where(sigma_p > 0, sigma_p * loss_function_v(k), np.maximum(mu_p - ip_after, 0.0))
    p_short = np.where(sigma_p > 0, 1.0 - norm_cdf_v(k), np.where(ip_after < mu_p - EPS, 1.0, 0.0))
    p_short = np.where(mu > 0, p_short, 0.0)
    esc = np.where(mu > 0, esc, 0.0)
    ending = np.maximum(ip_after - mu_p + esc, 0.0)
    return {"expected_short_units": esc, "p_short": p_short, "expected_ending_units": ending}


def steady_state(plan_out: dict, lines: dict, settings: Settings) -> dict[str, np.ndarray]:
    """Annualised textbook approximations for the policy (independent of today's stock).

    Average order Q = max(cycle stock, MOQ) in whole cases; average on-hand = SS+ + Q/2;
    orders/year = 365 mu / Q; expected shortage per cycle = sigma_P * G(SS / sigma_P).
    """
    mu = np.maximum(np.asarray(lines["mu"], float), 0.0)
    case = np.maximum(np.asarray(lines["case_pack"], float), 1.0)
    q = np.maximum(
        np.ceil(np.round(plan_out["cycle_stock"] / case, 6)) * case, plan_out["moq_units"]
    )
    q = np.where(mu > 0, q, 0.0)
    ss = np.maximum(plan_out["safety_stock"], 0.0)
    sp = plan_out["sigma_p"]
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(sp > 0, ss / np.where(sp > 0, sp, 1.0), 0.0)
        esc = np.where(sp > 0, sp * loss_function_v(k), 0.0)
        orders = np.where(q > 0, 365.0 * mu / np.where(q > 0, q, 1.0), 0.0)
        fill = np.where(q > 0, np.clip(1.0 - esc / np.where(q > 0, q, 1.0), 0.0, 1.0), 1.0)
    unit_cost = np.asarray(lines["unit_cost"], float)
    margin = np.maximum(np.asarray(lines["unit_price"], float) - unit_cost, 0.0)
    avg_inv = np.where(mu > 0, ss + q / 2.0, 0.0)
    holding = avg_inv * unit_cost * settings.holding_rate
    ordering = orders * np.asarray(lines["order_cost"], float)
    short_units = esc * orders
    shortage = short_units * margin * settings.shortage_multiplier
    return {
        "avg_order_qty": q,
        "avg_inventory_units": avg_inv,
        "orders_per_year": orders,
        "expected_short_units_per_year": short_units,
        "fill_rate": fill,
        "holding_cost": holding,
        "ordering_cost": ordering,
        "shortage_cost": shortage,
        "total_cost": holding + ordering + shortage,
    }
