"use client";

import { Suspense, useMemo, useState } from "react";
import { CalculationPanel, receiptDate } from "@/components/CalculationPanel";
import { CapacityCard } from "@/components/CapacityCard";
import { DataTable, type Column } from "@/components/DataTable";
import { applyFilters, FilterBar, useLineFilters } from "@/components/Filters";
import { Button, Card, EmptyState, PageHeader, RiskBadge, SelectField } from "@/components/ui";
import { downloadText, recommendationRows, toCsv } from "@/lib/csv";
import { useAppState, type AppData } from "@/lib/data";
import type { Recommendation } from "@/lib/engine/engine";
import { days, int, num, usd } from "@/lib/format";
import { usePushQuery, useQueryState, useUrlValue } from "@/lib/useQueryState";

const LIST_KEY = "inventoryiq.purchaseList";
const RISK_ORDER = { High: 0, Medium: 1, Low: 2 } as const;

export default function PlannerPage() {
  return (
    <Suspense>
      <Planner />
    </Suspense>
  );
}

function Planner() {
  const state = useAppState();
  if (state.status !== "ready") return null;
  return <PlannerReady data={state.data} />;
}

function loadList(): string[] {
  try {
    const v = window.localStorage.getItem(LIST_KEY);
    return v ? (JSON.parse(v) as string[]) : [];
  } catch {
    return [];
  }
}

