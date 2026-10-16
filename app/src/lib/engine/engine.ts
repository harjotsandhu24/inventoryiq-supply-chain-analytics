// TypeScript port of the reference replenishment engine
// (src/inventoryiq/inventory/policy.py and src/inventoryiq/planning.py).
// Every scenario is computed from immutable inputs; nothing here keeps state.
// Parity with Python is verified in tests/unit/parity.test.ts.

import type { Risk, Settings } from "../types";
import { lossFunction, normCdf, normPpf, roundTo } from "./stats";

export const EPS = 1e-9;
const RISK_RANK: Record<Risk, number> = { High: 0, Medium: 1, Low: 2 };

export interface EngineLine {
  id: string;
  mu: number;
  sigma: number;
  ltMean: number;
  ltSd: number;
  onHand: number;
  onOrder: number;
  backorders?: number;
  moq: number;
  casePack: number;
  unitCost: number;
  unitPrice: number;
  orderCost: number;
  intermittent: boolean;
  supplier: string;
  history: (number | null)[];
}

export type Status =
  | "No order needed"
  | "Order"
  | "Reduced: supplier capacity"
  | "Deferred: supplier capacity"
  | "Reduced: budget"
  | "Deferred: budget";

export interface PlanRow {
  id: string;
  mu: number;
  sigma: number;
  leadTime: number;
  leadTimeSd: number;
  protectionPeriod: number;
  z: number;
  sigmaP: number;
  safetyStockNormal: number;
  ropNormal: number;
  ropEmpirical: number | null;
  ropBasis: "normal" | "empirical";
  safetyStock: number;
  reorderPoint: number;
  eoq: number;
  cycleStock: number;
  orderUpTo: number;
  onHand: number;
  onOrder: number;
  inventoryPosition: number;
  needsOrder: boolean;
  rawQuantity: number;
  moqUnits: number;
  casePack: number;
  recommendedQty: number;
  coverageDays: number | null;
  leadTimeDemand: number;
  pStockoutLeadTime: number;
  expectedShortLeadTime: number;
  risk: Risk;
}

export interface Recommendation extends PlanRow {
  supplier: string;
  unitCost: number;
  finalQty: number;
  status: Status;
  /** Supplier capacity for this review (units); null when no capacity applies. */
  capacityLimit: number | null;
  /** Capacity left for this supplier when this line was considered; null if not evaluated. */
  capacityLeft: number | null;
  /** Budget left when this line was considered; null if not evaluated. */
  budgetLeft: number | null;
  orderValue: number;
  priorityRank: number;
  expectedReceiptDay: number;
  expectedShortUnits: number;
  pShort: number;
  expectedEndingUnits: number;
  annualAvgOrderQty: number;
  annualAvgInventoryUnits: number;
  annualOrdersPerYear: number;
  annualExpectedShortUnitsPerYear: number;
  annualFillRate: number;
  annualHoldingCost: number;
  annualOrderingCost: number;
  annualShortageCost: number;
  annualTotalCost: number;
  reason: string;
}

export class SettingsError extends Error {}

export function validateSettings(s: Settings): void {
  if (!(s.serviceLevel >= 0.5 && s.serviceLevel <= 0.999)) throw new SettingsError("Service level must be between 50% and 99.9%.");
  if (!Number.isInteger(s.reviewPeriod) || s.reviewPeriod < 1 || s.reviewPeriod > 28)
    throw new SettingsError("Review interval must be a whole number of days between 1 and 28.");
  if (!(s.leadTimeShift >= -30 && s.leadTimeShift <= 60)) throw new SettingsError("Lead-time change must be between -30 and +60 days.");
  if (!(s.leadTimeSdMultiplier >= 0 && s.leadTimeSdMultiplier <= 5))
    throw new SettingsError("Lead-time variability must be between 0x and 5x.");
  if (s.budget !== null && (!Number.isFinite(s.budget) || s.budget < 0)) throw new SettingsError("Budget must be zero or a positive amount.");
  if (s.holdingRate < 0 || s.shortageMultiplier < 0) throw new SettingsError("Cost rates must be non-negative.");
  if (s.maxCycleDays !== null && !(s.maxCycleDays >= s.reviewPeriod))
    throw new SettingsError("Maximum days of supply must be at least the review interval.");
}

