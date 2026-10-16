"use client";

import { useMemo, useState } from "react";
import { recommend, type Recommendation } from "@/lib/engine/engine";
import { addDays, days, int, longDate, num, pct, usd } from "@/lib/format";
import type { LineData, Manifest } from "@/lib/types";
import { Button, RiskBadge, StatusText } from "./ui";

interface Props {
  rec: Recommendation;
  line: LineData;
  manifest: Manifest;
  inList: boolean;
  onToggleList: () => void;
  onClose: () => void;
}

export function receiptDate(manifest: Manifest, r: Recommendation): string {
  return addDays(manifest.planningDate, r.expectedReceiptDay - manifest.planningDay);
}

type Lineage = "Observed" | "Derived" | "Modeled" | "Simulated" | "Synthetic";
const LINEAGE_STYLE: Record<Lineage, string> = {
  Observed: "bg-navy-50 text-navy",
  Derived: "bg-navy-50 text-navy",
  Modeled: "bg-teal-50 text-teal-700",
  Simulated: "bg-risk-med-bg text-risk-med",
  Synthetic: "bg-amber-100 text-navy",
};

export function LineageTag({ kind }: { kind: Lineage }) {
  return <span className={`ml-1.5 rounded px-1 py-px align-middle text-[10px] font-semibold uppercase tracking-wide ${LINEAGE_STYLE[kind]}`}>{kind}</span>;
}

function Row({ label, formula, value, strong, lineage }: { label: string; formula?: string; value: string; strong?: boolean; lineage?: Lineage }) {
  return (
    <tr className="border-b border-line/70 align-top">
      <th scope="row" className="py-1.5 pr-2 text-left font-normal text-ink">
        {label}
        {lineage && <LineageTag kind={lineage} />}
        {formula && <div className="font-mono text-[11px] leading-snug text-muted">{formula}</div>}
      </th>
      <td className={`tabular py-1.5 text-right ${strong ? "font-semibold text-navy" : "text-ink"}`}>{value}</td>
    </tr>
  );
}

