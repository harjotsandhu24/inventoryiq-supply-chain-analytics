"""Auditable day-by-day inventory simulation under a lost-sales model.

Daily sequence for every product-store line
    1. receive purchase orders due today (start of day)
    2. demand = observed M5 sales for the day (a proxy: recorded sales are
       already censored by real stockouts, so true demand may be higher)
    3. fulfilled = min(on_hand, demand); lost = demand - fulfilled
    4. closing = opening + receipts - fulfilled   (never negative)
    5. on review days, after closing, the policy reviews the position using only
       information available that day, applies supplier constraints, and places
       purchase orders that arrive after a realised lead time.

Both policies share starting stock, demand, supplier terms, lead-time draws
(common random numbers keyed by supplier and order day) and cost assumptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .policy import Settings, allocate, plan, priority_order


@dataclass
class SimInputs:
    series: np.ndarray  # ids
    demand: np.ndarray  # (n, days) observed sales during the simulation window
    start_day: int  # M5 day index of column 0
    lines: pd.DataFrame  # line master (case_pack, moq_units, unit_cost, unit_price, supplier_id, lead_time_*, order_cost)
    capacity: dict[str, float]
    lead_time_draws: dict[
        str, np.ndarray
    ]  # supplier -> realised lead time for an order placed on each sim day
    initial_on_hand: np.ndarray
    review_days: np.ndarray  # 0-based sim columns on which reviews happen


def draw_lead_times(suppliers: pd.DataFrame, n_days: int, seed: int) -> dict[str, np.ndarray]:
    """Gamma-distributed lead times rounded to whole days (minimum 1), one draw per supplier per day."""
    rng = np.random.default_rng(seed)
    out = {}
    for row in suppliers.sort_values("supplier_id").itertuples():
        m, s = row.lead_time_mean_days, row.lead_time_sd_days
        shape, scale = (m / s) ** 2, s * s / m
        out[row.supplier_id] = np.maximum(np.rint(rng.gamma(shape, scale, size=n_days)), 1).astype(
            int
        )
    return out


PolicyFn = Callable[[int, np.ndarray, np.ndarray], tuple[np.ndarray, dict]]


def run(inputs: SimInputs, policy: PolicyFn, name: str) -> dict:
    """Run one policy. ``policy(col, on_hand, on_order)`` returns (desired qty, diagnostics)."""
    L = inputs.lines
    n, days = inputs.demand.shape
    max_lt = max(int(v.max()) for v in inputs.lead_time_draws.values())
    arrivals = np.zeros((n, days + max_lt + 2))
    on_hand = inputs.initial_on_hand.astype(float).copy()
    on_order = np.zeros(n)
    rec = {
        k: np.zeros((n, days))
        for k in (
            "opening",
            "receipts",
            "demand",
            "fulfilled",
            "lost",
            "closing",
            "on_order",
            "ordered",
        )
    }
    pos = []
    review_set = set(int(c) for c in inputs.review_days)
    supplier = L["supplier_id"].to_numpy()
    case = L["case_pack"].to_numpy(float)
    moq = L["moq_units"].to_numpy(float)
    cost = L["unit_cost"].to_numpy(float)
    for t in range(days):
        rec["opening"][:, t] = on_hand
        r = arrivals[:, t]
        on_hand = on_hand + r
        on_order = on_order - r
        d = inputs.demand[:, t].astype(float)
        f = np.minimum(on_hand, d)
        on_hand = on_hand - f
        rec["receipts"][:, t] = r
        rec["demand"][:, t] = d
        rec["fulfilled"][:, t] = f
        rec["lost"][:, t] = d - f
        rec["closing"][:, t] = on_hand
        if t in review_set:
            qty, diag = policy(t, on_hand.copy(), on_order.copy())
            order = priority_order(
                diag["risk"], diag["p_stockout"], diag["value_rate"], inputs.series
            )
            final, _ = allocate(qty, case, moq, cost, supplier, order, inputs.capacity, None)
            for i in np.flatnonzero(final > 0):
                lt = int(inputs.lead_time_draws[supplier[i]][t])
                arrive = t + lt
                arrivals[i, arrive] += final[i]
                pos.append(
                    {
                        "policy": name,
                        "series": inputs.series[i],
                        "order_day": inputs.start_day + t,
                        "quantity": int(final[i]),
                        "unit_cost": cost[i],
                        "supplier_id": supplier[i],
                        "lead_time_realised": lt,
                        "expected_arrival_day": inputs.start_day
                        + t
                        + int(round(L["lead_time_mean"].iloc[i])),
                        "arrival_day": inputs.start_day + arrive,
                    }
                )
            on_order = on_order + final
            rec["ordered"][:, t] = final
        rec["on_order"][:, t] = on_order
    # Invariant: opening + receipts - fulfilled = closing, and stock never negative.
    bal = rec["opening"] + rec["receipts"] - rec["fulfilled"] - rec["closing"]
    if np.abs(bal).max() > 1e-9 or rec["closing"].min() < 0:
        raise AssertionError("inventory balance invariant violated")
    po = pd.DataFrame(pos)
    if len(po):
        prefix = {"basic": "BAS", "forecast_v1": "FV1", "forecast": "FV2"}.get(
            name, name[:3].upper()
        )
        po.insert(0, "po_id", [f"{prefix}-{k:06d}" for k in range(1, len(po) + 1)])
        last_day = inputs.start_day + days - 1
        po["status"] = np.where(po["arrival_day"] <= last_day, "received", "in transit")
        if po.duplicated(["series", "order_day"]).any():
            raise AssertionError("duplicate purchase orders for a line on one day")
    return {
        "name": name,
        "ledger": rec,
        "purchase_orders": po,
        "final_on_hand": on_hand,
        "final_on_order": on_order,
    }


def basic_policy_factory(
    inputs: SimInputs, history: np.ndarray, hist_listed: np.ndarray, cfg: dict
) -> PolicyFn:
    """Status-quo rule: min/max days of cover on the trailing 28-day average of recorded sales.

    ``history`` is (n, H + days) sales with the simulation window at the end; the
    rule only reads columns up to and including the review day.
    """
    L = inputs.lines
    lt = L["lead_time_mean"].to_numpy(float)
    case = L["case_pack"].to_numpy(float)
    moq = L["moq_units"].to_numpy(float)
    margin = (L["unit_price"] - L["unit_cost"]).to_numpy(float)
    offset = history.shape[1] - inputs.demand.shape[1]
    w = cfg["avg_window"]

    def policy(t: int, on_hand: np.ndarray, on_order: np.ndarray):
        end = offset + t + 1
        win = history[:, end - w : end]
        lst = hist_listed[:, end - w : end]
        with np.errstate(invalid="ignore", divide="ignore"):
            avg = np.where(lst.sum(1) > 0, (win * lst).sum(1) / lst.sum(1), 0.0)
        mn = avg * (lt + cfg["min_days_after_lead_time"])
        mx = avg * (lt + cfg["max_days_after_lead_time"])
        ip = on_hand + on_order
        needs = (ip <= mn) & (mx - ip > 1e-9) & (avg > 0)
        raw = np.where(needs, mx - ip, 0.0)
        qty = np.where(
            needs,
            np.maximum(np.ceil(np.round(raw / case, 6)) * case, np.ceil(moq / case) * case),
            0.0,
        )
        risk = np.where(
            needs & (on_hand <= avg * lt), "High", np.where(needs, "Medium", "Low")
        ).astype(object)
        return qty, {"risk": risk, "p_stockout": np.zeros(len(qty)), "value_rate": avg * margin}

    return policy


def forecast_policy_factory(
    inputs: SimInputs,
    mu_by_review: dict[int, np.ndarray],
    sigma: np.ndarray,
    intermittent: np.ndarray,
    history: np.ndarray,
    hist_listed: np.ndarray,
    settings: Settings,
) -> PolicyFn:
    """Forecast-informed (R, s, S) policy using the reference ``plan`` function."""
    L = inputs.lines
    offset = history.shape[1] - inputs.demand.shape[1]
    base = {
        "sigma": sigma,
        "lt_mean": L["lead_time_mean"].to_numpy(float),
        "lt_sd": L["lead_time_sd"].to_numpy(float),
        "moq": L["moq_units"].to_numpy(float),
        "case_pack": L["case_pack"].to_numpy(float),
        "unit_cost": L["unit_cost"].to_numpy(float),
        "unit_price": L["unit_price"].to_numpy(float),
        "order_cost": L["order_cost"].to_numpy(float),
        "intermittent": intermittent,
    }
    margin = (L["unit_price"] - L["unit_cost"]).to_numpy(float)

    def policy(t: int, on_hand: np.ndarray, on_order: np.ndarray):
        end = offset + t + 1
        hist = np.where(hist_listed[:, end - 364 : end], history[:, end - 364 : end], np.nan)
        lines = dict(
            base,
            mu=mu_by_review[t],
            on_hand=on_hand,
            on_order=on_order,
            backorders=np.zeros(len(on_hand)),
        )
        out = plan(lines, settings, history=hist)
        return out["recommended_qty"], {
            "risk": out["risk"],
            "p_stockout": out["p_stockout_lead_time"],
            "value_rate": mu_by_review[t] * margin,
        }

    return policy


def summarise(
    result: dict,
    lines: pd.DataFrame,
    review_days: np.ndarray,
    holding_rate: float,
    shortage_multiplier: float,
    margin_override: float | None = None,
) -> dict:
    """Service and cost metrics. Purchase spend is reported separately and is NOT part of modeled cost."""
    rec = result["ledger"]
    po = result["purchase_orders"]
    price = lines["unit_price"].to_numpy(float)
    if margin_override is None:
        cost = lines["unit_cost"].to_numpy(float)
    else:
        cost = np.round(price * (1 - margin_override), 2)
    unit_margin = np.maximum(price - cost, 0)
    days = rec["demand"].shape[1]
    demand = rec["demand"].sum()
    fulfilled = rec["fulfilled"].sum()
    lost = rec["lost"].sum()
    holding = float((rec["closing"] * cost[:, None]).sum() * holding_rate / 365.0)
    order_cost_line = lines.set_index("series")["order_cost"]
    ordering = float(po["series"].map(order_cost_line).sum()) if len(po) else 0.0
    shortage = float((rec["lost"].sum(1) * unit_margin).sum() * shortage_multiplier)
    spend = float((rec["ordered"] * cost[:, None]).sum())
    # Cycle service level: share of (line, review cycle) pairs with demand and no lost sales.
    bounds = list(review_days) + [days]
    cyc_ok = cyc_n = 0
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        d = rec["demand"][:, a + 1 : b + 1].sum(1)
        lo = rec["lost"][:, a + 1 : b + 1].sum(1)
        has = d > 0
        cyc_n += int(has.sum())
        cyc_ok += int((has & (lo == 0)).sum())
    return {
        "policy": result["name"],
        "lines": int(len(lines)),
        "days": int(days),
        "demand_units": float(demand),
        "fulfilled_units": float(fulfilled),
        "lost_units": float(lost),
        "fill_rate": float(fulfilled / demand) if demand > 0 else None,
        "cycle_service_level": float(cyc_ok / cyc_n) if cyc_n else None,
        "stockout_days": int((rec["lost"] > 0).sum()),
        "lines_with_stockout": int((rec["lost"].sum(1) > 0).sum()),
        "avg_inventory_units": float(rec["closing"].sum(0).mean()),
        "avg_inventory_value": float((rec["closing"] * cost[:, None]).sum(0).mean()),
        "ending_inventory_value": float((rec["closing"][:, -1] * cost).sum()),
        "ending_on_order_value": float((result["final_on_order"] * cost).sum()),
        "purchase_orders": int(len(po)),
        "purchase_units": float(rec["ordered"].sum()),
        "purchasing_spend": round(spend, 2),
        "holding_cost": round(holding, 2),
        "ordering_cost": round(ordering, 2),
        "shortage_penalty": round(shortage, 2),
        "modeled_total_cost": round(holding + ordering + shortage, 2),
    }
