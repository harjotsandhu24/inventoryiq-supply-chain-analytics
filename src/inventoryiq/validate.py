"""Data-quality validation for M5-format inputs.

Every check reports what it found. Nothing is silently repaired: records that
fail a rule are counted, listed (up to a sample), and handled by an explicit,
documented rule downstream (see docs/data_cleaning_rules.md).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .config import HORIZON, ID_COLUMNS, RAW_FILES, Windows
from .data_io import Dataset, day_columns


@dataclass
class Check:
    name: str
    category: str
    passed: bool
    detail: str
    value: float | int | None = None
    severity: str = (
        "error"  # "error" fails the pipeline; "warning" is flagged and handled by a rule
    )
    sample: list = field(default_factory=list)


def _check(
    checks: list[Check], name, category, passed, detail, value=None, severity="error", sample=None
):
    checks.append(Check(name, category, bool(passed), detail, value, severity, list(sample or [])))


def validate_files(source_dir: Path) -> list[Check]:
    checks: list[Check] = []
    for f in RAW_FILES:
        p = source_dir / f
        _check(
            checks,
            f"file_present:{f}",
            "files",
            p.exists(),
            f"{p.name} {'found' if p.exists() else 'missing'}",
        )
    return checks


def validate_calendar(cal: pd.DataFrame) -> list[Check]:
    checks: list[Check] = []
    n = len(cal)
    _check(
        checks,
        "calendar_unique_day",
        "calendar",
        cal["d"].is_unique,
        f"{n} rows, {cal['d'].nunique()} unique d keys",
    )
    _check(
        checks,
        "calendar_contiguous_days",
        "calendar",
        (cal["day"].to_numpy() == np.arange(1, n + 1)).all(),
        "d_1..d_N without gaps",
    )
    dates = pd.to_datetime(cal["date"])
    _check(
        checks,
        "calendar_daily_dates",
        "calendar",
        (dates.diff().dropna() == pd.Timedelta(days=1)).all(),
        f"{cal['date'].iloc[0]} to {cal['date'].iloc[-1]}, one row per day",
    )
    _check(
        checks,
        "calendar_weekday_matches_date",
        "calendar",
        (dates.dt.day_name() == cal["weekday"]).all(),
        "weekday label equals the weekday of the date",
    )
    _check(
        checks,
        "calendar_week_monotonic",
        "calendar",
        cal["wm_yr_wk"].is_monotonic_increasing,
        "wm_yr_wk never decreases",
    )
    wk_sizes = cal.groupby("wm_yr_wk").size()
    full = (wk_sizes == 7).sum()
    _check(
        checks,
        "calendar_week_size",
        "calendar",
        (wk_sizes.iloc[:-1] == 7).all() and wk_sizes.iloc[-1] <= 7,
        f"{full} of {len(wk_sizes)} weeks have 7 days",
    )
    for i in (1, 2):
        mismatch = (cal[f"event_name_{i}"].isna() != cal[f"event_type_{i}"].isna()).sum()
        _check(
            checks,
            f"calendar_event_{i}_pairs",
            "calendar",
            mismatch == 0,
            f"{mismatch} rows where event_name_{i} and event_type_{i} disagree on missingness",
        )
    snap_ok = all(cal[c].isin([0, 1]).all() for c in ("snap_CA", "snap_TX", "snap_WI"))
    _check(checks, "calendar_snap_binary", "calendar", snap_ok, "SNAP flags are 0/1")
    return checks


def validate_sales(source_dir: Path, cal: pd.DataFrame) -> tuple[list[Check], pd.DataFrame]:
    checks: list[Check] = []
    ev = pd.read_csv(source_dir / "sales_train_evaluation.csv")
    va = pd.read_csv(source_dir / "sales_train_validation.csv")
    ed, vd = day_columns(ev.columns), day_columns(va.columns)
    _check(
        checks,
        "sales_eval_shape",
        "sales",
        True,
        f"evaluation: {len(ev):,} series x {len(ed):,} days",
        len(ev),
        "info",
    )
    _check(
        checks,
        "sales_valid_shape",
        "sales",
        True,
        f"validation: {len(va):,} series x {len(vd):,} days",
        len(va),
        "info",
    )
    _check(
        checks,
        "sales_eval_day_columns",
        "sales",
        ed == [f"d_{i}" for i in range(1, len(ed) + 1)],
        "evaluation day columns are d_1..d_N in order",
    )
    _check(
        checks,
        "sales_calendar_alignment",
        "sales",
        len(ed) <= len(cal) and set(ed) <= set(cal["d"]),
        f"all {len(ed)} sales days exist in the calendar; calendar extends {len(cal) - len(ed)} days beyond the last observed sale",
    )
    _check(
        checks,
        "sales_unique_id",
        "sales",
        ev["id"].is_unique,
        f"{ev['id'].duplicated().sum()} duplicate series ids",
        int(ev["id"].duplicated().sum()),
    )
    nulls = int(ev.isna().sum().sum())
    _check(checks, "sales_no_nulls", "sales", nulls == 0, f"{nulls} null cells", nulls)
    X = ev[ed].to_numpy()
    neg = int((X < 0).sum())
    _check(checks, "sales_nonnegative", "sales", neg == 0, f"{neg} negative quantities", neg)
    nonint = int((np.round(X) != X).sum())
    _check(
        checks, "sales_integer", "sales", nonint == 0, f"{nonint} non-integer quantities", nonint
    )
    expected_id = ev["item_id"] + "_" + ev["store_id"] + "_evaluation"
    _check(
        checks,
        "sales_id_composition",
        "sales",
        (expected_id == ev["id"]).all(),
        "id = item_id + store_id + suffix for every row",
    )
    h1 = ev.groupby("item_id")[["dept_id", "cat_id"]].nunique().max().max()
    h2 = ev.groupby("store_id")["state_id"].nunique().max()
    h3 = ev.groupby("dept_id")["cat_id"].nunique().max()
    _check(
        checks,
        "sales_hierarchy",
        "sales",
        h1 == 1 and h2 == 1 and h3 == 1,
        "each item maps to one dept/category, each dept to one category, each store to one state",
    )
    pairs = ev.groupby(["item_id", "store_id"]).size()
    _check(
        checks,
        "sales_item_store_unique",
        "sales",
        (pairs == 1).all(),
        f"{(pairs > 1).sum()} duplicated item-store combinations",
    )
    full_grid = ev["item_id"].nunique() * ev["store_id"].nunique() == len(ev)
    _check(
        checks,
        "sales_full_item_store_grid",
        "sales",
        full_grid,
        f"{ev['item_id'].nunique():,} items x {ev['store_id'].nunique()} stores = {len(ev):,} series",
        severity="warning",
    )
    va_ids = va["id"].str.replace("_validation", "", regex=False)
    ev_ids = ev["id"].str.replace("_evaluation", "", regex=False)
    same_ids = va_ids.equals(ev_ids)
    same_vals = same_ids and np.array_equal(va[vd].to_numpy(), X[:, : len(vd)])
    _check(
        checks,
        "validation_file_is_prefix",
        "sales",
        same_ids and same_vals,
        f"validation file equals the first {len(vd)} days of the evaluation file",
    )
    profile = ev[ID_COLUMNS].copy()
    profile["total_units"] = X.sum(1)
    return checks, profile


def validate_prices_and_joins(source_dir: Path, ds: Dataset) -> list[Check]:
    checks: list[Check] = []
    con = duckdb.connect()
    p = con.sql(
        f"select * from read_csv_auto('{(source_dir / 'sell_prices.csv').as_posix()}')"
    ).df()
    _check(checks, "prices_shape", "prices", True, f"{len(p):,} weekly price rows", len(p), "info")
    dup = int(p.duplicated(["store_id", "item_id", "wm_yr_wk"]).sum())
    _check(
        checks,
        "prices_unique_key",
        "prices",
        dup == 0,
        f"{dup} duplicate (store, item, week) keys",
        dup,
    )
    nulls = int(p.isna().sum().sum())
    _check(checks, "prices_no_nulls", "prices", nulls == 0, f"{nulls} null cells", nulls)
    bad = int((p["sell_price"] <= 0).sum())
    _check(checks, "prices_positive", "prices", bad == 0, f"{bad} zero or negative prices", bad)
    weeks = set(ds.calendar["wm_yr_wk"])
    out = int((~p["wm_yr_wk"].isin(weeks)).sum())
    _check(
        checks,
        "prices_weeks_in_calendar",
        "prices",
        out == 0,
        f"{out} price rows reference weeks absent from the calendar",
        out,
    )
    sales_pairs = set(zip(ds.meta["item_id"], ds.meta["store_id"], strict=True))
    price_pairs = set(zip(p["item_id"], p["store_id"], strict=True))
    orphan = len(price_pairs - sales_pairs)
    missing = len(sales_pairs - price_pairs)
    _check(
        checks,
        "prices_pairs_match_sales",
        "prices",
        orphan == 0 and missing == 0,
        f"{orphan} priced pairs without sales; {missing} sales series without any price",
    )
    med = p.groupby(["store_id", "item_id"])["sell_price"].transform("median")
    ratio = p["sell_price"] / med
    outl = p[(ratio > 5) | (ratio < 0.2)]
    _check(
        checks,
        "prices_outliers",
        "prices",
        True,
        f"{len(outl)} weekly prices are >5x or <0.2x the item-store median; flagged, not altered",
        len(outl),
        "warning",
    )
    tiny = int((p["sell_price"] < 0.10).sum())
    _check(
        checks,
        "prices_below_10_cents",
        "prices",
        True,
        f"{tiny} weekly prices below $0.10; kept as observed and excluded from unit-cost medians only if they are outliers",
        tiny,
        "warning",
    )

    # Gaps: weeks without a listed price between first and last listing.
    first = np.argmax(ds.available, axis=1)
    last = ds.available.shape[1] - 1 - np.argmax(ds.available[:, ::-1], axis=1)
    span = last - first + 1
    listed = ds.available.sum(1)
    gaps = int((span != listed).sum())
    _check(
        checks,
        "prices_no_listing_gaps",
        "prices",
        True,
        f"{gaps} series have unlisted days between first and last price",
        gaps,
        "warning",
    )

    # Sales recorded while the item was not listed (would indicate a join/key problem).
    unavailable_sales = int((ds.sales * ~ds.available[:, : ds.last_day]).sum())
    _check(
        checks,
        "sales_only_when_listed",
        "joins",
        unavailable_sales == 0,
        f"{unavailable_sales} units sold on days without a listed price",
        unavailable_sales,
    )

    # Join cardinality: daily sales x calendar x weekly prices must stay one row per series-day.
    con.register("ev_ids", ds.meta[["item_id", "store_id"]])
    con.register("p", p)
    n_days = ds.last_day
    expected_rows = ds.n_series * n_days
    res = con.sql(
        f"""
        with days as (select d, wm_yr_wk from read_csv_auto('{(source_dir / "calendar.csv").as_posix()}')
                      where cast(substr(d, 3) as integer) <= {n_days}),
             grid as (select e.item_id, e.store_id, d.d, d.wm_yr_wk from ev_ids e cross join days d)
        select count(*) as n_rows, count(distinct (g.item_id, g.store_id, g.d)) as n_keys
        from grid g left join p on g.item_id = p.item_id and g.store_id = p.store_id and g.wm_yr_wk = p.wm_yr_wk
        """
    ).fetchone()
    _check(
        checks,
        "join_price_no_fanout",
        "joins",
        res[0] == expected_rows and res[1] == expected_rows,
        f"sales-calendar-price join returns {res[0]:,} rows for {expected_rows:,} series-days (no duplication)",
        int(res[0]),
    )
    return checks


def validate_series_behaviour(ds: Dataset, windows: Windows) -> list[Check]:
    checks: list[Check] = []
    start = ds.availability_start()
    late = int((start > 1).sum())
    _check(
        checks,
        "introduced_after_day_1",
        "series",
        True,
        f"{late:,} series were first listed after d_1; days before listing are treated as 'not available', never as zero demand",
        late,
        "warning",
    )
    hold0 = windows.holdout[0]
    short = int((hold0 - start < 365).sum())
    _check(
        checks,
        "short_history",
        "series",
        True,
        f"{short:,} series have less than 365 listed days before the holdout",
        short,
        "warning",
    )
    recent = ds.sales[:, -90:].sum(1)
    inactive = int((recent == 0).sum())
    _check(
        checks,
        "inactive_last_90_days",
        "series",
        True,
        f"{inactive:,} series sold nothing in the final 90 observed days",
        inactive,
        "warning",
    )
    # Long zero runs while listed: possible stockouts, delistings, or censored demand.
    X = ds.sales
    avail = ds.available[:, : ds.last_day]
    long_run = 0
    for i in range(ds.n_series):
        z = (X[i] == 0) & avail[i]
        if not z.any():
            continue
        dz = np.diff(np.concatenate(([0], z.astype(np.int8), [0])))
        runs = np.flatnonzero(dz == -1) - np.flatnonzero(dz == 1)
        if runs.max() >= 90:
            long_run += 1
    _check(
        checks,
        "long_zero_runs_while_listed",
        "series",
        True,
        f"{long_run:,} series have >=90 consecutive zero-sale days while listed (possible stockouts; true demand is not observed)",
        long_run,
        "warning",
    )
    # Spikes: a day above 10x the series' listed-day mean and at least 20 units.
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(avail.sum(1) > 0, (X * avail).sum(1) / avail.sum(1), 0)
    spikes = (np.maximum(20, 10 * mean[:, None]) <= X) & avail
    _check(
        checks,
        "demand_spikes",
        "series",
        True,
        f"{int(spikes.sum()):,} series-days exceed 10x the series mean (and >=20 units) across {int(spikes.any(1).sum()):,} series; kept as observed",
        int(spikes.sum()),
        "warning",
    )
    zero_share = float((X == 0).mean())
    _check(
        checks,
        "zero_share",
        "series",
        True,
        f"{zero_share:.1%} of all series-days have zero recorded sales",
        round(zero_share, 4),
        "info",
    )
    hold = windows.holdout
    _check(
        checks,
        "holdout_window",
        "design",
        hold[1] == ds.last_day and hold[1] - hold[0] + 1 == HORIZON,
        f"holdout = d_{hold[0]}..d_{hold[1]} ({ds.date_of(hold[0])} to {ds.date_of(hold[1])})",
    )
    vf = windows.validation_folds
    nonoverlap = all(vf[k][1] < vf[k + 1][0] for k in range(len(vf) - 1)) and vf[-1][1] < hold[0]
    _check(
        checks,
        "validation_folds_disjoint",
        "design",
        nonoverlap and len(vf) == 5,
        "; ".join(f"d_{a}-d_{b}" for a, b in vf),
    )
    return checks


def run_validation(source_dir: Path, ds: Dataset, windows: Windows, out_dir: Path) -> dict:
    checks = validate_files(source_dir)
    checks += validate_calendar(ds.calendar)
    sales_checks, _ = validate_sales(source_dir, ds.calendar)
    checks += sales_checks
    checks += validate_prices_and_joins(source_dir, ds)
    checks += validate_series_behaviour(ds, windows)
    errors = [c for c in checks if c.severity == "error" and not c.passed]
    meta = ds.meta
    summary = {
        "source": ds.source,
        "series": int(ds.n_series),
        "items": int(meta["item_id"].nunique()),
        "stores": sorted(meta["store_id"].unique().tolist()),
        "states": sorted(meta["state_id"].unique().tolist()),
        "categories": sorted(meta["cat_id"].unique().tolist()),
        "departments": sorted(meta["dept_id"].unique().tolist()),
        "observed_days": int(ds.last_day),
        "calendar_days": int(ds.n_calendar_days),
        "first_date": ds.date_of(1),
        "last_observed_date": ds.date_of(ds.last_day),
        "calendar_end_date": ds.date_of(ds.n_calendar_days),
        "total_units": int(ds.sales.sum()),
        "holdout": {
            "start_day": windows.holdout[0],
            "end_day": windows.holdout[1],
            "start_date": ds.date_of(windows.holdout[0]),
            "end_date": ds.date_of(windows.holdout[1]),
        },
        "validation_folds": [
            {"start_day": a, "end_day": b, "start_date": ds.date_of(a), "end_date": ds.date_of(b)}
            for a, b in windows.validation_folds
        ],
        "errors": len(errors),
        "warnings": sum(1 for c in checks if c.severity == "warning"),
        "passed": not errors,
    }
    report = {"summary": summary, "checks": [asdict(c) for c in checks]}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data_validation.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "data_validation.md").write_text(render_markdown(report))
    if errors:
        raise RuntimeError("Data validation failed: " + ", ".join(c.name for c in errors))
    return report


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Data validation report",
        "",
        f"Source: **{s['source']}**. Result: **{'PASSED' if s['passed'] else 'FAILED'}** "
        f"({s['errors']} blocking errors, {s['warnings']} flagged warnings).",
        "",
        "| Attribute | Value |",
        "|---|---|",
        f"| Series (item x store) | {s['series']:,} |",
        f"| Items | {s['items']:,} |",
        f"| Stores | {', '.join(s['stores'])} |",
        f"| Categories | {', '.join(s['categories'])} |",
        f"| Departments | {', '.join(s['departments'])} |",
        f"| Observed sales days | {s['observed_days']:,} ({s['first_date']} to {s['last_observed_date']}) |",
        f"| Calendar days | {s['calendar_days']:,} (to {s['calendar_end_date']}) |",
        f"| Total recorded units | {s['total_units']:,} |",
        f"| Holdout | d_{s['holdout']['start_day']}-d_{s['holdout']['end_day']} ({s['holdout']['start_date']} to {s['holdout']['end_date']}) |",
        "",
        "## Checks",
        "",
        "| Check | Category | Severity | Result | Detail |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        res = "pass" if c["passed"] else "FAIL"
        lines.append(
            f"| `{c['name']}` | {c['category']} | {c['severity']} | {res} | {c['detail']} |"
        )
    lines.append("")
    return "\n".join(lines)
