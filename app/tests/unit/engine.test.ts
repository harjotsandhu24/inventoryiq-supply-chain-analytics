import { describe, expect, it } from "vitest";
import { allocate, empiricalQuantile, recommend, SettingsError, summarise, type EngineLine } from "@/lib/engine/engine";
import { erfc, lossFunction, normCdf, normPpf, roundTo } from "@/lib/engine/stats";
import type { Settings } from "@/lib/types";

const S: Settings = {
  serviceLevel: 0.95,
  reviewPeriod: 7,
  leadTimeShift: 0,
  leadTimeSdMultiplier: 1,
  budget: null,
  intermittentFallback: true,
  holdingRate: 0.25,
  shortageMultiplier: 1.5,
  maxCycleDays: null,
};

const line = (o: Partial<EngineLine> = {}): EngineLine => ({
  id: "L1",
  mu: 10,
  sigma: 4,
  ltMean: 5,
  ltSd: 2,
  onHand: 100,
  onOrder: 30,
  moq: 12,
  casePack: 12,
  unitCost: 2,
  unitPrice: 3,
  orderCost: 6,
  intermittent: false,
  supplier: "S",
  history: [],
  ...o,
});

describe("normal helpers", () => {
  it("inverse CDF at common service levels", () => {
    expect(normPpf(0.95)).toBeCloseTo(1.6448536, 6);
    expect(normPpf(0.9)).toBeCloseTo(1.2815516, 6);
    expect(normPpf(0.5)).toBe(0);
    expect(normPpf(0.01)).toBeCloseTo(-2.3263479, 6);
    expect(() => normPpf(1)).toThrow();
  });
  it("CDF, erfc and loss function", () => {
    expect(normCdf(0)).toBeCloseTo(0.5, 7);
    expect(normCdf(1.96)).toBeCloseTo(0.9750021, 6);
    expect(erfc(0.4) + erfc(-0.4)).toBeCloseTo(2, 12);
    expect(lossFunction(0)).toBeCloseTo(0.3989423, 6);
  });
  it("roundTo uses half-to-even on exact ties", () => {
    expect(roundTo(2.5, 0)).toBe(2);
    expect(roundTo(3.5, 0)).toBe(4);
    expect(roundTo(1.234, 2)).toBe(1.23);
  });
});

describe("golden examples (hand calculated, see tests/test_golden_reference.py)", () => {
  it("1: safety stock, ROP, order-up-to and case rounding", () => {
    const [r] = recommend([line()], S, null, 100);
    expect(r.sigmaP).toBeCloseTo(24.33105, 4);
    expect(r.safetyStock).toBeCloseTo(40.021, 2);
    expect(r.reorderPoint).toBeCloseTo(160.021, 2);
    expect(r.eoq).toBeCloseTo(295.973, 2);
    expect(r.orderUpTo).toBeCloseTo(455.994, 2);
    expect(r.recommendedQty).toBe(336);
    expect(r.expectedReceiptDay).toBe(105);
  });
  it("2: no order above the reorder point", () => {
    const [r] = recommend([line({ mu: 2, sigma: 1, ltMean: 3, ltSd: 0, onHand: 30, onOrder: 0, casePack: 6, moq: 6, unitCost: 1, orderCost: 4 })], { ...S, serviceLevel: 0.9 }, null, 1);
    expect(r.reorderPoint).toBeCloseTo(24.0527, 3);
    expect(r.recommendedQty).toBe(0);
    expect(r.coverageDays).toBe(15);
    expect(r.risk).toBe("Low");
  });
  it("3: minimum order quantity binds", () => {
    const [r] = recommend([line({ mu: 0.5, sigma: 0.8, ltMean: 14, ltSd: 4, onHand: 5, onOrder: 0, casePack: 6, moq: 60, unitCost: 10, unitPrice: 16, orderCost: 9 })], S, null, 1);
    expect(r.reorderPoint).toBeCloseTo(17.3691, 3);
    expect(r.recommendedQty).toBe(60);
    expect(r.reason).toContain("60-unit minimum order");
  });
  it("5: budget allocation", () => {
    const { finalQty, status } = allocate([60, 50, 30], [10, 10, 10], [10, 10, 10], [1, 1, 1], ["S", "S", "S"], [0, 1, 2], null, 100);
    expect(finalQty).toEqual([60, 40, 0]);
    expect(status).toEqual(["Order", "Reduced: budget", "Deferred: budget"]);
  });
});

