"""End-to-end checks on the synthetic pipeline run: database, SQL, exports, Excel, scenarios."""

from __future__ import annotations

import json
from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd
import pytest

from inventoryiq import config as C
from inventoryiq.inventory.policy import Settings
from inventoryiq.planning import recommend

SQL_FILES = sorted((C.SQL_DIR / "analysis").glob("*.sql"))


def _strict_load(path):
    def bad(x):
        raise ValueError(f"invalid JSON number {x} in {path}")

    return json.loads(path.read_text(), parse_constant=bad)


def test_integrity_checks_all_pass(pipeline_run):
    checks = json.loads((pipeline_run["reports"] / "integrity_checks.json").read_text())
    assert len(checks) >= 15
    assert all(c["violations"] == 0 for c in checks), [c for c in checks if c["violations"]]


@pytest.mark.parametrize("sql_file", SQL_FILES, ids=[p.name for p in SQL_FILES])
def test_analysis_sql_runs_and_returns_rows(pipeline_run, sql_file):
    con = duckdb.connect(str(pipeline_run["processed"] / "inventoryiq.duckdb"), read_only=True)
    df = con.execute(sql_file.read_text()).df()
    con.close()
    assert len(df) > 0, sql_file.name
    assert not df.columns.duplicated().any()


def test_sql_aggregates_reconcile_with_python(pipeline_run):
    con = duckdb.connect(str(pipeline_run["processed"] / "inventoryiq.duckdb"), read_only=True)
    db_total = con.execute("SELECT SUM(units) FROM daily_sales").fetchone()[0]
    sim = con.execute(
        """SELECT policy, lost_units, demand_units FROM simulation_summary WHERE scope='demo' AND "window"='main' ORDER BY policy"""
    ).df()
    led = con.execute(
        "SELECT policy, SUM(lost) lost, SUM(demand) demand FROM inventory_ledger WHERE scope='demo' GROUP BY 1 ORDER BY 1"
    ).df()
    rec_total = con.execute(
        "SELECT SUM(order_value) FROM replenishment_recommendations"
    ).fetchone()[0]
    con.close()
    ev = pd.read_csv(C.SYNTHETIC_DIR / "sales_train_evaluation.csv")
    assert db_total == ev.filter(like="d_").to_numpy().sum()
    np.testing.assert_allclose(sim["lost_units"], led["lost"])
    np.testing.assert_allclose(sim["demand_units"], led["demand"])
    assert float(rec_total) == pytest.approx(
        pipeline_run["summary"]["planning"]["purchase_spend"], abs=0.01
    )


def test_app_json_is_valid_and_has_no_nan(pipeline_run):
    app = pipeline_run["app_dir"]
    for name in (
        "manifest.json",
        "lines.json",
        "evaluation.json",
        "simulation.json",
        "suppliers.json",
        "reference_plan.json",
    ):
        _strict_load(app / name)
    files = list((app / "forecasts").glob("*.json"))
    lines = _strict_load(app / "lines.json")
    assert len(files) == len(lines) > 0
    for f in files[:20]:
        d = _strict_load(f)
        assert len(d["holdout"]["actual"]) == 28 and len(d["future"]["selected"]) == 28
        assert all(v is None or v >= 0 for v in d["future"]["lo80"])
    manifest = _strict_load(app / "manifest.json")
    assert manifest["source"] == "synthetic" and "not Walmart" in manifest["sourceLabel"]


def test_reference_plan_reproduces_from_exported_inputs(pipeline_run):
    """Recompute the plan from the exported line inputs; must equal the exported reference."""
    app = pipeline_run["app_dir"]
    lines = _strict_load(app / "lines.json")
    ref = _strict_load(app / "reference_plan.json")
    L = pd.DataFrame(
        {
            "series": [x["id"] for x in lines],
            "item_id": [x["item"] for x in lines],
            "store_id": [x["store"] for x in lines],
            "dept_id": [x["dept"] for x in lines],
            "cat_id": [x["cat"] for x in lines],
            "supplier_id": [x["supplier"] for x in lines],
            "mu": [x["mu"] for x in lines],
            "sigma": [x["sigma"] for x in lines],
            "lead_time_mean": [x["ltMean"] for x in lines],
            "lead_time_sd": [x["ltSd"] for x in lines],
            "on_hand": [x["onHand"] for x in lines],
            "on_order": [x["onOrder"] for x in lines],
            "moq_units": [x["moq"] for x in lines],
            "case_pack": [x["casePack"] for x in lines],
            "unit_cost": [x["unitCost"] for x in lines],
            "unit_price": [x["unitPrice"] for x in lines],
            "order_cost": [x["orderCost"] for x in lines],
            "intermittent": [x["intermittent"] for x in lines],
        }
    )
    hist = np.array(
        [[np.nan if v is None else v for v in x["history"]] for x in lines], dtype=float
    )
    s = ref["settings"]
    settings = Settings(
        service_level=s["serviceLevel"],
        review_period=s["reviewPeriod"],
        holding_rate=s["holdingRate"],
        shortage_multiplier=s["shortageMultiplier"],
    )
    r = recommend(L, hist, settings, ref["capacity"], ref["planningDay"]).set_index("series")
    for sid, exp in ref["results"].items():
        assert r.loc[sid, "final_qty"] == exp["final_qty"]
        assert r.loc[sid, "status"] == exp["status"]
        assert r.loc[sid, "reorder_point"] == pytest.approx(exp["reorder_point"], abs=1e-9)


