"use client";

import { Suspense, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { LoadingState } from "@/components/AppShell";
import { Card, Disclosure, EmptyState, Legend, PageHeader, SelectField } from "@/components/ui";
import { useAppState, useSeriesForecast, type AppData } from "@/lib/data";
import { addDays, CATEGORY_LABEL, longDate, num, PATTERN_LABEL, pct, shortDate } from "@/lib/format";
import type { SeriesForecast } from "@/lib/types";
import { usePushQuery, useQueryState, useUrlValue } from "@/lib/useQueryState";

const METHOD_LABEL: Record<string, string> = {
  seasonal_naive: "Seasonal naive",
  moving_average: "Moving average",
  seasonal_ma: "Seasonal moving average",
  sba: "Croston-SBA",
  gbm: "Gradient boosting",
  selected: "Selected per product",
};
const COLORS = { history: "#172d47", actual: "#172d47", forecast: "#217e83", band: "#217e83", other: "#9aa6b2" };

export default function ForecastsPage() {
  return (
    <Suspense>
      <Forecasts />
    </Suspense>
  );
}

function Forecasts() {
  const state = useAppState();
  if (state.status !== "ready") return null;
  return <ForecastsReady data={state.data} />;
}

interface Point {
  date: string;
  history?: number | null;
  actual?: number | null;
  forecast?: number | null;
  future?: number | null;
  band?: [number, number] | null;
  naive?: number | null;
}

function buildPoints(f: SeriesForecast, weekly: boolean, compare: boolean): Point[] {
  const pts: Point[] = [];
  f.history.values.forEach((v, i) => pts.push({ date: addDays(f.history.start, i), history: v }));
  f.holdout.actual.forEach((v, i) =>
    pts.push({
      date: addDays(f.holdout.start, i),
      actual: v,
      forecast: f.holdout.selected[i],
      band: f.holdout.lo80[i] !== null && f.holdout.hi80[i] !== null ? [f.holdout.lo80[i]!, f.holdout.hi80[i]!] : null,
      naive: compare ? f.holdout.forecast.seasonal_naive?.[i] ?? null : null,
    }),
  );
  f.future.selected.forEach((v, i) =>
    pts.push({
      date: addDays(f.future.start, i),
      future: v,
      band: f.future.lo80[i] !== null && f.future.hi80[i] !== null ? [f.future.lo80[i]!, f.future.hi80[i]!] : null,
    }),
  );
  if (!weekly) return pts;
  // Weekly totals (7-day buckets aligned to the end of the history); intervals are not additive, so they are omitted.
  const out: Point[] = [];
  for (let i = pts.length % 7; i < pts.length; i += 7) {
    const chunk = pts.slice(i, i + 7);
    const sum = (k: keyof Point) => {
      const vals = chunk.map((p) => p[k]).filter((v): v is number => typeof v === "number");
      return vals.length === chunk.length ? vals.reduce((a, b) => a + b, 0) : null;
    };
    out.push({ date: chunk[0].date, history: sum("history"), actual: sum("actual"), forecast: sum("forecast"), future: sum("future"), naive: compare ? sum("naive") : null });
  }
  return out;
}

function ForecastsReady({ data }: { data: AppData }) {
  const { manifest, lines, lineById, evaluation } = data;
  const [store, setStore] = useQueryState("store", manifest.demo.stores[0]);
  const lineParam = useUrlValue("line", "");
  const push = usePushQuery();
  const [weekly, setWeekly] = useState(false);
  const [compare, setCompare] = useState(true);

  const storeLines = useMemo(() => lines.filter((l) => l.store === store).sort((a, b) => a.item.localeCompare(b.item)), [lines, store]);
  // Default to the store's highest-value product: a representative, readable first view.
  const defaultLine = useMemo(() => [...storeLines].sort((a, b) => b.value364 - a.value364)[0] ?? null, [storeLines]);
  const requested = lineById.get(lineParam);
  const line = requested && requested.store === store ? requested : defaultLine;
  const { data: fc, error, loading } = useSeriesForecast(line?.id ?? null);
  const points = useMemo(() => (fc ? buildPoints(fc, weekly, compare) : []), [fc, weekly, compare]);
  const cov = line ? evaluation.coverageByPattern.find((c) => c.pattern === line.pattern) : undefined;

  const methods = fc ? (["selected", "seasonal_naive", "moving_average", "seasonal_ma", "sba", "gbm"] as const).filter((m) => fc.metrics[m] && m !== fc.method) : [];
  const portfolio = evaluation.holdoutModelStores;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Demand forecasts"
        subtitle="Daily unit sales with a 28-day forecast. Each product uses the method that was most accurate in five earlier test windows; the final 28 observed days were held back to check it honestly."
      />
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label="Store"
          value={store}
          testId="fc-store"
          onChange={(s) => setStore(s)}
          options={manifest.demo.stores.map((s) => ({ value: s, label: s }))}
        />
        <SelectField
          label="Product"
          value={line?.id ?? ""}
          testId="fc-product"
          onChange={(id) => push("line", id)}
          options={storeLines.map((l) => ({ value: l.id, label: `${l.item} · ${PATTERN_LABEL[l.pattern] ?? l.pattern}` }))}
        />
        <fieldset className="flex items-center gap-1 rounded-md border border-line bg-white p-1 text-sm" aria-label="Time grain">
          {[false, true].map((w) => (
            <button key={String(w)} type="button" aria-pressed={weekly === w} onClick={() => setWeekly(w)} className={`rounded px-3 py-1 ${weekly === w ? "bg-navy text-white" : "text-ink hover:bg-canvas"}`}>
              {w ? "Weekly" : "Daily"}
            </button>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="h-4 w-4 accent-teal" />
          Show seasonal-naive benchmark
        </label>
      </div>

      {!line ? (
        <Card><EmptyState title="No products in this store" /></Card>
      ) : (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card title={`${line.item} · ${line.store}`} aside={<span className="text-xs text-muted">{CATEGORY_LABEL[line.cat]} · {PATTERN_LABEL[line.pattern]} demand · ABC {line.abc} / XYZ {line.xyz}</span>}>
            {loading && <div className="p-4"><LoadingState label="Loading forecast…" /></div>}
            {error && <div className="p-4"><EmptyState title="Forecast data unavailable for this product" hint={error} /></div>}
            {fc && (
              <div className="px-2 pb-3 pt-4">
                <div className="px-3 pb-2">
                  <Legend
                    items={[
                      { label: "Observed sales (history)", swatch: <span className="h-0.5 w-5 bg-navy" /> },
                      { label: "Held-back actuals", swatch: <span className="h-2 w-2 rounded-full bg-navy" /> },
                      { label: "Forecast", swatch: <span className="h-0.5 w-5 border-t-2 border-dashed border-teal" /> },
                      ...(!weekly ? [{ label: "80% prediction interval", swatch: <span className="h-3 w-5 rounded-sm bg-teal/20" /> }] : []),
                      ...(compare ? [{ label: "Seasonal naive (benchmark)", swatch: <span className="h-0.5 w-5 bg-[#9aa6b2]" /> }] : []),
                    ]}
                  />
                </div>
                <div className="h-[380px]" role="img" aria-label={`Line chart of daily unit sales and forecast for ${line.item} in ${line.store}`} data-testid="forecast-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={points} margin={{ left: 4, right: 16, top: 22, bottom: 4 }}>
                      <CartesianGrid stroke="#e6ebf0" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={40} tick={{ fontSize: 11, fill: "#66727f" }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#66727f" }} width={40} label={{ value: weekly ? "Units / week" : "Units / day", angle: -90, position: "insideLeft", fontSize: 11, fill: "#66727f" }} />
                      <Tooltip labelFormatter={(d) => longDate(String(d))} formatter={(v, n) => [Array.isArray(v) ? `${num(v[0] as number, 1)} – ${num(v[1] as number, 1)}` : num(v as number, 1), n]} />
                      {!weekly && <Area dataKey="band" name="80% interval" stroke="none" fill={COLORS.band} fillOpacity={0.16} isAnimationActive={false} />}
                      <Line dataKey="history" name="Observed" stroke={COLORS.history} dot={false} strokeWidth={1.4} isAnimationActive={false} connectNulls={false} />
                      <Line dataKey="actual" name="Held-back actual" stroke={COLORS.actual} strokeWidth={0} dot={{ r: 2.5, fill: COLORS.actual }} isAnimationActive={false} />
                      {compare && <Line dataKey="naive" name="Seasonal naive" stroke={COLORS.other} dot={false} strokeWidth={1.2} isAnimationActive={false} />}
                      <Line dataKey="forecast" name="Forecast (holdout)" stroke={COLORS.forecast} strokeDasharray="5 3" dot={false} strokeWidth={2} isAnimationActive={false} />
                      <Line dataKey="future" name="Forecast (next 28 days)" stroke={COLORS.forecast} strokeDasharray="5 3" dot={false} strokeWidth={2} isAnimationActive={false} />
                      <ReferenceLine x={weekly ? undefined : fc.holdout.start} stroke="#66727f" strokeDasharray="2 2" label={{ value: "Held-back test", position: "top", fontSize: 11, fill: "#66727f" }} />
                      <ReferenceLine x={weekly ? undefined : fc.future.start} stroke="#172d47" label={{ value: "Planning date", position: "insideTopLeft", fontSize: 11, fill: "#172d47" }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <p className="px-3 pt-1 text-xs text-muted">
                  History to {longDate(addDays(fc.holdout.start, -1))}; held-back test {longDate(fc.holdout.start)}–{longDate(addDays(fc.holdout.start, 27))}; forecast from {longDate(fc.future.start)}.
                  {weekly && " Weekly view shows totals; prediction intervals apply to daily values only."}
                </p>
              </div>
            )}
          </Card>

          <div className="space-y-4">
            <Card title="Selected method">
              <div className="space-y-2 px-4 py-3 text-sm">
                <p className="text-lg font-semibold text-navy" data-testid="selected-method">{line.methodLabel}</p>
                <p className="text-muted">Chosen because it had the lowest error across five 28-day test windows before the held-back period.</p>
                <dl className="grid grid-cols-2 gap-2 pt-1">
                  <div className="rounded bg-canvas p-2"><dt className="text-xs text-muted">Expected demand</dt><dd className="tabular font-semibold text-navy">{num(line.mu, 2)} / day</dd></div>
                  <div className="rounded bg-canvas p-2"><dt className="text-xs text-muted">Forecast error σ</dt><dd className="tabular font-semibold text-navy">{num(line.sigma, 2)} / day</dd></div>
                </dl>
                {cov && (
                  <p className="rounded bg-risk-med-bg px-2 py-1.5 text-xs text-ink" data-testid="interval-caveat">
                    <strong>Intervals are too narrow.</strong> On held-back days, 80% intervals for {PATTERN_LABEL[line.pattern]?.toLowerCase()} products covered {pct(cov.coverage80, 0)} of days (95% intervals: {pct(cov.coverage95, 0)}). Treat the shaded band as optimistic.
                  </p>
                )}
                <p className="text-xs text-muted">Forecasts are modeled from recorded sales. Recorded sales miss demand lost during real stockouts.</p>
              </div>
            </Card>
            <Card title="Accuracy on held-back days">
              {fc ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="method-table">
                    <caption className="sr-only">Holdout accuracy by method for this product</caption>
                    <thead>
                      <tr className="border-b border-line text-xs uppercase text-muted">
                        <th scope="col" className="px-3 py-2 text-left">Method</th>
                        <th scope="col" className="px-3 py-2 text-right" title="Mean absolute error, units per day">MAE</th>
                        <th scope="col" className="px-3 py-2 text-right" title="Weighted absolute percentage error">WAPE</th>
                        <th scope="col" className="px-3 py-2 text-right" title="Positive = over-forecast">Bias</th>
                      </tr>
                    </thead>
                    <tbody>
                      {methods.map((m) => {
                        const x = fc.metrics[m];
                        const isSel = m === "selected";
                        return (
                          <tr key={m} className={`border-b border-line/70 ${isSel ? "bg-teal-50 font-semibold text-navy" : ""}`}>
                            <th scope="row" className="px-3 py-1.5 text-left font-normal">{isSel ? `${METHOD_LABEL[fc.method]} (selected)` : METHOD_LABEL[m]}</th>
                            <td className="tabular px-3 py-1.5 text-right">{num(x.mae, 2)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{x.wape === null ? "n/a" : pct(x.wape, 0)}</td>
                            <td className="tabular px-3 py-1.5 text-right">{x.bias === null ? "n/a" : pct(x.bias, 0)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="px-3 py-2 text-xs text-muted">n/a: percentage errors are undefined when no units sold in the test period.</p>
                </div>
              ) : (
                <div className="p-4"><LoadingState label="Loading…" /></div>
              )}
            </Card>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Portfolio accuracy — all products in the two California stores">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="portfolio-table">
              <caption className="sr-only">Holdout accuracy by method across all model-store products</caption>
              <thead>
                <tr className="border-b border-line text-xs uppercase text-muted">
                  <th scope="col" className="px-3 py-2 text-left">Method</th>
                  <th scope="col" className="px-3 py-2 text-right">WAPE</th>
                  <th scope="col" className="px-3 py-2 text-right">MASE</th>
                  <th scope="col" className="px-3 py-2 text-right">Bias</th>
                </tr>
              </thead>
              <tbody>
                {[...portfolio].sort((a, b) => (a.wape ?? 9) - (b.wape ?? 9)).map((r) => (
                  <tr key={r.method} className={`border-b border-line/70 ${r.method === "selected" ? "bg-teal-50 font-semibold text-navy" : ""}`}>
                    <th scope="row" className="px-3 py-1.5 text-left font-normal">{METHOD_LABEL[r.method] ?? r.method}</th>
                    <td className="tabular px-3 py-1.5 text-right">{pct(r.wape, 1)}</td>
                    <td className="tabular px-3 py-1.5 text-right">{num(r.mase, 3)}</td>
                    <td className="tabular px-3 py-1.5 text-right">{pct(r.bias, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-3 py-2 text-xs text-muted">
              Final 28 observed days ({longDate(manifest.holdout.start)}–{longDate(manifest.holdout.end)}), never used to choose methods or settings. Lower is better.
            </p>
          </div>
        </Card>
        <Disclosure summary="How the forecast works">
          <ul className="list-disc space-y-1.5 pl-5">
            <li>Five candidate methods are tested: seasonal naive (repeat last week), moving average, seasonal moving average, Croston-SBA for intermittent demand, and a gradient-boosting model trained across all products in both stores.</li>
            <li>Each method forecasts five separate 28-day windows using only data available before each window (rolling-origin validation). Settings such as the moving-average window are tuned on these windows only.</li>
            <li>Each product keeps the method with the lowest validation error; gradient boosting must beat the simpler methods by at least 2% to be chosen.</li>
            <li>Prediction intervals come from the method&apos;s own validation errors. They describe the range for a single day&apos;s sales, not uncertainty about the average.</li>
            <li>Recorded sales are not true demand: when a store ran out, lost sales were never recorded.</li>
          </ul>
        </Disclosure>
      </div>
    </div>
  );
}