describe("edge cases and constraints", () => {
  it("zero inventory is high risk", () => {
    const [r] = recommend([line({ onHand: 0, onOrder: 0 })], S, null, 1);
    expect(r.risk).toBe("High");
    expect(r.finalQty).toBeGreaterThan(0);
  });
  it("zero demand never orders and has no coverage", () => {
    const [r] = recommend([line({ mu: 0, sigma: 0, onHand: 0, onOrder: 0 })], S, null, 1);
    expect(r.finalQty).toBe(0);
    expect(r.coverageDays).toBeNull();
    expect(r.reason).toContain("No demand");
  });
  it("in-transit stock reduces the order one-for-one", () => {
    const a = recommend([line({ onHand: 20, onOrder: 0 })], S, null, 1)[0].recommendedQty;
    const b = recommend([line({ onHand: 20, onOrder: 96 })], S, null, 1)[0].recommendedQty;
    expect(a - b).toBe(96);
  });
  it("whole cases and MOQ always respected", () => {
    for (const [cp, moq] of [[1, 1], [6, 6], [12, 48], [5, 7]]) {
      const [r] = recommend([line({ onHand: 0, onOrder: 0, mu: 1.3, casePack: cp, moq })], S, null, 1);
      expect(r.recommendedQty % cp).toBe(0);
      expect(r.recommendedQty).toBeGreaterThanOrEqual(Math.ceil(moq / cp) * cp);
    }
  });
  it("extreme lead times stay finite", () => {
    const [r] = recommend([line({ ltMean: 90, ltSd: 30 })], S, null, 1);
    expect(Number.isFinite(r.reorderPoint) && Number.isFinite(r.recommendedQty)).toBe(true);
  });
  it("lead-time change cannot go below one day", () => {
    const [r] = recommend([line({ ltMean: 2 })], { ...S, leadTimeShift: -10 }, null, 1);
    expect(r.leadTime).toBe(1);
  });
  it("supplier capacity limits lower-priority lines", () => {
    const lines = [line({ id: "A", onHand: 0, onOrder: 0 }), line({ id: "B", onHand: 50, onOrder: 0 })];
    // A needs 456 units (highest priority, no stock); B needs 384. Weekly capacity 600 -> B reduced to 144 (12 cases).
    const recs = recommend(lines, S, { S: 600 }, 1);
    const total = recs.reduce((a, r) => a + r.finalQty, 0);
    expect(total).toBeLessThanOrEqual(600);
    expect(recs.find((r) => r.id === "A")!.status).toBe("Order");
    expect(recs.find((r) => r.id === "B")!.finalQty).toBe(144);
    expect(recs.find((r) => r.id === "B")!.status).toBe("Reduced: supplier capacity");
  });
  it("budget is never exceeded; zero budget defers everything; negative budget is rejected", () => {
    const lines = [line({ id: "A", onHand: 0 }), line({ id: "B", onHand: 10 }), line({ id: "C", onHand: 40 })];
    for (const b of [0, 50, 300, 1000]) {
      const s = summarise(recommend(lines, { ...S, budget: b }, null, 1));
      expect(s.purchaseSpend).toBeLessThanOrEqual(b + 1e-9);
    }
    expect(summarise(recommend(lines, { ...S, budget: 0 }, null, 1)).linesFunded).toBe(0);
    expect(() => recommend(lines, { ...S, budget: -1 }, null, 1)).toThrow(SettingsError);
  });
  it("rejects invalid settings with readable messages", () => {
    expect(() => recommend([line()], { ...S, serviceLevel: 1 }, null, 1)).toThrow(/Service level/);
    expect(() => recommend([line()], { ...S, reviewPeriod: 0 }, null, 1)).toThrow(/Review interval/);
    expect(() => recommend([line()], { ...S, budget: Number.NaN }, null, 1)).toThrow(/Budget/);
  });
  it("days-of-supply cap limits cycle stock (policy v2)", () => {
    const [v1] = recommend([line({ mu: 1, sigma: 1, unitCost: 0.5, onHand: 0, onOrder: 0, casePack: 1, moq: 1 })], S, null, 1);
    const [v2] = recommend([line({ mu: 1, sigma: 1, unitCost: 0.5, onHand: 0, onOrder: 0, casePack: 1, moq: 1 })], { ...S, maxCycleDays: 28 }, null, 1);
    expect(v1.cycleStock).toBeGreaterThan(28);
    expect(v2.cycleStock).toBe(28);
  });
  it("empirical quantile uses nearest rank and drops unlisted days", () => {
    expect(empiricalQuantile([0, 1, 0, 3, null, 2, 0], 2, 0.8)).toBe(3);
    expect(Number.isNaN(empiricalQuantile([1], 3, 0.9))).toBe(true);
  });
});

describe("scenario isolation", () => {
  it("results depend only on inputs, not on previous runs", () => {
    const lines = [line({ id: "A", onHand: 0 }), line({ id: "B", onHand: 20 })];
    const snapshot = JSON.stringify(lines);
    const a = recommend(lines, S, { S: 1000 }, 1);
    recommend(lines, { ...S, serviceLevel: 0.99, budget: 10, leadTimeShift: 7 }, { S: 5 }, 1);
    const b = recommend(lines, S, { S: 1000 }, 1);
    expect(b).toEqual(a);
    expect(JSON.stringify(lines)).toBe(snapshot); // inputs never mutated
  });
  it("higher service level raises safety stock and lowers expected shortage", () => {
    const lines = [line({ onHand: 0 })];
    const lo = recommend(lines, { ...S, serviceLevel: 0.9 }, null, 1)[0];
    const hi = recommend(lines, { ...S, serviceLevel: 0.99 }, null, 1)[0];
    expect(hi.safetyStock).toBeGreaterThan(lo.safetyStock);
    expect(hi.annualShortageCost).toBeLessThan(lo.annualShortageCost);
  });
});
