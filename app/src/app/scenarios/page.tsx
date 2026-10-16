"use client";

import { Suspense, useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { receiptDate } from "@/components/CalculationPanel";
import { DataTable, type Column } from "@/components/DataTable";
import { Button, Card, PageHeader, SelectField } from "@/components/ui";
import { downloadText, recommendationRows, toCsv } from "@/lib/csv";
import { useAppState, useMemoRecs, type AppData } from "@/lib/data";
import { summarise, type PlanSummary, type Recommendation } from "@/lib/engine/engine";
import { compactUsd, int, num, pct, usd } from "@/lib/format";
import type { Settings, SimSummary } from "@/lib/types";
import { useQueryState, useUrlState } from "@/lib/useQueryState";

export default function ScenarioPage() {
  return (
    <Suspense>
      <Scenario />
    </Suspense>
  );
}

function Scenario() {
  const state = useAppState();
  if (state.status !== "ready") return null;
  return <ScenarioReady data={state.data} />;
}

type PresetKey = "balanced" | "protect" | "limit" | "custom";
const SCENARIO_DEFAULTS = { preset: "balanced", sl: "", lt: "", ltv: "", r: "", budget: "" };

function ScenarioReady({ data }: { data: AppData }) {
  const { manifest, lines, baseline, lineById } = data;
  const d = manifest.defaults;
  const baseSummary = useMemo(() => summarise(baseline), [baseline]);
  const [q, update] = useUrlState(SCENARIO_DEFAULTS);
  const { preset, sl: slQ, lt: ltQ, ltv: ltvQ, r: rQ, budget: bQ } = q;

  const presetDef = manifest.presets[preset as keyof typeof manifest.presets];
  const presetBudget = presetDef?.budget_share != null ? Math.round(baseSummary.purchaseSpend * presetDef.budget_share * 100) / 100 : null;
  // URL values override preset values; an empty URL value means "use the preset".
  const sl = slQ !== "" ? Number(slQ) : presetDef?.service_level ?? d.serviceLevel;
  const lt = ltQ !== "" ? Number(ltQ) : presetDef?.lead_time_shift ?? 0;
  const ltv = ltvQ !== "" ? Number(ltvQ) : presetDef?.lead_time_sd_multiplier ?? 1;
  const r = rQ !== "" ? Number(rQ) : presetDef?.review_period ?? d.reviewPeriod;
  const budgetText = bQ === "blank" ? "" : bQ !== "" ? bQ : presetBudget !== null ? String(presetBudget) : "none";
  const budget = budgetText === "none" ? null : budgetText.trim() === "" ? NaN : Number(budgetText);
  const budgetInvalid = budget !== null && (!Number.isFinite(budget) || budget < 0);

  const settings: Settings = useMemo(
    () => ({ ...d, serviceLevel: sl, leadTimeShift: lt, leadTimeSdMultiplier: ltv, reviewPeriod: r, budget: budgetInvalid ? null : budget }),
    [d, sl, lt, ltv, r, budget, budgetInvalid],
  );
  const { recs, error } = useMemoRecs(lines, settings, manifest.capacity, manifest.planningDay);
  const sum = recs ? summarise(recs) : null;

  // One atomic URL update per interaction. Moving away from a preset freezes its values as a custom scenario.
  const customise = (key: string, value: string) => {
    if (preset === "custom") update({ [key]: value });
    else update({ preset: "custom", sl: String(sl), lt: String(lt), ltv: String(ltv), r: String(r), budget: budgetText, [key]: value });
  };
  const applyPreset = (k: PresetKey) => {
    if (k === "custom") customise("preset", "custom");
    else update({ ...SCENARIO_DEFAULTS, preset: k });
  };
  // Every change re-runs recommend() on the immutable baseline lines; no state carries between scenarios.

  const changes = useMemo(() => {
    if (!recs) return [];
    return recs
      .map((x) => ({ rec: x, base: data.baselineById.get(x.id)!, delta: x.finalQty - data.baselineById.get(x.id)!.finalQty }))
      .filter((x) => x.delta !== 0)
      .sort((a, b) => Math.abs(b.delta * b.rec.unitCost) - Math.abs(a.delta * a.rec.unitCost));
  }, [recs, data.baselineById]);

  const exportScenario = () => {
    if (!recs) return;
    const rows = recommendationRows(recs, lineById, (x) => receiptDate(manifest, x)).map((row) => ({
      scenario: preset,
      service_level: settings.serviceLevel,
      lead_time_change_days: settings.leadTimeShift,
      lead_time_variability_multiplier: settings.leadTimeSdMultiplier,
      review_interval_days: settings.reviewPeriod,
      budget: settings.budget ?? "unlimited",
      ...row,
    }));
    downloadText(`inventoryiq_scenario_${preset}.csv`, toCsv(rows));
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Scenario lab"
        subtitle="Change a planning assumption and every recommendation is recalculated from the same baseline data. The Balanced plan is the fixed comparison point."
        actions={
          <>
            <Button onClick={() => applyPreset("balanced")} data-testid="reset">Reset</Button>
            <Button variant="primary" onClick={exportScenario} disabled={!recs} data-testid="export-scenario">Export scenario (CSV)</Button>
          </>
        }
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card title="Assumptions">
          <div className="space-y-5 px-4 py-4">
            <fieldset>
              <legend className="mb-2 text-xs font-medium text-muted">Presets</legend>
              <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Scenario preset">
                {(["balanced", "protect", "limit", "custom"] as PresetKey[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    aria-checked={preset === k}
                    data-testid={`preset-${k}`}
                    onClick={() => applyPreset(k)}
                    className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${preset === k ? "border-teal bg-teal-50 font-semibold text-navy" : "border-line hover:border-navy/40 hover:bg-canvas"}`}
                  >
                    {k === "custom" ? "Custom" : manifest.presets[k].label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted">
                {preset === "protect" && "Higher service target (99%): more safety stock, fewer expected stockouts."}
                {preset === "limit" && `Budget capped at 60% of the Balanced spend (${usd(presetBudget, 0)}). Lowest-priority orders are cut first.`}
                {preset === "balanced" && "95% cycle service level, weekly review, no budget limit."}
                {preset === "custom" && "Your own combination of assumptions."}
              </p>
            </fieldset>

            <Slider label="Target cycle service level" value={sl} min={0.8} max={0.995} step={0.005} display={pct(sl, 1)} testId="sl" onChange={(v) => customise("sl", String(v))} />
            <Slider label="Supplier lead-time change" value={lt} min={-3} max={14} step={1} display={`${lt > 0 ? "+" : ""}${lt} days`} testId="lt" onChange={(v) => customise("lt", String(v))} />
            <Slider label="Lead-time variability" value={ltv} min={0} max={3} step={0.25} display={`${num(ltv, 2)}× supplier sd`} testId="ltv" onChange={(v) => customise("ltv", String(v))} />
            <SelectField label="Replenishment review interval" value={String(r)} testId="review" onChange={(v) => customise("r", v)} options={[1, 7, 14, 28].map((x) => ({ value: String(x), label: x === 1 ? "Daily" : `Every ${x} days` }))} />
            <div className="space-y-1">
              <label className="flex items-center gap-2 text-xs font-medium text-muted">
                <input type="checkbox" className="h-4 w-4 accent-teal" checked={budget === null && !budgetInvalid} onChange={(e) => customise("budget", e.target.checked ? "none" : String(Math.round(baseSummary.purchaseSpend)))} data-testid="budget-unlimited" />
                No purchasing budget limit
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-muted">
                Purchasing budget for this review ($)
                <input
                  type="number"
                  min={0}
                  step={100}
                  inputMode="decimal"
                  disabled={budgetText === "none"}
                  value={budgetText === "none" ? "" : budgetText}
                  placeholder="No limit"
                  onChange={(e) => customise("budget", e.target.value === "" ? "blank" : e.target.value)}
                  aria-invalid={budgetInvalid}
                  aria-describedby="budget-help"
                  data-testid="budget"
                  className={`h-9 rounded-md border px-3 text-sm text-ink disabled:bg-canvas ${budgetInvalid ? "border-risk-high" : "border-line"}`}
                />
              </label>
              <p id="budget-help" className={`text-xs ${budgetInvalid ? "text-risk-high" : "text-muted"}`} role={budgetInvalid ? "alert" : undefined}>
                {budgetInvalid ? "Enter zero or a positive amount. The budget is ignored until it is valid." : `Balanced plan spends ${usd(baseSummary.purchaseSpend, 0)}.`}
              </p>
            </div>
          </div>
        </Card>

        <div className="space-y-5">
          {error && (
            <p role="alert" className="rounded-md bg-risk-high-bg px-4 py-3 text-sm text-risk-high">{error}</p>
          )}
          {sum && <Comparison base={baseSummary} scen={sum} />}
          {sum && <CostChart base={baseSummary} scen={sum} />}
          <Card title={`Lines whose order changes (${changes.length})`}>
            <DataTable
              testId="changes-table"
              caption="Products whose funded order differs from the Balanced plan"
              rows={changes}
              rowKey={(x) => x.rec.id}
              pageSize={8}
              columns={changeColumns}
              empty={<p className="px-4 py-6 text-center text-sm text-muted">No recommendation differs from the Balanced plan.</p>}
            />
          </Card>
        </div>
      </div>
      <Backtest data={data} />
    </div>
  );
}

const changeColumns: Column<{ rec: Recommendation; base: Recommendation; delta: number }>[] = [
  { key: "id", label: "Product", render: (x) => <span className="font-medium text-navy">{x.rec.id}</span>, sortValue: (x) => x.rec.id },
  { key: "base", label: "Balanced qty", align: "right", render: (x) => int(x.base.finalQty), sortValue: (x) => x.base.finalQty },
  { key: "scen", label: "Scenario qty", align: "right", render: (x) => int(x.rec.finalQty), sortValue: (x) => x.rec.finalQty },
  { key: "delta", label: "Change", align: "right", render: (x) => <span className={x.delta > 0 ? "text-teal-700" : "text-risk-high"}>{x.delta > 0 ? "+" : ""}{int(x.delta)}</span>, sortValue: (x) => x.delta },
  { key: "rop", label: "Reorder point", align: "right", render: (x) => `${num(x.base.reorderPoint, 1)} → ${num(x.rec.reorderPoint, 1)}` },
  { key: "status", label: "Scenario status", render: (x) => x.rec.status },
];

function Slider({ label, value, min, max, step, display, onChange, testId }: { label: string; value: number; min: number; max: number; step: number; display: string; onChange: (v: number) => void; testId: string }) {
  return (
    <label className="block text-xs font-medium text-muted">
      <span className="flex justify-between">
        {label}
        <strong className="tabular text-sm text-navy" data-testid={`${testId}-value`}>{display}</strong>
      </span>
      <input type="range" className="mt-2 w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} data-testid={`${testId}-slider`} aria-valuetext={display} />
    </label>
  );
}

function Comparison({ base, scen }: { base: PlanSummary; scen: PlanSummary }) {
  const rows: { label: string; b: number; s: number; fmt: (x: number) => string; better: "lower" | "higher" | null; hint?: string }[] = [
    { label: "Purchase spend this review", b: base.purchaseSpend, s: scen.purchaseSpend, fmt: (x) => usd(x, 0), better: null },
    { label: "Lines ordered", b: base.linesFunded, s: scen.linesFunded, fmt: int, better: null },
    { label: "Lines needing an order but not funded", b: base.linesDeferred, s: scen.linesDeferred, fmt: int, better: "lower" },
    { label: "Lines at high stockout risk", b: base.highRisk, s: scen.highRisk, fmt: int, better: "lower", hint: "before any new order can arrive" },
    { label: "Expected units short before receipt", b: base.expectedShortLeadTime, s: scen.expectedShortLeadTime, fmt: (x) => num(x, 0), better: "lower", hint: "cannot be fixed by this order" },
    { label: "Expected units short after ordering", b: base.expectedShortUnits, s: scen.expectedShortUnits, fmt: (x) => num(x, 0), better: "lower", hint: "over each line's protection period" },
    { label: "Projected stock left at period end", b: base.expectedEndingValue, s: scen.expectedEndingValue, fmt: compactUsd, better: null },
    { label: "Modeled annual holding cost", b: base.annualHoldingCost, s: scen.annualHoldingCost, fmt: compactUsd, better: "lower" },
    { label: "Modeled annual ordering cost", b: base.annualOrderingCost, s: scen.annualOrderingCost, fmt: compactUsd, better: "lower" },
    { label: "Modeled annual shortage penalty", b: base.annualShortageCost, s: scen.annualShortageCost, fmt: compactUsd, better: "lower" },
    { label: "Modeled annual total cost", b: base.annualTotalCost, s: scen.annualTotalCost, fmt: compactUsd, better: "lower" },
  ];
  return (
    <Card title="Scenario vs Balanced plan">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="comparison-table">
          <caption className="sr-only">Scenario results compared with the Balanced baseline</caption>
          <thead>
            <tr className="border-b border-line text-xs uppercase text-muted">
              <th scope="col" className="px-4 py-2 text-left">Measure</th>
              <th scope="col" className="px-4 py-2 text-right">Balanced</th>
              <th scope="col" className="px-4 py-2 text-right">Scenario</th>
              <th scope="col" className="px-4 py-2 text-right">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta = r.s - r.b;
              const rel = Math.abs(r.b) > 1e-9 ? delta / Math.abs(r.b) : null;
              const good = r.better === null || Math.abs(delta) < 1e-9 ? null : (r.better === "lower") === delta < 0;
              return (
                <tr key={r.label} className="border-b border-line/70">
                  <th scope="row" className="px-4 py-2 text-left font-normal">
                    {r.label}
                    {r.hint && <span className="block text-xs text-muted">{r.hint}</span>}
                  </th>
                  <td className="tabular px-4 py-2 text-right">{r.fmt(r.b)}</td>
                  <td className="tabular px-4 py-2 text-right font-semibold text-navy">{r.fmt(r.s)}</td>
                  <td className={`tabular px-4 py-2 text-right ${good === null ? "text-muted" : good ? "text-teal-700" : "text-risk-high"}`}>
                    {Math.abs(delta) < 1e-9 ? "no change" : `${delta > 0 ? "+" : ""}${rel !== null ? pct(rel, Math.abs(rel) < 0.01 ? 1 : 0) : r.fmt(delta)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {scen.linesDeferredBudget > 0 && (
          <p className="mx-4 mt-2 rounded-md bg-risk-med-bg px-3 py-2 text-sm text-ink" data-testid="budget-note">
            <strong>The budget limits this scenario.</strong> Only the highest-priority orders are funded, so {scen.linesDeferredBudget} lines are deferred by
            budget and expected shortages after ordering rise. The steady-state annual costs describe the policy itself, so a one-week budget cut does not change them.
          </p>
        )}
        {scen.linesDeferredCapacity > base.linesDeferredCapacity && (
          <p className="mx-4 mt-2 rounded-md bg-risk-med-bg px-3 py-2 text-sm text-ink" data-testid="capacity-note">
            <strong>Supplier capacity limits this scenario.</strong> It asks for more units than the simulated suppliers can ship this review, so{" "}
            {scen.linesDeferredCapacity - base.linesDeferredCapacity} more lines are deferred by capacity. That is why expected shortages can rise even as safety stock goes up.
          </p>
        )}
        <p className="px-4 py-2 text-xs text-muted">
          Annual costs are steady-state approximations of the policy (average stock = safety stock + half a lot; shortages from the normal loss function). Purchase spend is not a cost. All costs use simulated unit costs.
        </p>
      </div>
    </Card>
  );
}

function CostChart({ base, scen }: { base: PlanSummary; scen: PlanSummary }) {
  const chart = [
    { name: "Holding", Balanced: base.annualHoldingCost, Scenario: scen.annualHoldingCost },
    { name: "Ordering", Balanced: base.annualOrderingCost, Scenario: scen.annualOrderingCost },
    { name: "Shortage penalty", Balanced: base.annualShortageCost, Scenario: scen.annualShortageCost },
  ];
  return (
    <Card title="Modeled annual cost by component">
      <div className="h-60 px-2 py-3" role="img" aria-label="Bar chart comparing modeled annual cost components for the Balanced plan and the scenario">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} margin={{ left: 8, right: 16, top: 8, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="#e6ebf0" />
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#3e4b5b" }} />
            <YAxis tickFormatter={(v: number) => compactUsd(v)} tick={{ fontSize: 11, fill: "#66727f" }} width={64} />
            <Tooltip formatter={(v) => usd(v as number, 0)} cursor={{ fill: "#f1f4f7" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Balanced" fill="#9aa6b2" isAnimationActive={false} />
            <Bar dataKey="Scenario" fill="#217e83" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function Backtest({ data }: { data: AppData }) {
  const sim = data.simulation;
  const [scope, setScope] = useQueryState("bt", "model_stores");
  const rows = sim.summary.filter((s) => s.scope === scope);
  const order = { basic: 0, forecast_v1: 1, forecast: 2 } as const;
  const sorted = (w: string) => rows.filter((s) => s.window === w).sort((a, b) => order[a.policy] - order[b.policy]);
  const sens = sim.sensitivity.filter((s) => s.scope === scope && s.window === "main" && s.margin_shift === 0 && s.shortage_multiplier === 1.5);
  const sensRow = (oc: number, p: string) => sens.find((s) => s.order_cost_multiplier === oc && s.policy === p)?.modeled_total_cost ?? null;
  const synthetic = data.manifest.source === "synthetic";
  return (
    <Card
      title={`Historical backtest — 182 simulated days on ${synthetic ? "synthetic" : "recorded"} sales`}
      aside={
        <SelectField label="" value={scope} onChange={setScope} testId="bt-scope" options={[{ value: "model_stores", label: "All products, both stores" }, { value: "demo", label: "Demo products only" }]} />
      }
    >
      <div className="space-y-4 px-4 py-4">
        {synthetic && (
          <p className="rounded-md bg-amber-100 px-3 py-2 text-sm text-navy" data-testid="synthetic-backtest-note">
            <strong>Synthetic demo data.</strong> These figures come from running the same simulation on randomly generated sales. They are not the
            Walmart M5 research results described in the project documentation.
          </p>
        )}
        <p className="text-sm">
          Each policy starts with the same simulated stock and faces the same {synthetic ? "synthetic" : "recorded"} sales, supplier lead-time draws and cost
          assumptions. The forecast policies only use information available on each simulated day.
        </p>
        <ul className="space-y-1 text-sm" data-testid="evidence-labels">
          <li><strong className="text-navy">v1</strong> was specified before any simulation was run, so its development-window result is a genuine first test.</li>
          <li><strong className="text-navy">v2</strong> was designed <em>after</em> v1 failed in the development window of the M5 research, so its development-window result is <strong>not independent</strong>. The confirmation window was excluded from that redesign and evaluated once: it is v2&apos;s only out-of-sample check.</li>
        </ul>
        {(["main", "confirmation"] as const).map((w) => (
          <div key={w} className="overflow-x-auto">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
              {w === "main" ? `Development window · ${sim.window.start} to ${sim.window.end}` : `Confirmation window (held out from v2 design) · ${sim.confirmationWindow.start} to ${sim.confirmationWindow.end}`}
            </h3>
            <SimTable rows={sorted(w)} />
          </div>
        ))}
        <BreakEven rows={rows} />
        <div className="overflow-x-auto">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Sensitivity: modeled total cost vs assumed cost per purchase-order line (development window)</h3>
          <table className="w-full max-w-xl text-sm" data-testid="sensitivity-table">
            <thead>
              <tr className="border-b border-line text-xs uppercase text-muted">
                <th scope="col" className="px-3 py-1.5 text-left">Order cost per line</th>
                <th scope="col" className="px-3 py-1.5 text-right">Basic</th>
                <th scope="col" className="px-3 py-1.5 text-right">Forecast v2</th>
                <th scope="col" className="px-3 py-1.5 text-right">Difference</th>
              </tr>
            </thead>
            <tbody>
              {[0.25, 0.5, 1].map((oc) => {
                const b = sensRow(oc, "basic");
                const f = sensRow(oc, "forecast");
                return (
                  <tr key={oc} className="border-b border-line/70">
                    <th scope="row" className="px-3 py-1.5 text-left font-normal">{oc === 1 ? "As assumed ($4–$9)" : `${oc * 100}% of assumed`}</th>
                    <td className="tabular px-3 py-1.5 text-right">{compactUsd(b)}</td>
                    <td className="tabular px-3 py-1.5 text-right">{compactUsd(f)}</td>
                    <td className="tabular px-3 py-1.5 text-right">{b !== null && f !== null ? `${f - b > 0 ? "+" : ""}${compactUsd(f - b)}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

/** Break-even ordering cost: every modeled cost component is linear in its assumption (decisions held fixed). */
/**
 * How v2's modeled cost compares with the basic rule as the assumed ordering cost per PO line changes.
 * Every component is linear in its assumption (decisions held fixed):
 *   v2 - basic = dFixed + k * dOrder, where dFixed = holding + shortage difference and k = order-cost multiplier.
 */
function BreakEven({ rows }: { rows: SimSummary[] }) {
  const verdict = (w: string) => {
    const b = rows.find((r) => r.window === w && r.policy === "basic");
    const v = rows.find((r) => r.window === w && r.policy === "forecast");
    if (!b || !v) return null;
    const dFixed = v.holding_cost - b.holding_cost + v.shortage_penalty - b.shortage_penalty;
    const dOrder = v.ordering_cost - b.ordering_cost;
    if (dOrder < 0 && dFixed > 0) return { kind: "v2-above" as const, k: dFixed / -dOrder };
    if (dOrder > 0 && dFixed < 0) return { kind: "v2-below" as const, k: -dFixed / dOrder };
    if (dFixed + dOrder < 0) return { kind: "v2-always" as const, k: null };
    return { kind: "basic-always" as const, k: null };
  };
  const vs = [verdict("main"), verdict("confirmation")].filter((x): x is NonNullable<ReturnType<typeof verdict>> => x !== null);
  if (vs.length === 0) return null;
  const kinds = new Set(vs.map((x) => x.kind));
  let text: React.ReactNode;
  if (kinds.size === 1 && vs[0].kind === "v2-above") {
    const ks = vs.map((x) => x.k as number);
    const lo = Math.min(...ks);
    const hi = Math.max(...ks);
    text = (
      <>
        v2&apos;s lower modeled cost comes from fewer purchase-order lines. It is cheaper only while each order line costs more than about{" "}
        <strong>{pct(lo, 0)}–{pct(hi, 0)}</strong> of the assumed $4–$9 (roughly ${(4 * lo).toFixed(2)}–${(9 * hi).toFixed(2)} per line). Below that, the basic rule is cheaper.
      </>
    );
  } else if (kinds.size === 1 && vs[0].kind === "v2-always") {
    text = <>In these results v2 also has lower holding and shortage costs, so its modeled cost is lower at any ordering cost. That conclusion still rests on the simulated cost assumptions.</>;
  } else if (kinds.size === 1 && vs[0].kind === "basic-always") {
    text = <>The basic rule has the lower modeled cost at any ordering cost in these results.</>;
  } else {
    text = <>The windows disagree on which policy is cheaper as the ordering cost changes, so the cost comparison is not robust.</>;
  }
  return (
    <p className="rounded-md bg-risk-med-bg px-3 py-2 text-sm text-ink" data-testid="break-even">
      <strong>Cost comparisons depend on assumptions.</strong> {text} Ordering, holding and shortage costs are simulated.
    </p>
  );
}

function SimTable({ rows }: { rows: SimSummary[] }) {
  return (
    <table className="w-full text-sm" data-testid="backtest-table">
      <thead>
        <tr className="border-b border-line text-xs uppercase text-muted">
          <th scope="col" className="px-3 py-1.5 text-left">Policy</th>
          <th scope="col" className="px-3 py-1.5 text-right" title="Share of demand units filled from stock">Fill rate</th>
          <th scope="col" className="px-3 py-1.5 text-right" title="Share of replenishment cycles with no lost sales">Cycle service</th>
          <th scope="col" className="px-3 py-1.5 text-right">Lost units</th>
          <th scope="col" className="px-3 py-1.5 text-right">Avg inventory</th>
          <th scope="col" className="px-3 py-1.5 text-right">Order lines</th>
          <th scope="col" className="px-3 py-1.5 text-right">Holding</th>
          <th scope="col" className="px-3 py-1.5 text-right">Ordering</th>
          <th scope="col" className="px-3 py-1.5 text-right">Shortage</th>
          <th scope="col" className="px-3 py-1.5 text-right">Modeled cost</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.policy} className={`border-b border-line/70 ${s.policy === "forecast" ? "bg-teal-50/60" : ""}`}>
            <th scope="row" className="px-3 py-1.5 text-left font-normal">{s.policy_label}</th>
            <td className="tabular px-3 py-1.5 text-right">{pct(s.fill_rate, 2)}</td>
            <td className="tabular px-3 py-1.5 text-right">{pct(s.cycle_service_level, 1)}</td>
            <td className="tabular px-3 py-1.5 text-right">{int(s.lost_units)}</td>
            <td className="tabular px-3 py-1.5 text-right">{compactUsd(s.avg_inventory_value)}</td>
            <td className="tabular px-3 py-1.5 text-right">{int(s.purchase_orders)}</td>
            <td className="tabular px-3 py-1.5 text-right">{compactUsd(s.holding_cost)}</td>
            <td className="tabular px-3 py-1.5 text-right">{compactUsd(s.ordering_cost)}</td>
            <td className="tabular px-3 py-1.5 text-right">{compactUsd(s.shortage_penalty)}</td>
            <td className="tabular px-3 py-1.5 text-right font-semibold text-navy">{compactUsd(s.modeled_total_cost)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
