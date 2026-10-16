"use client";

import { useMemo } from "react";
import type { Recommendation } from "@/lib/engine/engine";
import { days, int, pct } from "@/lib/format";
import type { Supplier } from "@/lib/types";
import { Card } from "./ui";

/** Explains supplier-capacity limits for the current review, computed from the same recommendations the table shows. */
export function CapacityCard({ recs, suppliers }: { recs: Recommendation[]; suppliers: Supplier[] }) {
  const rows = useMemo(() => {
    return suppliers
      .map((s) => {
        const mine = recs.filter((r) => r.supplier === s.supplier_id);
        const need = mine.filter((r) => r.needsOrder);
        const limit = mine.find((r) => r.capacityLimit !== null)?.capacityLimit ?? null;
        const requested = need.reduce((a, r) => a + r.recommendedQty, 0);
        const funded = mine.reduce((a, r) => a + r.finalQty, 0);
        return {
          id: s.supplier_id,
          name: s.supplier_name.replace(" (simulated)", ""),
          leadTime: s.lead_time_mean_days,
          limit,
          requested,
          funded,
          deferred: mine.filter((r) => r.status === "Deferred: supplier capacity").length,
          reduced: mine.filter((r) => r.status === "Reduced: supplier capacity").length,
        };
      })
      .filter((r) => r.requested > 0);
  }, [recs, suppliers]);
  const deferred = recs.filter((r) => r.status === "Deferred: supplier capacity");
  const deferredHigh = deferred.filter((r) => r.risk === "High").length;
  const minCover = deferred.reduce((m, r) => (r.coverageDays !== null && r.coverageDays < m ? r.coverageDays : m), Infinity);
  if (rows.length === 0) return null;
  return (
    <Card title="Supplier capacity this review (simulated)" id="capacity" aside={<span className="text-xs text-muted">Units each supplier can ship per 7-day review</span>}>
      <div className="grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="capacity-table">
            <caption className="sr-only">Requested and funded units by supplier against weekly capacity</caption>
            <thead>
              <tr className="border-b border-line text-xs uppercase text-muted">
                <th scope="col" className="py-1.5 pr-2 text-left">Supplier</th>
                <th scope="col" className="px-2 py-1.5 text-right">Capacity</th>
                <th scope="col" className="px-2 py-1.5 text-right">Requested</th>
                <th scope="col" className="px-2 py-1.5 text-right">Funded</th>
                <th scope="col" className="px-2 py-1.5 text-left">Load</th>
                <th scope="col" className="px-2 py-1.5 text-right">Deferred</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const load = r.limit ? r.requested / r.limit : null;
                return (
                  <tr key={r.id} className="border-b border-line/70">
                    <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                      <span className="font-medium text-navy">{r.id}</span> <span className="text-xs text-muted">{r.name} · {r.leadTime} d lead time</span>
                    </th>
                    <td className="tabular px-2 py-1.5 text-right">{r.limit === null ? "none" : int(r.limit)}</td>
                    <td className="tabular px-2 py-1.5 text-right">{int(r.requested)}</td>
                    <td className="tabular px-2 py-1.5 text-right">{int(r.funded)}</td>
                    <td className="px-2 py-1.5">
                      {load !== null && (
                        <div className="flex items-center gap-2" title={`Requested is ${pct(load, 0)} of capacity`}>
                          <div className="h-2 w-24 overflow-hidden rounded bg-canvas" aria-hidden>
                            <div className={`h-full ${load > 1 ? "bg-risk-high" : "bg-teal"}`} style={{ width: `${Math.min(load, 1) * 100}%` }} />
                          </div>
                          <span className={`tabular text-xs ${load > 1 ? "font-semibold text-risk-high" : "text-muted"}`}>{pct(load, 0)}</span>
                        </div>
                      )}
                    </td>
                    <td className="tabular px-2 py-1.5 text-right">
                      {r.deferred > 0 ? <span className="text-risk-high">{r.deferred}</span> : "0"}
                      {r.reduced > 0 && <span className="block text-xs text-risk-med">{r.reduced} reduced</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="space-y-2 rounded-md bg-canvas p-3 text-sm leading-snug" data-testid="capacity-explainer">
          <p>
            <strong className="text-navy">Why orders are deferred.</strong> Stock on hand comes from the simpler status-quo rule, which holds less than this
            policy targets. Catching up in one week asks some suppliers for more than they can ship.
          </p>
          <p>
            Capacity goes to the highest-risk lines first. {deferred.length > 0 ? (
              <>
                The <strong>{deferred.length}</strong> deferred lines include <strong>{deferredHigh}</strong> high-risk lines
                {Number.isFinite(minCover) && minCover > 0 && <> and all have at least <strong>{days(minCover)}</strong> of stock on hand</>}. They are reconsidered at the next review.
              </>
            ) : (
              "No line is deferred at these settings."
            )}
          </p>
          <p className="text-xs text-muted">Capacities are simulated assumptions (1.5–1.8x each supplier&apos;s average weekly volume).</p>
        </div>
      </div>
    </Card>
  );
}