/** Nearest-rank quantile of rolling `window`-day sums; null (unlisted) days dropped. */
export function empiricalQuantile(history: (number | null)[], window: number, level: number): number {
  const h = history.filter((v): v is number => v !== null && Number.isFinite(v));
  if (window <= 0 || h.length < window) return NaN;
  const c = new Array<number>(h.length + 1);
  c[0] = 0;
  for (let i = 0; i < h.length; i++) c[i + 1] = c[i] + h[i];
  const sums: number[] = [];
  for (let i = window; i <= h.length; i++) sums.push(c[i] - c[i - window]);
  sums.sort((a, b) => a - b);
  const k = Math.max(Math.ceil(level * sums.length) - 1, 0);
  return sums[k];
}

export function planLine(l: EngineLine, s: Settings, z: number): PlanRow {
  const mu = Math.max(l.mu, 0);
  const sigma = Math.max(Number.isFinite(l.sigma) ? l.sigma : 0, 0);
  const L = Math.max(l.ltMean + s.leadTimeShift, 1.0);
  const sdL = l.ltSd * s.leadTimeSdMultiplier;
  const varL = sdL * sdL;
  const R = s.reviewPeriod;
  const P = L + R;
  const sigmaP = Math.sqrt(P * sigma * sigma + mu * mu * varL);
  const ssNormal = z * sigmaP;
  const ropNormal = mu * P + ssNormal;
  let ropEmp = NaN;
  let useEmp = false;
  if (s.intermittentFallback && l.intermittent) {
    ropEmp = empiricalQuantile(l.history, Math.ceil(P), s.serviceLevel);
    useEmp = Number.isFinite(ropEmp) && ropEmp > ropNormal;
  }
  const rop = useEmp ? ropEmp : ropNormal;
  const ss = rop - mu * P;
  const h = s.holdingRate * l.unitCost;
  const eoq = mu > 0 && h > 0 ? Math.sqrt((2.0 * 365.0 * mu * l.orderCost) / h) : 0.0;
  let cycle = Math.max(eoq, mu * R);
  if (s.maxCycleDays !== null) cycle = Math.min(cycle, mu * s.maxCycleDays);
  const orderUpTo = rop + cycle;
  const ip = l.onHand + l.onOrder - (l.backorders ?? 0);
  const caseP = Math.max(l.casePack, 1.0);
  const moqUnits = Math.ceil(l.moq / caseP) * caseP;
  const needs = ip <= rop + EPS && orderUpTo - ip > EPS;
  const raw = needs ? orderUpTo - ip : 0.0;
  const cases = Math.ceil(roundTo(raw / caseP, 6));
  const qty = needs ? Math.max(cases * caseP, moqUnits) : 0.0;

  const muL = mu * L;
  const sigmaL = Math.sqrt(L * sigma * sigma + mu * mu * varL);
  const availL = l.onHand + l.onOrder;
  const kL = sigmaL > 0 ? (availL - muL) / sigmaL : 0.0;
  let pStock = sigmaL > 0 ? 1.0 - normCdf(kL) : availL < muL - EPS ? 1.0 : 0.0;
  if (!(mu > 0)) pStock = 0.0;
  let shortL = sigmaL > 0 ? sigmaL * lossFunction(kL) : Math.max(muL - availL, 0.0);
  if (!(mu > 0)) shortL = 0.0;
  const high = mu > 0 && (l.onHand <= 0 || pStock >= 0.5);
  const medium = !high && mu > 0 && ip <= rop + EPS;
  const risk: Risk = high ? "High" : medium ? "Medium" : "Low";
  return {
    id: l.id,
    mu,
    sigma,
    leadTime: L,
    leadTimeSd: sdL,
    protectionPeriod: P,
    z,
    sigmaP,
    safetyStockNormal: ssNormal,
    ropNormal,
    ropEmpirical: Number.isFinite(ropEmp) ? ropEmp : null,
    ropBasis: useEmp ? "empirical" : "normal",
    safetyStock: ss,
    reorderPoint: rop,
    eoq,
    cycleStock: cycle,
    orderUpTo,
    onHand: l.onHand,
    onOrder: l.onOrder,
    inventoryPosition: ip,
    needsOrder: needs,
    rawQuantity: raw,
    moqUnits,
    casePack: caseP,
    recommendedQty: qty,
    coverageDays: mu > 0 ? l.onHand / mu : null,
    leadTimeDemand: muL,
    pStockoutLeadTime: pStock,
    expectedShortLeadTime: shortL,
    risk,
  };
}