export function CalculationPanel({ rec: r, line: l, manifest, inList, onToggleList, onClose }: Props) {
  const [sl, setSl] = useState(manifest.defaults.serviceLevel);
  const [shift, setShift] = useState(0);
  const whatIf = useMemo(() => {
    if (sl === manifest.defaults.serviceLevel && shift === 0) return null;
    const s = { ...manifest.defaults, serviceLevel: sl, leadTimeShift: shift };
    return recommend([l], s, null, manifest.planningDay)[0];
  }, [sl, shift, l, manifest]);
  const unconstrained = useMemo(() => recommend([l], manifest.defaults, null, manifest.planningDay)[0], [l, manifest]);

  const funded = r.finalQty > 0;
  return (
    <aside aria-label={`Purchasing calculation for ${l.id}`} className="rounded-lg border border-line bg-white" data-testid="detail-panel">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-navy">{l.item}</h2>
          <p className="text-xs text-muted">
            Store {l.store} · {l.dept} · Supplier {l.supplier} (simulated)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RiskBadge risk={r.risk} />
          <button type="button" onClick={onClose} aria-label="Close calculation panel" className="rounded px-2 py-1 text-muted hover:bg-canvas hover:text-navy">
            ✕
          </button>
        </div>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div className={`rounded-md p-3 ${funded ? "bg-teal-50" : r.needsOrder ? (r.risk === "High" ? "bg-risk-high-bg" : "bg-risk-med-bg") : "bg-canvas"}`} data-testid="recommendation-summary">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">Recommendation</div>
          <div className="mt-1 text-lg font-semibold text-navy" data-testid="recommended-units">
            {funded ? `Order ${int(r.finalQty)} units · ${usd(r.orderValue, 2)}` : r.needsOrder ? "Order needed but not funded" : "No order needed"}
          </div>
          {funded && <div className="text-sm">Expected receipt {longDate(receiptDate(manifest, r))} ({r.leadTime} days lead time)</div>}
          <div className="mt-1"><StatusText status={r.status} /></div>
          <p className="mt-2 text-sm leading-snug">{r.reason}</p>
          {r.status.includes("supplier capacity") && r.capacityLimit !== null && r.capacityLeft !== null && (
            <div className="mt-2 rounded border border-risk-med/30 bg-white p-2 text-xs" data-testid="capacity-callout">
              <div className="mb-1 flex justify-between text-muted">
                <span>{r.supplier} capacity this review</span>
                <span className="tabular">{int(r.capacityLimit - r.capacityLeft)} used before this line · {int(r.capacityLeft)} left</span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-canvas" aria-hidden>
                <div className="h-full bg-risk-med" style={{ width: `${Math.min(1, (r.capacityLimit - r.capacityLeft) / r.capacityLimit) * 100}%` }} />
              </div>
              <p className="mt-1 text-muted">
                Next review: {longDate(addDays(manifest.planningDate, manifest.defaults.reviewPeriod))}. <a href="#capacity" className="font-medium text-teal-700 underline">See supplier capacity</a>
              </p>
            </div>
          )}
        </div>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Inputs</h3>
          <table className="w-full text-sm">
            <tbody>
              <Row label="Stock on hand" lineage="Simulated" value={`${int(r.onHand)} units`} />
              <Row label="Incoming orders (in transit)" lineage="Simulated" value={`${int(r.onOrder)} units`} />
              <Row label="Expected daily demand μ" lineage="Modeled" formula={`${l.methodLabel}, mean of next 28 days`} value={num(r.mu, 2)} />
              <Row label="Expected consumption over lead time" formula="μ × E[L]" value={`${num(r.leadTimeDemand, 1)} units`} />
              <Row label="Daily forecast error σ" lineage="Modeled" formula="RMSE across 5 validation windows" value={num(r.sigma, 2)} />
              <Row label="Supplier lead time E[L] ± sd" lineage="Simulated" value={`${r.leadTime} ± ${num(r.leadTimeSd, 1)} d`} />
              <Row label="Case pack / minimum order" lineage="Simulated" value={`${int(r.casePack)} / ${int(r.moqUnits)} units`} />
              <Row label="Unit cost" lineage="Simulated" value={usd(r.unitCost, 2)} />
              <Row label="Sales, last 364 days" lineage={manifest.source === "synthetic" ? "Synthetic" : "Observed"} value={`${int(l.units364)} units`} />
            </tbody>
          </table>
        </div>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Calculation</h3>
          <table className="w-full text-sm" data-testid="calc-table">
            <tbody>
              <Row label="Protection period P" formula={`E[L] + R = ${r.leadTime} + ${manifest.defaults.reviewPeriod}`} value={`${num(r.protectionPeriod, 0)} d`} />
              <Row label="Demand uncertainty σP" formula="√(P·σ² + μ²·Var[L])" value={num(r.sigmaP, 2)} />
              <Row label="Safety stock" formula={r.ropBasis === "empirical" ? "empirical fallback: ROP − μ·P" : `z(${pct(manifest.defaults.serviceLevel, 0)}) × σP = ${num(r.z, 3)} × ${num(r.sigmaP, 2)}`} value={num(r.safetyStock, 1)} />
              <Row label="Reorder point s" formula={r.ropBasis === "empirical" ? `${pct(manifest.defaults.serviceLevel, 0)} quantile of observed P-day demand (intermittent item)` : "μ·P + safety stock"} value={num(r.reorderPoint, 1)} strong />
              <Row label="Lot size" formula={`min(max(EOQ ${num(r.eoq, 0)}, μ·R), μ·${manifest.defaults.maxCycleDays ?? "∞"}d)`} value={num(r.cycleStock, 1)} />
              <Row label="Order-up-to level S" formula="s + lot size" value={num(r.orderUpTo, 1)} />
              <Row label="Inventory position" formula="on hand + in transit" value={int(r.inventoryPosition)} strong />
              <Row label="Raw need" formula={r.needsOrder ? "S − inventory position" : "position above s → 0"} value={num(r.rawQuantity, 1)} />
              <Row label="Recommended quantity" formula={`whole cases of ${int(r.casePack)}, at least ${int(r.moqUnits)}`} value={int(r.recommendedQty)} strong />
              <Row label="After capacity / budget" formula={`priority #${r.priorityRank} of ${manifest.demo.lines}`} value={int(r.finalQty)} strong />
              <Row label="Coverage on hand" formula="on hand ÷ μ" value={days(r.coverageDays)} />
              <Row label="Chance of stockout before receipt" formula="P(lead-time demand > on hand + in transit)" value={pct(r.pStockoutLeadTime, 0)} />
              {r.onHand <= 0 && r.mu > 0 && (
                <tr>
                  <td colSpan={2} className="py-1.5 text-xs text-risk-high">Out of stock now: sales are lost until the next receipt, which is why this line is High risk.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {l.inTransit.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Purchase orders in transit (simulated)</h3>
            <ul className="space-y-1 text-sm">
              {l.inTransit.map((p) => (
                <li key={p.po} className="flex justify-between gap-2">
                  <span className="font-mono text-xs">{p.po}</span>
                  <span>{int(p.qty)} units · expected {longDate(p.expectedDate)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="rounded-md border border-line p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What if? (this product only, before capacity limits)</h3>
          <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
            <label className="flex flex-col gap-1">
              Service level: <strong className="text-navy">{pct(sl, 1)}</strong>
              <input type="range" min={0.8} max={0.995} step={0.005} value={sl} onChange={(e) => setSl(Number(e.target.value))} aria-label="What-if service level" data-testid="whatif-sl" />
            </label>
            <label className="flex flex-col gap-1">
              Lead-time change: <strong className="text-navy">{shift > 0 ? "+" : ""}{shift} d</strong>
              <input type="range" min={-3} max={14} step={1} value={shift} onChange={(e) => setShift(Number(e.target.value))} aria-label="What-if lead-time change" data-testid="whatif-lt" />
            </label>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs" data-testid="whatif-result">
            <div className="rounded bg-canvas p-2">
              <div className="text-muted">Reorder point</div>
              <div className="tabular font-semibold text-navy">{num(unconstrained.reorderPoint, 1)} → {num((whatIf ?? unconstrained).reorderPoint, 1)}</div>
            </div>
            <div className="rounded bg-canvas p-2">
              <div className="text-muted">Safety stock</div>
              <div className="tabular font-semibold text-navy">{num(unconstrained.safetyStock, 1)} → {num((whatIf ?? unconstrained).safetyStock, 1)}</div>
            </div>
            <div className="rounded bg-canvas p-2">
              <div className="text-muted">Order qty</div>
              <div className="tabular font-semibold text-navy" data-testid="whatif-qty">{int(unconstrained.recommendedQty)} → {int((whatIf ?? unconstrained).recommendedQty)}</div>
            </div>
          </div>
          {whatIf && (
            <button type="button" className="mt-2 text-xs font-medium text-teal-700 underline" onClick={() => { setSl(manifest.defaults.serviceLevel); setShift(0); }}>
              Reset what-if
            </button>
          )}
        </div>

        <Button variant={inList ? "secondary" : "primary"} className="w-full" onClick={onToggleList} disabled={!funded && !inList} data-testid="toggle-list">
          {inList ? "Remove from purchase list" : funded ? "Add to purchase list" : "Nothing to purchase"}
        </Button>
      </div>
    </aside>
  );
}
