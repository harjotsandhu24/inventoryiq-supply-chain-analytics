"""Build the analyst workbook (live Excel formulas) from pipeline CSV exports, and validate it.

Regenerate without rerunning the pipeline:
    python -m inventoryiq.excel_workbook --source m5
Validate formulas against the Python reference engine:
    python -m inventoryiq.excel_workbook --source m5 --validate
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from . import config as C

NAVY, TEAL, SLATE, TEXT = "172D47", "217E83", "F1F4F7", "3E4B5B"
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
INPUT_FILL = PatternFill("solid", fgColor="FFF7E0")
SUB_FILL = PatternFill("solid", fgColor=SLATE)
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color=NAVY)
NOTE_FONT = Font(italic=True, size=9, color=TEXT)
THIN = Border(bottom=Side(style="thin", color="D5DBE3"))
FIRST = 5  # first data row on table sheets (title, note, blank, header)

FMT_INT = "#,##0"
FMT_1 = "#,##0.0"
FMT_2 = "#,##0.00"
FMT_USD = "$#,##0.00"
FMT_USD0 = "$#,##0"
FMT_PCT = "0.0%"
FMT_PCT2 = "0.00%"

# Assumption cells (Assumptions sheet, column C)
A = {
    "csl": "Assumptions!$C$5",
    "review": "Assumptions!$C$6",
    "lt_shift": "Assumptions!$C$7",
    "lt_mult": "Assumptions!$C$8",
    "hold": "Assumptions!$C$9",
    "penalty": "Assumptions!$C$10",
    "maxdays": "Assumptions!$C$11",
    "z": "Assumptions!$C$12",
}


def _title(ws: Worksheet, title: str, note: str) -> None:
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = note
    ws["A2"].font = NOTE_FONT
    ws.sheet_view.showGridLines = False


def _header(ws: Worksheet, row: int, headers: list[str], widths: list[int] | None = None) -> None:
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=j, value=h)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 32
    for j, w in enumerate(widths or [14] * len(headers), 1):
        ws.column_dimensions[get_column_letter(j)].width = w


def _table(ws: Worksheet, headers, widths, rows, formats, freeze_col="C") -> int:
    _header(ws, FIRST - 1, headers, widths)
    for i, row in enumerate(rows):
        r = FIRST + i
        for j, v in enumerate(row, 1):
            if isinstance(v, float) and not math.isfinite(v):
                v = None
            c = ws.cell(row=r, column=j, value=v)
            fmt = formats[j - 1]
            if fmt:
                c.number_format = fmt
            c.border = THIN
    last = FIRST + len(rows) - 1
    ws.freeze_panes = f"{freeze_col}{FIRST}"
    ws.auto_filter.ref = f"A{FIRST - 1}:{get_column_letter(len(headers))}{max(last, FIRST)}"
    return last


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def load_inputs(source: str) -> dict:
    csv = C.DELIVERABLES_DIR / source / "csv"
    rep = C.REPORTS_DIR / source
    return {
        "lines": pd.read_csv(csv / "planning_inputs.csv"),
        "rec": pd.read_csv(
            csv / "replenishment_recommendations.csv", keep_default_na=False, na_values=[""]
        ),
        "scen": pd.read_csv(csv / "scenario_summary.csv"),
        "sim": pd.read_csv(csv / "simulation_summary.csv"),
        "sens": pd.read_csv(csv / "simulation_sensitivity.csv"),
        "sup": pd.read_csv(csv / "suppliers.csv"),
        "eval": pd.read_csv(rep / "forecast_holdout_by_method_model_stores.csv"),
        "coverage": pd.read_csv(rep / "forecast_interval_coverage_model_stores.csv"),
        "manifest": json.loads((csv / "planning_settings.json").read_text()),
        "source": source,
    }


def build_workbook_from_files(source: str, out: Path) -> Path:
    return write_workbook(load_inputs(source), out)


def build_workbook(ctx: dict, out: Path) -> Path:
    """Pipeline hook: CSVs have already been exported for ``ctx['source']``."""
    return build_workbook_from_files(ctx["source"], out)


def write_workbook(d: dict, out: Path) -> Path:
    L = d["lines"].reset_index(drop=True)
    rec = d["rec"].set_index("series").loc[L["series"]].reset_index()
    n = len(L)
    last = FIRST + n - 1
    wb = Workbook()
    src_label = (
        "Walmart M5 sales (licensed local copy)"
        if d["source"] == "m5"
        else "SYNTHETIC demo data - not Walmart data"
    )
    planning_date = str(rec["planning_date"].iloc[0]) if "planning_date" in rec else ""

    # ---------------- README
    ws = wb.active
    ws.title = "README"
    _title(
        ws,
        "InventoryIQ - Inventory Forecasting & Replenishment Workbook",
        f"Data source: {src_label}. Planning date: {planning_date}.",
    )
    lines = [
        (
            "Purpose",
            "Working analyst view of the InventoryIQ planning engine: demand forecasts, safety stock, reorder points, and purchase recommendations.",
        ),
        (
            "How to use",
            "Change the yellow cells on the Assumptions sheet. Safety Stock, Reorder Points, Inventory Summary and Purchase Recs recalculate with live formulas.",
        ),
        (
            "Not recalculated in Excel",
            "Forecasts, budget/capacity allocation and the historical simulation are produced by the Python engine and pasted as values (labelled 'Python').",
        ),
        ("Lineage: OBSERVED", "Recorded M5 sales, prices and calendar."),
        (
            "Lineage: DERIVED",
            "Statistics calculated directly from observed data (ABC/XYZ, demand pattern, list price).",
        ),
        (
            "Lineage: MODELED",
            "Forecasts, forecast error, safety stock, reorder points, recommendations.",
        ),
        (
            "Lineage: SIMULATED",
            "Suppliers, lead times, MOQs, case packs, unit costs, stock on hand, purchase orders and all financial results. These are assumptions, not Walmart operations.",
        ),
        (
            "Refresh",
            "python -m inventoryiq.pipeline --source m5   (full run)   or   python -m inventoryiq.excel_workbook --source m5   (workbook only).",
        ),
        (
            "Validation",
            "python -m inventoryiq.excel_workbook --source m5 --validate recalculates every formula and compares it with the Python reference engine.",
        ),
        (
            "Sheets",
            "Assumptions | Inventory Summary | ABC_XYZ | Forecasts | Safety Stock | Reorder Points | Purchase Recs | Suppliers | Scenarios | Data Definitions",
        ),
    ]
    for i, (k, v) in enumerate(lines, 4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True, color=NAVY)
        ws.cell(row=i, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[i].height = 30
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 120

    # ---------------- Assumptions
    ws = wb.create_sheet("Assumptions")
    _title(
        ws,
        "Planning assumptions",
        "Yellow cells are inputs. Defaults match the application's Balanced scenario.",
    )
    _header(ws, 4, ["Parameter", "Unit", "Value", "Lineage", "Notes"], [34, 14, 14, 12, 80])
    m = d["manifest"].get("defaults", {})
    rows = [
        (
            "Target cycle service level",
            "probability",
            m.get("serviceLevel", 0.95),
            "Assumed",
            "Probability of no stockout per replenishment cycle (not the fill rate).",
        ),
        (
            "Review interval R",
            "days",
            m.get("reviewPeriod", 7),
            "Assumed",
            "Days between purchasing reviews.",
        ),
        (
            "Lead-time shift",
            "days",
            m.get("leadTimeShift", 0.0),
            "Assumed",
            "Added to every supplier's mean lead time (min 1 day).",
        ),
        (
            "Lead-time variability multiplier",
            "x",
            m.get("leadTimeSdMultiplier", 1.0),
            "Assumed",
            "Multiplies each supplier's lead-time standard deviation.",
        ),
        (
            "Annual holding cost rate",
            "% of cost",
            C.FIN.annual_holding_rate,
            "Simulated",
            "Capital, storage and obsolescence per unit-year.",
        ),
        (
            "Shortage penalty multiplier",
            "x margin",
            C.FIN.shortage_penalty_multiplier,
            "Simulated",
            "Penalty per lost unit = multiplier x unit gross margin.",
        ),
        (
            "Maximum days of supply per order",
            "days",
            m.get("maxCycleDays", 28),
            "Assumed",
            "Policy v2 lot-size cap: cycle stock <= mu x this many days.",
        ),
    ]
    for i, (a_, b, c, dd, e) in enumerate(rows, 5):
        ws.cell(row=i, column=1, value=a_)
        ws.cell(row=i, column=2, value=b)
        cell = ws.cell(row=i, column=3, value=c)
        cell.fill = INPUT_FILL
        cell.number_format = FMT_PCT if b in ("probability", "% of cost") else FMT_2
        ws.cell(row=i, column=4, value=dd)
        ws.cell(row=i, column=5, value=e)
    ws["A12"] = "z = NORMSINV(service level)"
    ws["B12"] = "std. normal"
    ws["C12"] = f"=NORMSINV({A['csl']})"
    ws["C12"].number_format = "0.0000"
    ws["E12"] = "Normal quantile used in the safety-stock formula."
    ws["A14"] = "Settings equal defaults?"
    ws["C14"] = (
        f'=IF(AND({A["csl"]}={m.get("serviceLevel", 0.95)},{A["review"]}={m.get("reviewPeriod", 7)},{A["lt_shift"]}={m.get("leadTimeShift", 0.0)},{A["lt_mult"]}={m.get("leadTimeSdMultiplier", 1.0)},{A["maxdays"]}={m.get("maxCycleDays", 28)}),"YES","NO")'
    )
    ws["E14"] = (
        "Empirical fallback reorder points and Python check columns are valid only when this reads YES."
    )
    ws["A16"] = "Safety stock formula"
    ws["E16"] = (
        "SS = z x SQRT(P x sigma_d^2 + mu_d^2 x Var[L]),  P = E[L] + R  (periodic-review protection period)"
    )
    ws["A17"] = "Reorder point"
    ws["E17"] = (
        "s = mu_d x P + SS; for intermittent/lumpy items s = max(s, empirical CSL-quantile of P-day demand)"
    )
    ws["A18"] = "Order-up-to level"
    ws["E18"] = (
        "S = s + min(max(EOQ, mu_d x R), mu_d x max days);  EOQ = SQRT(2 x 365 x mu_d x order cost / (holding rate x unit cost))"
    )
    ws["A19"] = "Order quantity"
    ws["E19"] = (
        "If IP <= s: Q = max(CEILING((S - IP) / case) x case, MOQ);  IP = on hand + on order (lost-sales model, no backorders)"
    )
    for r in range(16, 20):
        ws.cell(row=r, column=1).font = Font(bold=True, color=NAVY)

    # ---------------- Suppliers
    ws = wb.create_sheet("Suppliers")
    _title(
        ws,
        "Supplier assumptions (SIMULATED)",
        "Fictional suppliers assigned by department. Capacity is units per 7-day review.",
    )
    sup = d["sup"]
    cap = d["manifest"].get("capacity", {})
    s_rows = []
    for i, r in enumerate(sup.itertuples()):
        row = FIRST + i
        s_rows.append(
            [
                r.supplier_id,
                r.supplier_name,
                r.departments,
                r.lead_time_mean_days,
                r.lead_time_sd_days,
                f"=MAX(D{row}+{A['lt_shift']},1)",
                f"=E{row}*{A['lt_mult']}",
                r.moq_cases,
                r.order_cost_per_line,
                _f(cap.get(r.supplier_id)),
                r.on_time_rate_assumed,
                f"=COUNTIF('Purchase Recs'!$D${FIRST}:$D${last},A{row})",
                f"=SUMIF('Purchase Recs'!$D${FIRST}:$D${last},A{row},'Purchase Recs'!$K${FIRST}:$K${last})",
            ]
        )
    _table(
        ws,
        [
            "Supplier",
            "Name",
            "Departments",
            "Base lead time (d)",
            "Base LT sd (d)",
            "Lead time used (d)",
            "LT sd used (d)",
            "MOQ (cases)",
            "Order cost / line",
            "Capacity (units/wk)",
            "On-time rate (assumed)",
            "Lines",
            "Recommended spend",
        ],
        [10, 36, 22, 12, 12, 12, 12, 10, 12, 14, 12, 8, 16],
        s_rows,
        [
            None,
            None,
            None,
            FMT_1,
            FMT_1,
            FMT_1,
            FMT_2,
            FMT_INT,
            FMT_USD,
            FMT_INT,
            FMT_PCT,
            FMT_INT,
            FMT_USD,
        ],
        "B",
    )

    # ---------------- Safety Stock
    ws = wb.create_sheet("Safety Stock")
    _title(
        ws,
        "Safety stock (MODELED)",
        "Live formulas. mu and sigma come from the Python forecasting engine; lead times are SIMULATED supplier terms.",
    )
    rows = []
    for i, r in enumerate(L.itertuples()):
        row = FIRST + i
        rr = rec.iloc[i]
        rows.append(
            [
                r.series,
                r.item_id,
                r.store_id,
                r.cat_id,
                r.pattern,
                _f(r.mu),
                _f(r.sigma),
                _f(r.lead_time_mean),
                _f(r.lead_time_sd),
                f"=MAX(H{row}+{A['lt_shift']},1)",
                f"=I{row}*{A['lt_mult']}",
                f"={A['review']}",
                f"=J{row}+L{row}",
                f"=SQRT(M{row}*G{row}^2+F{row}^2*K{row}^2)",
                f"={A['z']}",
                f"=O{row}*N{row}",
                f"=F{row}*M{row}+P{row}",
                _f(rr["rop_empirical"]) if bool(r.intermittent) else None,
                bool(r.intermittent),
                f"=IF(AND(S{row},ISNUMBER(R{row})),IF(R{row}>Q{row},R{row},Q{row}),Q{row})",
                f"=T{row}-F{row}*M{row}",
                _f(rr["reorder_point"]),
                f'=IF(ABS(T{row}-V{row})<0.01,"OK","CHECK")',
            ]
        )
    _table(
        ws,
        [
            "Series",
            "Item",
            "Store",
            "Category",
            "Demand pattern",
            "mu: daily demand",
            "sigma: daily error",
            "Base lead time",
            "Base LT sd",
            "E[L] used",
            "sd(L) used",
            "R (days)",
            "P = E[L]+R",
            "sigma_P",
            "z",
            "SS (normal)",
            "ROP (normal)",
            "Empirical ROP (Python, default P)",
            "Intermittent?",
            "ROP used",
            "Safety stock used",
            "Python ROP",
            "Check vs Python",
        ],
        [24, 16, 7, 11, 12, 10, 10, 9, 9, 9, 9, 7, 9, 9, 7, 10, 10, 13, 10, 10, 10, 10, 10],
        rows,
        [
            None,
            None,
            None,
            None,
            None,
            "0.000",
            "0.000",
            FMT_1,
            FMT_1,
            FMT_1,
            FMT_2,
            FMT_INT,
            FMT_1,
            FMT_2,
            "0.000",
            FMT_2,
            FMT_2,
            FMT_1,
            None,
            FMT_2,
            FMT_2,
            FMT_2,
            None,
        ],
    )

    # ---------------- Reorder Points
    ws = wb.create_sheet("Reorder Points")
    _title(
        ws,
        "Reorder points, order-up-to levels and order quantities (MODELED)",
        "Live formulas referencing the Safety Stock sheet. On-hand and on-order stock are SIMULATED.",
    )
    rows = []
    for i, r in enumerate(L.itertuples()):
        row = FIRST + i
        rr = rec.iloc[i]
        ss = "'Safety Stock'!"
        rows.append(
            [
                r.series,
                r.item_id,
                r.store_id,
                f"={ss}F{row}",
                f"={ss}T{row}",
                _f(r.unit_cost),
                _f(r.order_cost),
                f"=F{row}*{A['hold']}",
                f"=IF(AND(D{row}>0,H{row}>0),SQRT(2*365*D{row}*G{row}/H{row}),0)",
                f"=MIN(MAX(I{row},D{row}*{A['review']}),D{row}*{A['maxdays']})",
                f"=E{row}+J{row}",
                int(r.on_hand),
                int(r.on_order),
                f"=L{row}+M{row}",
                f"=AND(N{row}<=E{row}+0.000000001,K{row}-N{row}>0.000000001)",
                f"=IF(O{row},K{row}-N{row},0)",
                int(r.case_pack),
                int(r.moq_units),
                f"=IF(O{row},MAX(CEILING(ROUND(P{row}/Q{row},6),1)*Q{row},CEILING(R{row}/Q{row},1)*Q{row}),0)",
                f'=IF(D{row}>0,L{row}/D{row},"no demand")',
                int(rr["recommended_qty"]),
                f'=IF(S{row}=U{row},"OK","CHECK")',
            ]
        )
    _table(
        ws,
        [
            "Series",
            "Item",
            "Store",
            "mu",
            "Reorder point s",
            "Unit cost",
            "Order cost",
            "Holding $/unit/yr",
            "EOQ",
            "Cycle stock",
            "Order-up-to S",
            "On hand",
            "On order",
            "Inventory position",
            "Order needed?",
            "Raw need",
            "Case pack",
            "MOQ (units)",
            "Recommended qty",
            "Coverage (days)",
            "Python qty",
            "Check vs Python",
        ],
        [24, 16, 7, 9, 10, 9, 9, 10, 9, 9, 10, 9, 9, 10, 9, 9, 8, 9, 11, 10, 9, 10],
        rows,
        [
            None,
            None,
            None,
            "0.000",
            FMT_2,
            FMT_USD,
            FMT_USD,
            FMT_USD,
            FMT_1,
            FMT_1,
            FMT_2,
            FMT_INT,
            FMT_INT,
            FMT_INT,
            None,
            FMT_2,
            FMT_INT,
            FMT_INT,
            FMT_INT,
            FMT_1,
            FMT_INT,
            None,
        ],
    )

    # ---------------- Purchase Recs
    ws = wb.create_sheet("Purchase Recs")
    budget = rec["budget"].iloc[0] if "budget" in rec.columns else None
    _title(
        ws,
        "Purchase recommendations",
        "Recommended qty is live (Reorder Points). Funded qty applies supplier capacity and budget in priority order (Python allocation, values).",
    )
    rows = []
    for i, r in enumerate(L.itertuples()):
        row = FIRST + i
        rr = rec.iloc[i]
        rows.append(
            [
                r.series,
                r.item_id,
                r.store_id,
                r.supplier_id,
                rr["risk"],
                int(rr["priority_rank"]),
                f"='Reorder Points'!S{row}",
                int(rr["final_qty"]),
                rr["status"],
                _f(r.unit_cost),
                f"=H{row}*J{row}",
                str(rr.get("expected_receipt_date", "") or ""),
                rr["reason"],
            ]
        )
    last_pr = _table(
        ws,
        [
            "Series",
            "Item",
            "Store",
            "Supplier",
            "Risk",
            "Priority",
            "Recommended qty (live)",
            "Funded qty (Python)",
            "Status",
            "Unit cost",
            "Order value",
            "Expected receipt",
            "Reason",
        ],
        [24, 16, 7, 9, 8, 8, 12, 12, 24, 9, 12, 12, 90],
        rows,
        [
            None,
            None,
            None,
            None,
            None,
            FMT_INT,
            FMT_INT,
            FMT_INT,
            None,
            FMT_USD,
            FMT_USD,
            None,
            None,
        ],
    )
    tr = last_pr + 2
    ws.cell(row=tr, column=10, value="Total").font = Font(bold=True)
    ws.cell(row=tr, column=11, value=f"=SUM(K{FIRST}:K{last_pr})").number_format = FMT_USD
    ws.cell(row=tr, column=11).font = Font(bold=True)
    ws.cell(row=tr + 1, column=10, value="Lines funded")
    ws.cell(row=tr + 1, column=11, value=f'=COUNTIF(H{FIRST}:H{last_pr},">0")')
    ws.cell(row=tr + 2, column=10, value="Budget")
    ws.cell(
        row=tr + 2,
        column=11,
        value="Unconstrained"
        if budget in (None, "") or (isinstance(budget, float) and math.isnan(budget))
        else budget,
    )

    # ---------------- Inventory Summary
    ws = wb.create_sheet("Inventory Summary", 2)
    _title(
        ws,
        "Inventory summary (SIMULATED stock, MODELED risk)",
        "Simulated on-hand stock at the planning date valued at simulated unit cost.",
    )
    rows = []
    for i, r in enumerate(L.itertuples()):
        row = FIRST + i
        rr = rec.iloc[i]
        rows.append(
            [
                r.series,
                r.item_id,
                r.store_id,
                r.cat_id,
                r.supplier_id,
                int(r.on_hand),
                int(r.on_order),
                _f(r.unit_cost),
                f"=F{row}*H{row}",
                f"='Reorder Points'!T{row}",
                rr["risk"],
                _f(rr["p_stockout_lead_time"]),
            ]
        )
    last_is = _table(
        ws,
        [
            "Series",
            "Item",
            "Store",
            "Category",
            "Supplier",
            "On hand",
            "On order",
            "Unit cost",
            "Inventory value",
            "Coverage (days)",
            "Risk",
            "P(stockout before receipt)",
        ],
        [24, 16, 7, 11, 9, 9, 9, 9, 13, 11, 8, 13],
        rows,
        [None, None, None, None, None, FMT_INT, FMT_INT, FMT_USD, FMT_USD, FMT_1, None, FMT_PCT],
    )
    col = 14
    ws.cell(row=FIRST - 1, column=col, value="Summary").font = Font(bold=True, color=NAVY)
    stores = sorted(L["store_id"].unique())
    cats = sorted(L["cat_id"].unique())
    ws.cell(row=FIRST, column=col, value="Inventory value").font = Font(bold=True)
    for j, s in enumerate(stores):
        ws.cell(row=FIRST, column=col + 1 + j, value=s).font = Font(bold=True)
    for i, ccat in enumerate(cats):
        rr_ = FIRST + 1 + i
        ws.cell(row=rr_, column=col, value=ccat)
        for j, _s in enumerate(stores):
            c = ws.cell(
                row=rr_,
                column=col + 1 + j,
                value=f"=SUMIFS($I${FIRST}:$I${last_is},$D${FIRST}:$D${last_is},$N{rr_},$C${FIRST}:$C${last_is},{get_column_letter(col + 1 + j)}${FIRST})",
            )
            c.number_format = FMT_USD0
    rr_ = FIRST + 2 + len(cats)
    ws.cell(row=rr_, column=col, value="Lines by risk").font = Font(bold=True)
    for k, risk in enumerate(("High", "Medium", "Low")):
        ws.cell(row=rr_ + 1 + k, column=col, value=risk)
        for j, _s in enumerate(stores):
            ws.cell(
                row=rr_ + 1 + k,
                column=col + 1 + j,
                value=f"=COUNTIFS($K${FIRST}:$K${last_is},$N{rr_ + 1 + k},$C${FIRST}:$C${last_is},{get_column_letter(col + 1 + j)}${FIRST})",
            )
    ws.column_dimensions[get_column_letter(col)].width = 16

    # ---------------- ABC_XYZ
    ws = wb.create_sheet("ABC_XYZ", 3)
    _title(
        ws,
        "ABC (value) and XYZ (variability) segmentation (DERIVED)",
        "Last 364 observed days. A <80% cumulative value, B <95%, C remainder. X CV<=0.5, Y<=1.0, Z >1.0 (weekly CV).",
    )
    srt = (
        L.assign(_v=L["sales_value_364"].fillna(0))
        .sort_values("_v", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    rec_abc = d["rec"].set_index("series")
    rows = []
    for i, r in enumerate(srt.itertuples()):
        row = FIRST + i
        cv = _f(r.weekly_cv)
        rows.append(
            [
                r.series,
                r.cat_id,
                r.store_id,
                _f(r.units_364),
                _f(r.sales_value_364),
                f"=E{row}/SUM($E${FIRST}:$E${last})",
                f"=SUM($E${FIRST}:E{row})/SUM($E${FIRST}:$E${last})-F{row}",
                f'=IF(E{row}<=0,"C",IF(G{row}<0.8,"A",IF(G{row}<0.95,"B","C")))',
                cv,
                f'=IF(ISNUMBER(I{row}),IF(I{row}<=0.5,"X",IF(I{row}<=1,"Y","Z")),"Z")',
                f"=H{row}&J{row}",
                rec_abc.loc[r.series, "abc"] + rec_abc.loc[r.series, "xyz"],
            ]
        )
    _table(
        ws,
        [
            "Series",
            "Category",
            "Store",
            "Units (364d)",
            "Sales value (364d)",
            "Value share",
            "Cumulative share before item",
            "ABC",
            "Weekly CV",
            "XYZ",
            "Class",
            "Python class",
        ],
        [24, 11, 7, 11, 14, 10, 13, 6, 10, 6, 7, 9],
        rows,
        [None, None, None, FMT_INT, FMT_USD, FMT_PCT2, FMT_PCT, None, FMT_2, None, None, None],
        "B",
    )
    mc = 14
    ws.cell(row=FIRST - 1, column=mc, value="Lines by class").font = Font(bold=True, color=NAVY)
    for j, x in enumerate("XYZ"):
        ws.cell(row=FIRST, column=mc + 1 + j, value=x).font = Font(bold=True)
    for i, a_ in enumerate("ABC"):
        ws.cell(row=FIRST + 1 + i, column=mc, value=a_).font = Font(bold=True)
        for j, x in enumerate("XYZ"):
            ws.cell(
                row=FIRST + 1 + i,
                column=mc + 1 + j,
                value=f'=COUNTIFS($H${FIRST}:$H${last},"{a_}",$J${FIRST}:$J${last},"{x}")',
            )

    # ---------------- Forecasts
    ws = wb.create_sheet("Forecasts", 4)
    _title(
        ws,
        "Demand forecasts (MODELED, Python)",
        "28-day forecasts after the last observed day. Holdout = final 28 observed days, never used for selection or tuning.",
    )
    rows = []
    for i, r in enumerate(L.itertuples()):
        row = FIRST + i
        rows.append(
            [
                r.series,
                r.item_id,
                r.store_id,
                r.cat_id,
                r.pattern,
                r.method,
                _f(r.mu),
                _f(r.forecast_28d_total),
                _f(r.sigma),
                _f(r.holdout_mae_selected),
                _f(r.holdout_wape_selected),
                _f(r.holdout_wape_naive),
                f'=IF(AND(ISNUMBER(K{row}),ISNUMBER(L{row}),L{row}>0),1-K{row}/L{row},"n/a")',
            ]
        )
    last_fc = _table(
        ws,
        [
            "Series",
            "Item",
            "Store",
            "Category",
            "Pattern",
            "Selected method",
            "mu (units/day)",
            "28-day forecast",
            "sigma (daily error)",
            "Holdout MAE",
            "Holdout WAPE",
            "Seasonal-naive WAPE",
            "WAPE improvement vs naive",
        ],
        [24, 16, 7, 11, 12, 16, 10, 11, 10, 10, 10, 11, 12],
        rows,
        [
            None,
            None,
            None,
            None,
            None,
            None,
            "0.000",
            FMT_1,
            "0.000",
            "0.000",
            FMT_PCT,
            FMT_PCT,
            FMT_PCT,
        ],
    )
    er = last_fc + 3
    ws.cell(
        row=er, column=1, value="Holdout accuracy by method - model stores, all series (Python)"
    ).font = Font(bold=True, color=NAVY)
    hdr = ["Method", "Series", "MAE", "WAPE", "Bias", "MASE"]
    for j, h in enumerate(hdr, 1):
        c = ws.cell(row=er + 1, column=j, value=h)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for i, r in enumerate(d["eval"].itertuples()):
        vals = [r.method_label, r.series_windows, r.mae, r.wape, r.bias, r.mase]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=er + 2 + i, column=j, value=_f(v) if j > 1 else v)
            c.number_format = [None, FMT_INT, "0.000", FMT_PCT, FMT_PCT, "0.000"][
                j - 1
            ] or "General"

    # ---------------- Scenarios
    ws = wb.create_sheet("Scenarios")
    _title(
        ws,
        "Scenario and policy comparisons (Python engine, values)",
        "Scenarios recompute today's plan from the same immutable baseline. Simulation results are SIMULATED.",
    )
    sc = d["scen"]
    hdr = [
        "Scenario",
        "Service level",
        "Review (d)",
        "LT shift (d)",
        "LT sd x",
        "Budget",
        "Lines ordering",
        "Lines deferred",
        "Purchase spend",
        "High-risk lines",
        "Exp. short (cycle)",
        "Annual holding",
        "Annual ordering",
        "Annual shortage",
        "Annual total",
    ]
    _header(ws, 4, hdr, [18, 10, 9, 9, 8, 12, 10, 10, 13, 10, 11, 12, 12, 12, 12])
    for i, r in enumerate(sc.itertuples()):
        vals = [
            r.scenario_id,
            r.service_level,
            r.review_period,
            r.lead_time_shift,
            r.lead_time_sd_mult,
            "Unconstrained" if pd.isna(r.budget) else r.budget,
            r.lines_funded,
            r.lines_deferred,
            r.purchase_spend,
            r.high_risk,
            r.expected_short_units,
            r.annual_holding_cost,
            r.annual_ordering_cost,
            r.annual_shortage_cost,
            r.annual_total_cost,
        ]
        fm = [
            None,
            FMT_PCT,
            FMT_INT,
            FMT_1,
            FMT_1,
            FMT_USD0,
            FMT_INT,
            FMT_INT,
            FMT_USD0,
            FMT_INT,
            FMT_1,
            FMT_USD0,
            FMT_USD0,
            FMT_USD0,
            FMT_USD0,
        ]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=5 + i, column=j, value=v)
            if fm[j - 1]:
                c.number_format = fm[j - 1]
    sr = 5 + len(sc) + 2
    ws.cell(
        row=sr,
        column=1,
        value="Historical simulation: basic vs forecast-informed policies (SIMULATED, 182 days each window)",
    ).font = Font(bold=True, color=NAVY)
    order = {
        "demo": 0,
        "model_stores": 1,
        "main": 0,
        "confirmation": 1,
        "basic": 0,
        "forecast_v1": 1,
        "forecast": 2,
    }
    sim = d["sim"].assign(
        _k=lambda x: (
            x["window"].map(order) * 10 + x["scope"].map(order) * 3 + x["policy"].map(order)
        )
    )
    sim = sim.sort_values("_k").reset_index(drop=True)
    cols = [
        "window",
        "scope",
        "policy_label",
        "lines",
        "fill_rate",
        "cycle_service_level",
        "lost_units",
        "stockout_days",
        "avg_inventory_value",
        "purchase_orders",
        "purchasing_spend",
        "holding_cost",
        "ordering_cost",
        "shortage_penalty",
        "modeled_total_cost",
    ]
    labels = [
        "Window",
        "Scope",
        "Policy",
        "Lines",
        "Fill rate",
        "Cycle service level",
        "Lost units",
        "Stockout days",
        "Avg inventory value",
        "POs",
        "Purchasing spend (not a cost)",
        "Holding cost",
        "Ordering cost",
        "Shortage penalty",
        "Modeled total cost",
    ]
    fm = [
        None,
        None,
        None,
        FMT_INT,
        FMT_PCT2,
        FMT_PCT,
        FMT_INT,
        FMT_INT,
        FMT_USD0,
        FMT_INT,
        FMT_USD0,
        FMT_USD0,
        FMT_USD0,
        FMT_USD0,
        FMT_USD0,
    ]
    for j, h in enumerate(labels, 1):
        c = ws.cell(row=sr + 1, column=j, value=h)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(wrap_text=True)
    for i, r in enumerate(sim[cols].itertuples(index=False)):
        for j, v in enumerate(r, 1):
            c = ws.cell(row=sr + 2 + i, column=j, value=v)
            if fm[j - 1]:
                c.number_format = fm[j - 1]
    chart = BarChart()
    chart.type = "col"
    chart.title = "Modeled cost components - main window, demo scope"
    chart.y_axis.title = "$"
    data = Reference(ws, min_col=12, max_col=14, min_row=sr + 1, max_row=sr + 4)
    cats_ref = Reference(ws, min_col=3, min_row=sr + 2, max_row=sr + 4)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.height, chart.width = 7, 16
    ws.add_chart(chart, f"B{sr + len(sim) + 4}")
    se = sr + len(sim) + 20
    ws.cell(
        row=se,
        column=1,
        value="Cost sensitivity (decisions held fixed; margin and shortage penalty varied)",
    ).font = Font(bold=True, color=NAVY)
    sens = d["sens"]
    sens = (
        sens[
            (sens["scope"] == "demo")
            & (sens["window"] == "main")
            & (sens["order_cost_multiplier"] == 1.0)
        ]
        .pivot_table(
            index=["margin_shift", "shortage_multiplier"],
            columns="policy",
            values="modeled_total_cost",
        )
        .reset_index()
    )
    sens = sens[["margin_shift", "shortage_multiplier", "basic", "forecast_v1", "forecast"]]
    for j, h in enumerate(
        [
            "Margin shift",
            "Shortage multiplier",
            "Basic: total cost",
            "Forecast v1: total cost",
            "Forecast v2: total cost",
            "v2 - basic",
        ],
        1,
    ):
        c = ws.cell(row=se + 1, column=j, value=h)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(wrap_text=True)
    for i, r in enumerate(sens.itertuples(index=False)):
        row = se + 2 + i
        ws.cell(row=row, column=1, value=r[0]).number_format = "+0%;-0%;0%"
        ws.cell(row=row, column=2, value=r[1]).number_format = "0.0x"
        ws.cell(row=row, column=3, value=r[2]).number_format = FMT_USD0
        ws.cell(row=row, column=4, value=r[3]).number_format = FMT_USD0
        ws.cell(row=row, column=5, value=r[4]).number_format = FMT_USD0
        ws.cell(row=row, column=6, value=f"=E{row}-C{row}").number_format = FMT_USD0

    # ---------------- Data Definitions
    ws = wb.create_sheet("Data Definitions")
    _title(
        ws,
        "Data definitions and lineage",
        "OBSERVED = M5 records; DERIVED = computed from observed; MODELED = forecasts and plans; SIMULATED = assumptions.",
    )
    defs = [
        ("Series", "Product-store combination (M5 item_id + store_id).", "OBSERVED"),
        (
            "mu",
            "Expected daily demand: mean of the selected model's 28-day forecast after the last observed day.",
            "MODELED",
        ),
        (
            "sigma",
            "Std. deviation (RMSE) of daily forecast errors across five 28-day validation folds.",
            "MODELED",
        ),
        (
            "Demand pattern",
            "Syntetos-Boylan class from average inter-demand interval (1.32) and squared CV of demand sizes (0.49).",
            "DERIVED",
        ),
        (
            "ABC / XYZ",
            "ABC on cumulative 364-day sales value; XYZ on coefficient of variation of weekly demand.",
            "DERIVED",
        ),
        (
            "Lead time, LT sd",
            "Supplier mean lead time and its standard deviation in days.",
            "SIMULATED",
        ),
        (
            "Case pack, MOQ",
            "Units per case set from item velocity; MOQ = supplier minimum cases x case pack.",
            "SIMULATED",
        ),
        (
            "Unit price",
            "Median weekly shelf price over the 364 days before the simulation start.",
            "OBSERVED/DERIVED",
        ),
        ("Unit cost", "Unit price x (1 - assumed category gross margin).", "SIMULATED"),
        (
            "On hand / on order",
            "Ending state of the 182-day simulation of the basic policy at the planning date.",
            "SIMULATED",
        ),
        (
            "Safety stock",
            "z x sigma_P (normal) or the empirical-quantile fallback for intermittent items.",
            "MODELED",
        ),
        ("Reorder point s", "Demand over the protection period plus safety stock.", "MODELED"),
        ("Order-up-to S", "s + max(EOQ, one review period of demand).", "MODELED"),
        ("Recommended qty", "Unconstrained order: whole cases, at least the MOQ.", "MODELED"),
        (
            "Funded qty",
            "After supplier capacity and budget, allocated in priority order (greedy heuristic, not an optimum).",
            "MODELED",
        ),
        (
            "Risk",
            "High: expected to run out before a new order could arrive (P >= 50% or no stock). Medium: at/below reorder point. Low: otherwise.",
            "MODELED",
        ),
        ("Fill rate", "Simulated share of demand units fulfilled from stock.", "SIMULATED"),
        (
            "Cycle service level",
            "Simulated share of replenishment cycles with no lost sales (differs from fill rate).",
            "SIMULATED",
        ),
        (
            "Modeled total cost",
            "Holding + ordering + shortage penalty. Purchasing spend is reported separately and is not counted as a cost.",
            "SIMULATED",
        ),
    ]
    _table(ws, ["Field", "Definition", "Lineage"], [22, 110, 18], defs, [None, None, None], "B")

    order = [
        "README",
        "Assumptions",
        "Inventory Summary",
        "ABC_XYZ",
        "Forecasts",
        "Safety Stock",
        "Reorder Points",
        "Purchase Recs",
        "Suppliers",
        "Scenarios",
        "Data Definitions",
    ]
    wb._sheets = [wb[s] for s in order]
    for s in wb.worksheets:
        s.sheet_properties.tabColor = NAVY if s.title in ("README", "Assumptions") else TEAL
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def validate(path: Path, source: str) -> dict:
    """Recalculate every formula with the `formulas` engine and compare with Python values."""
    import formulas

    d = load_inputs(source)
    L = d["lines"].reset_index(drop=True)
    rec = d["rec"].set_index("series").loc[L["series"]].reset_index()
    xl = formulas.ExcelModel().loads(str(path)).finish()
    sol = xl.calculate()
    name = path.name

    def val(sheet, cell):
        key = f"'[{name}]{sheet.upper()}'!{cell}"
        v = sol[key].value
        return v[0][0] if hasattr(v, "__getitem__") else v

    n = len(L)
    rop_diff, ss_diff, qty_mismatch = [], [], []
    errors = 0
    for i in range(n):
        row = FIRST + i
        rop = float(val("Safety Stock", f"T{row}"))
        ss = float(val("Safety Stock", f"U{row}"))
        q = float(val("Reorder Points", f"S{row}"))
        rop_diff.append(abs(rop - rec["reorder_point"].iloc[i]))
        ss_diff.append(abs(ss - rec["safety_stock"].iloc[i]))
        if round(q) != int(rec["recommended_qty"].iloc[i]):
            qty_mismatch.append(L["series"].iloc[i])
    for sheet, cols in (("Inventory Summary", "IJ"), ("Purchase Recs", "K"), ("ABC_XYZ", "FGHJ")):
        for c in cols:
            for i in range(n):
                v = val(sheet, f"{c}{FIRST + i}")
                if str(v).startswith("#"):
                    errors += 1
    abc_mismatch = sum(
        1
        for i in range(n)
        if str(val("ABC_XYZ", f"K{FIRST + i}")) != str(val("ABC_XYZ", f"L{FIRST + i}"))
    )
    total_excel = float(val("Purchase Recs", f"K{FIRST + n + 1}"))
    total_py = float(rec["order_value"].sum())
    result = {
        "lines": n,
        "max_abs_rop_diff": max(rop_diff),
        "max_abs_ss_diff": max(ss_diff),
        "recommended_qty_mismatches": qty_mismatch,
        "abc_xyz_mismatches": abc_mismatch,
        "formula_errors": errors,
        "purchase_total_excel": round(total_excel, 2),
        "purchase_total_python": round(total_py, 2),
        "passed": max(rop_diff) < 0.01
        and not qty_mismatch
        and abc_mismatch == 0
        and errors == 0
        and abs(total_excel - total_py) < 0.05,
    }
    (C.REPORTS_DIR / source / "excel_validation.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["m5", "synthetic"], default="m5")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    out = C.DELIVERABLES_DIR / args.source / "InventoryIQ_Analysis.xlsx"
    build_workbook_from_files(args.source, out)
    print(f"wrote {out}")
    if args.validate:
        print(json.dumps(validate(out, args.source), indent=2))


if __name__ == "__main__":
    main()