function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Allocation priority: risk tier, stockout probability, margin at risk per day, id. */
export function priorityOrder(rows: { id: string; risk: Risk; p: number; value: number }[]): number[] {
  const idx = rows.map((_, i) => i);
  idx.sort((i, j) => {
    const a = rows[i];
    const b = rows[j];
    if (RISK_RANK[a.risk] !== RISK_RANK[b.risk]) return RISK_RANK[a.risk] - RISK_RANK[b.risk];
    const pa = roundTo(a.p, 9);
    const pb = roundTo(b.p, 9);
    if (pa !== pb) return pb - pa;
    if (a.value !== b.value) return b.value - a.value;
    return compareIds(a.id, b.id);
  });
  return idx;
}

/** Greedy constrained allocation (capacity, then budget) in priority order. Heuristic, not an optimum. */
export function allocate(
  qty: number[],
  casePack: number[],
  moqUnits: number[],
  unitCost: number[],
  supplier: string[],
  order: number[],
  capacity: Record<string, number> | null,
  budget: number | null,
): { finalQty: number[]; status: Status[]; capacityLeft: (number | null)[]; budgetLeft: (number | null)[] } {
  if (budget !== null && (!Number.isFinite(budget) || budget < 0)) throw new SettingsError("Budget must be zero or a positive amount.");
  const finalQty = qty.slice();
  const status: Status[] = finalQty.map((q) => (q > 0 ? "Order" : "No order needed"));
  const capacityLeft: (number | null)[] = finalQty.map(() => null);
  const budgetLeft: (number | null)[] = finalQty.map(() => null);
  if (capacity !== null) {
    const left: Record<string, number> = { ...capacity };
    for (const i of order) {
      if (finalQty[i] <= 0) continue;
      const cap = supplier[i] in left ? left[supplier[i]] : Infinity;
      capacityLeft[i] = Number.isFinite(cap) ? cap : null;
      if (finalQty[i] > cap + EPS) {
        const q = Math.floor(roundTo(cap / casePack[i], 6)) * casePack[i];
        if (q >= moqUnits[i] && q > 0) {
          finalQty[i] = q;
          status[i] = "Reduced: supplier capacity";
        } else {
          finalQty[i] = 0;
          status[i] = "Deferred: supplier capacity";
        }
      }
      left[supplier[i]] = cap - finalQty[i];
    }
  }
  if (budget !== null) {
    let left = budget;
    for (const i of order) {
      if (finalQty[i] <= 0) continue;
      const cost = finalQty[i] * unitCost[i];
      budgetLeft[i] = left;
      if (cost > left + 1e-6) {
        const q = unitCost[i] > 0 ? Math.floor(roundTo(left / (casePack[i] * unitCost[i]), 6)) * casePack[i] : finalQty[i];
        if (q >= moqUnits[i] && q > 0) {
          finalQty[i] = q;
          status[i] = "Reduced: budget";
        } else {
          finalQty[i] = 0;
          status[i] = "Deferred: budget";
        }
      }
      left -= finalQty[i] * unitCost[i];
    }
  }
  return { finalQty, status, capacityLeft, budgetLeft };
}

export function exposure(ipAfter: number, mu: number, P: number, sigmaP: number) {
  const muP = mu * P;
  const k = sigmaP > 0 ? (ipAfter - muP) / sigmaP : 0.0;
  let esc = sigmaP > 0 ? sigmaP * lossFunction(k) : Math.max(muP - ipAfter, 0.0);
  let pShort = sigmaP > 0 ? 1.0 - normCdf(k) : ipAfter < muP - EPS ? 1.0 : 0.0;
  if (!(mu > 0)) {
    pShort = 0.0;
    esc = 0.0;
  }
  const ending = Math.max(ipAfter - muP + esc, 0.0);
  return { expectedShortUnits: esc, pShort, expectedEndingUnits: ending };
}