def test_exported_csv_matches_reference_plan(pipeline_run):
    csv = pd.read_csv(
        pipeline_run["deliverables"] / "csv" / "replenishment_recommendations.csv"
    ).set_index("series")
    ref = _strict_load(pipeline_run["app_dir"] / "reference_plan.json")["results"]
    for sid, exp in ref.items():
        assert csv.loc[sid, "final_qty"] == exp["final_qty"]
        assert csv.loc[sid, "order_value"] == pytest.approx(exp["order_value"], abs=0.005)


def test_excel_workbook_validates_against_python(pipeline_run):
    from inventoryiq.excel_workbook import validate

    res = validate(pipeline_run["deliverables"] / "InventoryIQ_Analysis.xlsx", "synthetic")
    assert res["passed"], res


def test_scenarios_are_reproducible_and_isolated(pipeline_run):
    csv = pipeline_run["deliverables"] / "csv"
    L = pd.read_csv(csv / "planning_inputs.csv")
    app = pipeline_run["app_dir"]
    lines = _strict_load(app / "lines.json")
    hist = np.array(
        [[np.nan if v is None else v for v in x["history"]] for x in lines], dtype=float
    )
    ref = _strict_load(app / "reference_plan.json")
    base = Settings(service_level=0.95, review_period=7)
    a = recommend(L, hist, base, ref["capacity"], 1)
    _ = recommend(
        L,
        hist,
        replace(base, service_level=0.99, budget=10.0, lead_time_shift=5),
        ref["capacity"],
        1,
    )
    b = recommend(L, hist, base, ref["capacity"], 1)
    pd.testing.assert_frame_equal(a, b)  # no state leaks between scenario runs
    hi = recommend(L, hist, replace(base, service_level=0.99), ref["capacity"], 1)
    assert hi["safety_stock"].sum() > a["safety_stock"].sum()
    lim = recommend(
        L, hist, replace(base, budget=float(a["order_value"].sum()) * 0.5), ref["capacity"], 1
    )
    assert lim["order_value"].sum() <= a["order_value"].sum() * 0.5 + 0.01
    assert lim["expected_short_units"].sum() >= a["expected_short_units"].sum() - 1e-9


def test_simulation_policies_share_identical_conditions(pipeline_run):
    sim = pd.read_csv(pipeline_run["reports"] / "simulation_summary.csv")
    assert set(sim["window"]) == {"main", "confirmation"}
    for key, g in sim.groupby(["scope", "window"]):
        assert g["demand_units"].nunique() == 1, key
        assert g["lines"].nunique() == 1
        assert set(g["policy"]) == {"basic", "forecast_v1", "forecast"}
        for r in g.itertuples():
            assert r.modeled_total_cost == pytest.approx(
                r.holding_cost + r.ordering_cost + r.shortage_penalty, abs=0.011
            )
            assert r.fulfilled_units + r.lost_units == pytest.approx(r.demand_units)


def test_holdout_not_used_for_selection(pipeline_run):
    """Selection must be reproducible from validation errors alone."""
    v = json.loads((pipeline_run["reports"] / "data_validation.json").read_text())["summary"]
    assert all(f["end_day"] < v["holdout"]["start_day"] for f in v["validation_folds"])
    counts = pd.read_csv(pipeline_run["reports"] / "forecast_selection_counts.csv")
    assert counts["series"].sum() > 0


def test_parity_fixture_written(pipeline_run):
    fx = _strict_load(pipeline_run["processed"] / "parity_cases.json")
    names = [c["name"] for c in fx["cases"]]
    assert {"balanced", "protect", "limit", "edge_cases"} <= set(names)
