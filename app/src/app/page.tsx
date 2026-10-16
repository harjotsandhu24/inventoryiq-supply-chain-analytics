"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataTable, type Column } from "@/components/DataTable";
import { applyFilters, FilterBar, useLineFilters } from "@/components/Filters";
import { Card, EmptyState, Kpi, Legend, PageHeader, RiskBadge } from "@/components/ui";
import type { Recommendation } from "@/lib/engine/engine";
import { useAppState, type AppData } from "@/lib/data";
import { CATEGORY_LABEL, compactUsd, days, int, pct, usd } from "@/lib/format";

const RISK_COLORS = { High: "#b42318", Medium: "#d08a1f", Low: "#7fb7a8" };
const RISK_ORDER = { High: 0, Medium: 1, Low: 2 } as const;

export default function OverviewPage() {
  return (
    <Suspense>
      <Overview />
    </Suspense>
  );
}

function Overview() {
  const state = useAppState();
  if (state.status !== "ready") return null;
  return <OverviewReady data={state.data} />;
}

function OverviewReady({ data }: { data: AppData }) {
  const f = useLineFilters();
  const router = useRouter();
  const { manifest, baseline, lineById } = data;
  const rows = useMemo(() => applyFilters(baseline, lineById, f), [baseline, lineById, f]);

  const kpi = useMemo(() => {
    let inv = 0;
    let absErr = 0;
    let actual = 0;
    let absNaive = 0;
    let actualNaive = 0;
    for (const r of rows) {
      const l = lineById.get(r.id)!;
      inv += r.onHand * r.unitCost;
      if (l.holdout && l.holdout.mae !== null) {
        absErr += l.holdout.mae * l.holdout.days;
        actual += l.holdout.actual;
      }
      if (l.holdoutNaive && l.holdoutNaive.mae !== null) {
        absNaive += l.holdoutNaive.mae * l.holdoutNaive.days;
        actualNaive += l.holdoutNaive.actual;
      }
    }
    return {
      high: rows.filter((r) => r.risk === "High").length,
      medium: rows.filter((r) => r.risk === "Medium").length,
      inv,
      need: rows.filter((r) => r.needsOrder).length,
      funded: rows.filter((r) => r.finalQty > 0).length,
      deferred: rows.filter((r) => r.status.startsWith("Deferred")).length,
      spend: rows.reduce((a, r) => a + r.orderValue, 0),
      wape: actual > 0 ? absErr / actual : null,
      wapeNaive: actualNaive > 0 ? absNaive / actualNaive : null,
    };
  }, [rows, lineById]);

  const chart = useMemo(() => {
    const cats = manifest.demo.categories;
    return cats.map((c) => {
      const rs = rows.filter((r) => lineById.get(r.id)!.cat === c);
      return {
        category: CATEGORY_LABEL[c] ?? c,
        High: rs.filter((r) => r.risk === "High").length,
        Medium: rs.filter((r) => r.risk === "Medium").length,
        Low: rs.filter((r) => r.risk === "Low").length,
      };
    });
  }, [rows, lineById, manifest.demo.categories]);

  const columns: Column<Recommendation>[] = [
    {
      key: "product",
      label: "Product",
      render: (r) => (
        <div>
          <div className="font-medium text-navy">{lineById.get(r.id)!.item}</div>
          <div className="text-xs text-muted">{lineById.get(r.id)!.dept}</div>
        </div>
      ),
      sortValue: (r) => lineById.get(r.id)!.item,
    },
    { key: "store", label: "Store", render: (r) => lineById.get(r.id)!.store, sortValue: (r) => lineById.get(r.id)!.store },
    { key: "risk", label: "Risk", render: (r) => <RiskBadge risk={r.risk} />, sortValue: (r) => -(RISK_ORDER[r.risk] * 2 - r.pStockoutLeadTime) },
    { key: "p", label: "Stockout chance", title: "Modeled probability of running out before a new order could arrive", align: "right", render: (r) => (r.onHand <= 0 && r.mu > 0 ? <span className="text-xs font-semibold text-risk-high">Out of stock now</span> : pct(r.pStockoutLeadTime, 0)), sortValue: (r) => (r.onHand <= 0 && r.mu > 0 ? 1.01 : r.pStockoutLeadTime) },
    { key: "onhand", label: "On hand", align: "right", render: (r) => int(r.onHand), sortValue: (r) => r.onHand },
    { key: "cover", label: "Coverage", title: "Days until simulated stock on hand runs out at forecast demand", align: "right", render: (r) => days(r.coverageDays), sortValue: (r) => r.coverageDays },
    { key: "lt", label: "Lead time", align: "right", render: (r) => `${r.leadTime} d`, sortValue: (r) => r.leadTime },
    { key: "qty", label: "Order qty", align: "right", render: (r) => (r.finalQty > 0 ? int(r.finalQty) : r.needsOrder ? <span className="text-risk-high">Deferred</span> : "—"), sortValue: (r) => r.finalQty },
    { key: "value", label: "Order value", align: "right", render: (r) => (r.finalQty > 0 ? usd(r.orderValue) : "—"), sortValue: (r) => r.orderValue },
  ];

  const plannerHref = `/planner${f.store !== "all" || f.cat !== "all" ? `?${new URLSearchParams({ ...(f.store !== "all" ? { store: f.store } : {}), ...(f.cat !== "all" ? { cat: f.cat } : {}) })}` : ""}`;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Inventory risk overview"
        subtitle={`${manifest.demo.lines} product-store lines in ${manifest.demo.stores.join(" and ")}. Recommendations use the Balanced policy (${pct(manifest.defaults.serviceLevel, 0)} cycle service level, weekly review).`}
        actions={
          <Link href={plannerHref} className="inline-flex items-center gap-1.5 rounded-md bg-teal px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 active:bg-navy" data-testid="review-purchases">
            Review purchases →
          </Link>
        }
      />
      <FilterBar f={f} stores={manifest.demo.stores} cats={manifest.demo.categories} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" data-testid="kpis">
        <Kpi testId="kpi-risk" label="Lines at stockout risk" value={int(kpi.high)} tone={kpi.high > 0 ? "alert" : "default"} sub={`+${int(kpi.medium)} at or below reorder point`} />
        <Kpi testId="kpi-inventory" label="Simulated inventory value" value={compactUsd(kpi.inv)} sub="On hand × simulated unit cost" />
        <Kpi testId="kpi-orders" label="Lines requiring an order" value={int(kpi.need)} sub={`${int(kpi.funded)} funded · ${int(kpi.deferred)} deferred by capacity`} />
        <Kpi testId="kpi-spend" label="Recommended purchase spend" value={compactUsd(kpi.spend)} sub="After supplier capacity limits" />
        <Kpi testId="kpi-accuracy" label="Forecast error (WAPE)" value={pct(kpi.wape, 0)} sub={kpi.wapeNaive !== null ? `vs ${pct(kpi.wapeNaive, 0)} seasonal naive · these lines, unseen final 28 days` : "Holdout: final 28 observed days"} />
      </div>
      {rows.length === 0 ? (
        <Card>
          <EmptyState title="No products match these filters" hint="Clear the search box or choose another store or category." action={<button type="button" className="text-sm font-medium text-teal-700 underline" onClick={f.reset}>Reset filters</button>} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <Card title="Products by risk" aside={<span className="text-xs text-muted">Click a row to open its purchasing calculation</span>}>
            <DataTable
              testId="risk-table"
              caption="Products ranked by inventory risk"
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              initialSort={{ key: "risk", dir: "desc" }}
              onRowClick={(r) => router.push(`/planner?line=${encodeURIComponent(r.id)}`)}
              pageSize={12}
            />
          </Card>
          <Card title="Risk by category">
            <div className="px-4 pt-3">
              <Legend items={(["High", "Medium", "Low"] as const).map((k) => ({ label: k, swatch: <span className="h-3 w-3 rounded-sm" style={{ background: RISK_COLORS[k] }} /> }))} />
            </div>
            <div className="h-64 px-2 pt-1" aria-label="Bar chart: number of lines by risk level and category" role="img">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
                  <CartesianGrid horizontal={false} stroke="#e6ebf0" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: "#66727f" }} label={{ value: "Product-store lines", position: "insideBottom", offset: -2, fontSize: 11, fill: "#66727f" }} height={36} />
                  <YAxis type="category" dataKey="category" tick={{ fontSize: 12, fill: "#3e4b5b" }} width={80} />
                  <Tooltip cursor={{ fill: "#f1f4f7" }} />
                  <Bar dataKey="High" stackId="r" fill={RISK_COLORS.High} />
                  <Bar dataKey="Medium" stackId="r" fill={RISK_COLORS.Medium} />
                  <Bar dataKey="Low" stackId="r" fill={RISK_COLORS.Low} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <dl className="space-y-1 border-t border-line px-4 py-3 text-xs text-muted">
              <div><dt className="inline font-semibold text-risk-high">High</dt> <dd className="inline">— out of stock now, or likely to run out before a new order can arrive.</dd></div>
              <div><dt className="inline font-semibold text-risk-med">Medium</dt> <dd className="inline">— at or below the reorder point.</dd></div>
              <div><dt className="inline font-semibold text-risk-low">Low</dt> <dd className="inline">— covered until the next review.</dd></div>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