export function steadyState(p: PlanRow, l: EngineLine, s: Settings) {
  const mu = Math.max(l.mu, 0);
  const caseP = Math.max(l.casePack, 1.0);
  let q = Math.max(Math.ceil(roundTo(p.cycleStock / caseP, 6)) * caseP, p.moqUnits);
  if (!(mu > 0)) q = 0.0;
  const ss = Math.max(p.safetyStock, 0.0);
  const sp = p.sigmaP;
  const k = sp > 0 ? ss / sp : 0.0;
  const esc = sp > 0 ? sp * lossFunction(k) : 0.0;
  const orders = q > 0 ? (365.0 * mu) / q : 0.0;
  const fill = q > 0 ? Math.min(Math.max(1.0 - esc / q, 0.0), 1.0) : 1.0;
  const margin = Math.max(l.unitPrice - l.unitCost, 0.0);
  const avgInv = mu > 0 ? ss + q / 2.0 : 0.0;
  const holding = avgInv * l.unitCost * s.holdingRate;
  const ordering = orders * l.orderCost;
  const shortUnits = esc * orders;
  const shortage = shortUnits * margin * s.shortageMultiplier;
  return {
    annualAvgOrderQty: q,
    annualAvgInventoryUnits: avgInv,
    annualOrdersPerYear: orders,
    annualExpectedShortUnitsPerYear: shortUnits,
    annualFillRate: fill,
    annualHoldingCost: holding,
    annualOrderingCost: ordering,
    annualShortageCost: shortage,
    annualTotalCost: holding + ordering + shortage,
  };
}

function fixed(x: number, d: number): string {
  return x.toFixed(d);
}

export function reason(r: Omit<Recommendation, "reason">): string {
  if (r.mu <= 0) return "No demand is forecast for the next 28 days, so no purchase is recommended.";
  const ip = r.inventoryPosition;
  if (!r.needsOrder) return `Inventory position ${fixed(ip, 0)} is above the reorder point ${fixed(r.reorderPoint, 1)}; no order is needed at this review.`;
  let text = `Inventory position ${fixed(ip, 0)} is at or below the reorder point ${fixed(r.reorderPoint, 1)}. Ordering up to ${fixed(r.orderUpTo, 1)} needs ${fixed(r.rawQuantity, 1)} units`;
  const notes: string[] = [];
  if (r.recommendedQty > Math.ceil(roundTo(r.rawQuantity, 6))) {
    if (r.recommendedQty === r.moqUnits && r.moqUnits > r.rawQuantity) notes.push(`raised to the ${fixed(r.moqUnits, 0)}-unit minimum order`);
    else notes.push(`rounded up to whole cases of ${fixed(r.casePack, 0)}`);
  }
  text += (notes.length ? ", " + notes.join(" and ") : "") + ` = ${fixed(r.recommendedQty, 0)} units.`;
  const sup = r.supplier;
  const left = r.capacityLeft ?? NaN;
  const limit = r.capacityLimit ?? NaN;
  if (r.status === "Reduced: supplier capacity")
    text += ` Reduced by supplier capacity: ${sup} had ${fixed(left, 0)} of ${fixed(limit, 0)} units left for this review after higher-priority lines, so ${fixed(r.finalQty, 0)} units are funded.`;
  else if (r.status === "Deferred: supplier capacity")
    text += ` Deferred by supplier capacity: ${sup} had ${fixed(left, 0)} of ${fixed(limit, 0)} units left for this review after higher-priority lines, less than this line's ${fixed(r.moqUnits, 0)}-unit minimum order. It is reconsidered at the next review.`;
  else if (r.status === "Reduced: budget")
    text += ` Reduced by budget: $${fixed(r.budgetLeft ?? NaN, 2)} remained after higher-priority lines, so ${fixed(r.finalQty, 0)} units are funded.`;
  else if (r.status === "Deferred: budget")
    text += ` Deferred by budget: $${fixed(r.budgetLeft ?? NaN, 2)} remained after higher-priority lines, less than this line's minimum order cost of $${fixed(r.moqUnits * r.unitCost, 2)}.`;
  return text;
}