function PlannerReady({ data }: { data: AppData }) {
  const { manifest, baseline, lineById } = data;
  const f = useLineFilters();
  const [risk, setRisk] = useQueryState("risk", "all");
  const [show, setShow] = useQueryState("show", "needs");
  const selected = useUrlValue("line", "");
  const push = usePushQuery();
  // PlannerReady only mounts in the browser (after data has loaded), so reading storage here is safe.
  const [list, setList] = useState<string[]>(() => (typeof window === "undefined" ? [] : loadList()));
  const saveList = (next: string[]) => {
    setList(next);
    try {
      window.localStorage.setItem(LIST_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: list lives for this session only */
    }
  };

  const rows = useMemo(() => {
    let r = applyFilters(baseline, lineById, f);
    if (risk !== "all") r = r.filter((x) => x.risk === risk);
    if (show === "needs") r = r.filter((x) => x.needsOrder);
    return r;
  }, [baseline, lineById, f, risk, show]);

  const sel = selected ? data.baselineById.get(selected) ?? null : null;
  const listRecs = list.map((id) => data.baselineById.get(id)).filter((r): r is Recommendation => !!r && r.finalQty > 0);
  const listTotal = listRecs.reduce((a, r) => a + r.orderValue, 0);

  const exportRows = (recs: Recommendation[], name: string) =>
    downloadText(name, toCsv(recommendationRows(recs, lineById, (r) => receiptDate(manifest, r))));

  const columns: Column<Recommendation>[] = [
    {
      key: "pick",
      label: "List",
      align: "center",
      render: (r) => (
        <input
          type="checkbox"
          aria-label={`Add ${r.id} to purchase list`}
          checked={list.includes(r.id)}
          disabled={r.finalQty <= 0}
          onClick={(e) => e.stopPropagation()}
          onChange={() => saveList(list.includes(r.id) ? list.filter((x) => x !== r.id) : [...list, r.id])}
          className="h-4 w-4 accent-teal disabled:opacity-30"
        />
      ),
    },
    {
      key: "product",
      label: "Product",
      render: (r) => <span className="font-medium text-navy">{lineById.get(r.id)!.item}</span>,
      sortValue: (r) => lineById.get(r.id)!.item,
    },
    { key: "store", label: "Location", render: (r) => lineById.get(r.id)!.store, sortValue: (r) => lineById.get(r.id)!.store },
    { key: "risk", label: "Risk", render: (r) => <RiskBadge risk={r.risk} />, sortValue: (r) => -(RISK_ORDER[r.risk] * 2 - r.pStockoutLeadTime) },
    { key: "inv", label: "On hand", align: "right", render: (r) => `${int(r.onHand)}${r.onOrder > 0 ? ` (+${int(r.onOrder)})` : ""}`, sortValue: (r) => r.onHand, title: "On hand (+ in transit)" },
    { key: "cover", label: "Coverage", align: "right", render: (r) => days(r.coverageDays), sortValue: (r) => r.coverageDays },
    { key: "rop", label: "Reorder point", align: "right", render: (r) => num(r.reorderPoint, 1), sortValue: (r) => r.reorderPoint },
    {
      key: "qty",
      label: "Order qty",
      align: "right",
      render: (r) =>
        r.finalQty > 0 ? (
          <span className="font-semibold text-navy" title={r.status}>
            {int(r.finalQty)}
            {r.status.startsWith("Reduced") && <span className="ml-1 text-xs font-normal text-risk-med">reduced</span>}
          </span>
        ) : r.needsOrder ? (
          <span className="text-xs font-medium text-risk-high" title={r.status}>Deferred</span>
        ) : (
          "—"
        ),
      sortValue: (r) => r.finalQty,
    },
    { key: "cost", label: "Purchase cost", align: "right", render: (r) => (r.finalQty > 0 ? usd(r.orderValue, 2) : "—"), sortValue: (r) => r.orderValue },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Replenishment planner"
        subtitle="Purchase recommendations for the next review, after case packs, minimum order quantities and simulated supplier capacity. Select a row to see the full calculation."
        actions={
          <Button onClick={() => exportRows(rows, "inventoryiq_recommendations.csv")} disabled={rows.length === 0} data-testid="export-all">
            Export table (CSV)
          </Button>
        }
      />
      <FilterBar f={f} stores={manifest.demo.stores} cats={manifest.demo.categories}>
        <SelectField label="Risk" value={risk} onChange={setRisk} testId="filter-risk" options={[{ value: "all", label: "All risk levels" }, { value: "High", label: "High" }, { value: "Medium", label: "Medium" }, { value: "Low", label: "Low" }]} />
        <SelectField label="Show" value={show} onChange={setShow} testId="filter-show" options={[{ value: "needs", label: "Needs an order" }, { value: "all", label: "All products" }]} />
      </FilterBar>

      <div className={`grid grid-cols-1 items-start gap-4 ${sel ? "xl:grid-cols-[minmax(0,1fr)_420px]" : ""}`}>
        <Card title={`${rows.length} products`} aside={<span className="text-xs text-muted">Sorted by priority: risk, then stockout chance</span>}>
          <DataTable
            testId="planner-table"
            caption="Replenishment recommendations"
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
            initialSort={{ key: "risk", dir: "desc" }}
            selectedKey={sel?.id ?? null}
            onRowClick={(r) => push("line", r.id)}
            pageSize={15}
            dense
            empty={
              <EmptyState
                title={show === "needs" ? "No products need an order with these filters" : "No products match these filters"}
                hint="Try another store, category or risk level, or show all products."
                action={<Button variant="ghost" onClick={() => setShow("all")}>Show all products</Button>}
              />
            }
          />
        </Card>
        {sel && (
          <div className="xl:sticky xl:top-4 xl:self-start">
            <CalculationPanel
              key={sel.id}
              rec={sel}
              line={lineById.get(sel.id)!}
              manifest={manifest}
              inList={list.includes(sel.id)}
              onToggleList={() => saveList(list.includes(sel.id) ? list.filter((x) => x !== sel.id) : [...list, sel.id])}
              onClose={() => push("line", null)}
            />
          </div>
        )}
      </div>
      {selected && !sel && (
        <p role="alert" className="rounded-md bg-risk-high-bg px-3 py-2 text-sm text-risk-high">
          Product “{selected}” is not in the demo scope. Choose a product from the table.
        </p>
      )}

      <CapacityCard recs={baseline} suppliers={data.suppliers} />

      <Card title="Simulated purchase list" aside={<span className="tabular text-sm font-semibold text-navy" data-testid="list-total">{int(listRecs.length)} lines · {usd(listTotal, 2)}</span>}>
        {listRecs.length === 0 ? (
          <EmptyState title="Your purchase list is empty" hint="Tick products in the table, or open a product and choose “Add to purchase list”." />
        ) : (
          <div className="px-4 py-3">
            <ul className="divide-y divide-line text-sm" data-testid="purchase-list">
              {listRecs.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span className="font-medium text-navy">{r.id}</span>
                  <span className="tabular">
                    {int(r.finalQty)} units · {usd(r.orderValue, 2)} · arrives {receiptDate(manifest, r)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => exportRows(listRecs, "inventoryiq_purchase_list.csv")} data-testid="export-list">
                Export purchase list (CSV)
              </Button>
              <Button onClick={() => saveList([])}>Clear list</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
