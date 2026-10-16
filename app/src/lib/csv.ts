// CSV export of on-screen engine results. Values come straight from the same
// Recommendation objects the tables render, so exports always match the screen.

import type { Recommendation } from "./engine/engine";
import type { LineData } from "./types";

function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(Math.round(v * 1e6) / 1e6) : "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const cols = Object.keys(rows[0]);
  return [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n") + "\n";
}

export function recommendationRows(recs: Recommendation[], lines: Map<string, LineData>, receiptDate: (r: Recommendation) => string) {
  return recs.map((r) => {
    const l = lines.get(r.id);
    return {
      series: r.id,
      item: l?.item ?? "",
      store: l?.store ?? "",
      category: l?.cat ?? "",
      supplier: r.supplier,
      risk: r.risk,
      priority_rank: r.priorityRank,
      on_hand: r.onHand,
      on_order: r.onOrder,
      inventory_position: r.inventoryPosition,
      expected_daily_demand: r.mu,
      forecast_error_sd: r.sigma,
      lead_time_days: r.leadTime,
      protection_period_days: r.protectionPeriod,
      safety_stock: r.safetyStock,
      reorder_point: r.reorderPoint,
      order_up_to: r.orderUpTo,
      recommended_qty: r.recommendedQty,
      funded_qty: r.finalQty,
      status: r.status,
      unit_cost: r.unitCost,
      order_value: r.orderValue,
      expected_receipt_date: r.finalQty > 0 ? receiptDate(r) : "",
      coverage_days: r.coverageDays,
      stockout_probability_before_receipt: r.pStockoutLeadTime,
      reason: r.reason,
    };
  });
}

/** Trigger a browser download of text content (local application only). */
export function downloadText(filename: string, text: string, mime = "text/csv") {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