/** Full recommendation set for all lines under one immutable settings object. */
export function recommend(lines: EngineLine[], s: Settings, capacity: Record<string, number> | null, planningDay: number): Recommendation[] {
  validateSettings(s);
  const z = normPpf(s.serviceLevel);
  const plans = lines.map((l) => planLine(l, s, z));
  const order = priorityOrder(
    plans.map((p, i) => ({ id: p.id, risk: p.risk, p: p.pStockoutLeadTime, value: Math.max(lines[i].mu, 0) * Math.max(lines[i].unitPrice - lines[i].unitCost, 0) })),
  );
  const cap = capacity === null ? null : Object.fromEntries(Object.entries(capacity).map(([k, v]) => [k, (v * s.reviewPeriod) / 7.0]));
  const { finalQty, status, capacityLeft, budgetLeft } = allocate(
    plans.map((p) => p.recommendedQty),
    plans.map((p) => p.casePack),
    plans.map((p) => p.moqUnits),
    lines.map((l) => l.unitCost),
    lines.map((l) => l.supplier),
    order,
    cap,
    s.budget,
  );
  const rank = new Array<number>(lines.length);
  order.forEach((i, k) => (rank[i] = k + 1));
  return plans.map((p, i) => {
    const l = lines[i];
    const ex = exposure(p.inventoryPosition + finalQty[i], Math.max(l.mu, 0), p.protectionPeriod, p.sigmaP);
    const st = steadyState(p, l, s);
    const base = {
      ...p,
      supplier: l.supplier,
      unitCost: l.unitCost,
      finalQty: finalQty[i],
      status: status[i],
      capacityLimit: cap !== null && l.supplier in cap ? cap[l.supplier] : null,
      capacityLeft: capacityLeft[i],
      budgetLeft: budgetLeft[i],
      orderValue: roundTo(finalQty[i] * l.unitCost, 2),
      priorityRank: rank[i],
      expectedReceiptDay: finalQty[i] > 0 ? planningDay + roundTo(p.leadTime, 0) : 0, // numpy.rint semantics
      ...ex,
      ...st,
    };
    return { ...base, reason: reason(base) };
  });
}

export interface PlanSummary {
  lines: number;
  linesNeedingOrder: number;
  linesFunded: number;
  linesDeferred: number;
  linesDeferredCapacity: number;
  linesDeferredBudget: number;
  unitsOrdered: number;
  purchaseSpend: number;
  highRisk: number;
  mediumRisk: number;
  expectedShortUnits: number;
  expectedShortLeadTime: number;
  expectedEndingValue: number;
  annualHoldingCost: number;
  annualOrderingCost: number;
  annualShortageCost: number;
  annualTotalCost: number;
}

export function summarise(recs: Recommendation[]): PlanSummary {
  const sum = (f: (r: Recommendation) => number) => recs.reduce((a, r) => a + f(r), 0);
  return {
    lines: recs.length,
    linesNeedingOrder: recs.filter((r) => r.needsOrder).length,
    linesFunded: recs.filter((r) => r.finalQty > 0).length,
    linesDeferred: recs.filter((r) => r.status.startsWith("Deferred")).length,
    linesDeferredCapacity: recs.filter((r) => r.status === "Deferred: supplier capacity").length,
    linesDeferredBudget: recs.filter((r) => r.status === "Deferred: budget").length,
    unitsOrdered: sum((r) => r.finalQty),
    purchaseSpend: roundTo(sum((r) => r.orderValue), 2),
    highRisk: recs.filter((r) => r.risk === "High").length,
    mediumRisk: recs.filter((r) => r.risk === "Medium").length,
    expectedShortUnits: sum((r) => r.expectedShortUnits),
    expectedShortLeadTime: sum((r) => r.expectedShortLeadTime),
    expectedEndingValue: sum((r) => r.expectedEndingUnits * r.unitCost),
    annualHoldingCost: sum((r) => r.annualHoldingCost),
    annualOrderingCost: sum((r) => r.annualOrderingCost),
    annualShortageCost: sum((r) => r.annualShortageCost),
    annualTotalCost: sum((r) => r.annualTotalCost),
  };
}
