"""Planning snapshot: today's replenishment recommendations for the demo scope.

``recommend`` is the reference for the TypeScript planner (app/src/lib/engine).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .inventory.policy import Settings, allocate, exposure, plan, priority_order, steady_state

PRESETS = {
    "balanced": {
        "label": "Balanced",
        "service_level": 0.95,
        "review_period": 7,
        "lead_time_shift": 0.0,
        "lead_time_sd_multiplier": 1.0,
        "budget_share": None,
    },
    "protect": {
        "label": "Protect Availability",
        "service_level": 0.99,
        "review_period": 7,
        "lead_time_shift": 0.0,
        "lead_time_sd_multiplier": 1.0,
        "budget_share": None,
    },
    "limit": {
        "label": "Limit Spending",
        "service_level": 0.95,
        "review_period": 7,
        "lead_time_shift": 0.0,
        "lead_time_sd_multiplier": 1.0,
        "budget_share": 0.6,
    },
}


def line_arrays(lines: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "mu": lines["mu"].to_numpy(float),
        "sigma": lines["sigma"].to_numpy(float),
        "lt_mean": lines["lead_time_mean"].to_numpy(float),
        "lt_sd": lines["lead_time_sd"].to_numpy(float),
        "on_hand": lines["on_hand"].to_numpy(float),
        "on_order": lines["on_order"].to_numpy(float),
        "backorders": np.zeros(len(lines)),
        "moq": lines["moq_units"].to_numpy(float),
        "case_pack": lines["case_pack"].to_numpy(float),
        "unit_cost": lines["unit_cost"].to_numpy(float),
        "unit_price": lines["unit_price"].to_numpy(float),
        "order_cost": lines["order_cost"].to_numpy(float),
        "intermittent": lines["intermittent"].to_numpy(bool),
    }


def reason(row: dict) -> str:
    if row["mu"] <= 0:
        return "No demand is forecast for the next 28 days, so no purchase is recommended."
    ip, rop, s = row["inventory_position"], row["reorder_point"], row["order_up_to"]
    if not row["needs_order"]:
        return f"Inventory position {ip:.0f} is above the reorder point {rop:.1f}; no order is needed at this review."
    text = f"Inventory position {ip:.0f} is at or below the reorder point {rop:.1f}. Ordering up to {s:.1f} needs {row['raw_quantity']:.1f} units"
    notes = []
    if row["recommended_qty"] > np.ceil(round(row["raw_quantity"], 6)):
        if row["recommended_qty"] == row["moq_units"] and row["moq_units"] > row["raw_quantity"]:
            notes.append(f"raised to the {row['moq_units']:.0f}-unit minimum order")
        else:
            notes.append(f"rounded up to whole cases of {row['case_pack']:.0f}")
    text += (
        ", " + " and ".join(notes) if notes else ""
    ) + f" = {row['recommended_qty']:.0f} units."
    st = row["status"]
    sup, cap_left, cap_limit = row["supplier_id"], row["capacity_left"], row["capacity_limit"]
    if st == "Reduced: supplier capacity":
        text += (
            f" Reduced by supplier capacity: {sup} had {cap_left:.0f} of {cap_limit:.0f} units left"
            f" for this review after higher-priority lines, so {row['final_qty']:.0f} units are funded."
        )
    elif st == "Deferred: supplier capacity":
        text += (
            f" Deferred by supplier capacity: {sup} had {cap_left:.0f} of {cap_limit:.0f} units left"
            f" for this review after higher-priority lines, less than this line's {row['moq_units']:.0f}-unit"
            " minimum order. It is reconsidered at the next review."
        )
    elif st == "Reduced: budget":
        text += (
            f" Reduced by budget: ${row['budget_left']:.2f} remained after higher-priority lines,"
            f" so {row['final_qty']:.0f} units are funded."
        )
    elif st == "Deferred: budget":
        text += (
            f" Deferred by budget: ${row['budget_left']:.2f} remained after higher-priority lines,"
            f" less than this line's minimum order cost of ${row['moq_units'] * row['unit_cost']:.2f}."
        )
    return text


def recommend(
    lines: pd.DataFrame,
    history: np.ndarray,
    settings: Settings,
    capacity: dict[str, float] | None,
    planning_day: int,
) -> pd.DataFrame:
    arr = line_arrays(lines)
    p = plan(arr, settings, history=history)
    margin = np.maximum(arr["unit_price"] - arr["unit_cost"], 0)
    order = priority_order(
        p["risk"], p["p_stockout_lead_time"], arr["mu"] * margin, lines["series"].to_numpy()
    )
    cap = None
    if capacity is not None:
        cap = {k: v * settings.review_period / 7.0 for k, v in capacity.items()}
    trace: dict[str, np.ndarray] = {}
    final, status = allocate(
        p["recommended_qty"],
        arr["case_pack"],
        p["moq_units"],
        arr["unit_cost"],
        lines["supplier_id"].to_numpy(),
        order,
        cap,
        settings.budget,
        trace,
    )
    ip_after = p["inventory_position"] + final
    ex = exposure(ip_after, arr["mu"], p["protection_period"], p["sigma_p"])
    ss = steady_state(p, arr, settings)
    out = lines[["series", "item_id", "store_id", "dept_id", "cat_id", "supplier_id"]].copy()
    for k in (
        "lead_time",
        "lead_time_sd",
        "protection_period",
        "z",
        "sigma_p",
        "safety_stock_normal",
        "rop_normal",
        "rop_empirical",
        "safety_stock",
        "rop_basis",
        "reorder_point",
        "eoq",
        "cycle_stock",
        "order_up_to",
        "inventory_position",
        "needs_order",
        "raw_quantity",
        "moq_units",
        "recommended_qty",
        "coverage_days",
        "lead_time_demand",
        "p_stockout_lead_time",
        "expected_short_lead_time",
        "risk",
    ):
        out[k] = p[k]
    out["mu"] = arr["mu"]
    out["sigma"] = arr["sigma"]
    out["on_hand"] = arr["on_hand"]
    out["on_order"] = arr["on_order"]
    out["case_pack"] = arr["case_pack"]
    out["unit_cost"] = arr["unit_cost"]
    out["final_qty"] = final
    out["status"] = status
    # Allocation trace: what was left for this line when it was considered (NaN = not evaluated)
    out["capacity_limit"] = (
        lines["supplier_id"].map(cap).astype(float).to_numpy() if cap is not None else np.nan
    )
    out["capacity_left"] = trace["capacity_left"]
    out["budget_left"] = trace["budget_left"]
    out["order_value"] = np.round(final * arr["unit_cost"], 2)
    out["priority_rank"] = np.empty(len(lines), dtype=int)
    out.loc[order, "priority_rank"] = np.arange(1, len(lines) + 1)
    out["expected_receipt_day"] = np.where(
        final > 0, planning_day + np.rint(p["lead_time"]).astype(int), 0
    )
    for k, v in ex.items():
        out[k] = v
    for k, v in ss.items():
        out[f"annual_{k}"] = v
    out["reason"] = [reason(r) for r in out.to_dict("records")]
    return out


def summarise_recommendations(rec: pd.DataFrame) -> dict:
    return {
        "lines": int(len(rec)),
        "lines_needing_order": int(rec["needs_order"].sum()),
        "lines_funded": int((rec["final_qty"] > 0).sum()),
        "lines_deferred": int(rec["status"].str.startswith("Deferred").sum()),
        "units_ordered": float(rec["final_qty"].sum()),
        "purchase_spend": round(float(rec["order_value"].sum()), 2),
        "high_risk": int((rec["risk"] == "High").sum()),
        "medium_risk": int((rec["risk"] == "Medium").sum()),
        "expected_short_units": float(rec["expected_short_units"].sum()),
        "expected_short_lead_time": float(rec["expected_short_lead_time"].sum()),
        "expected_ending_value": float((rec["expected_ending_units"] * rec["unit_cost"]).sum()),
        "annual_holding_cost": float(rec["annual_holding_cost"].sum()),
        "annual_ordering_cost": float(rec["annual_ordering_cost"].sum()),
        "annual_shortage_cost": float(rec["annual_shortage_cost"].sum()),
        "annual_total_cost": float(rec["annual_total_cost"].sum()),
    }
