"use client";

import type { LineData } from "@/lib/types";
import { CATEGORY_LABEL } from "@/lib/format";
import { useUrlState } from "@/lib/useQueryState";
import { SearchField, SelectField } from "./ui";

export interface FilterState {
  store: string;
  cat: string;
  q: string;
  setStore: (v: string) => void;
  setCat: (v: string) => void;
  setQ: (v: string) => void;
  reset: () => void;
}

const FILTER_DEFAULTS = { store: "all", cat: "all", q: "" };

export function useLineFilters(): FilterState {
  const [s, update] = useUrlState(FILTER_DEFAULTS);
  return {
    store: s.store,
    cat: s.cat,
    q: s.q,
    setStore: (v) => update({ store: v }),
    setCat: (v) => update({ cat: v }),
    setQ: (v) => update({ q: v }),
    reset: () => update(FILTER_DEFAULTS),
  };
}

export function applyFilters<T extends { id: string }>(rows: T[], lines: Map<string, LineData>, f: Pick<FilterState, "store" | "cat" | "q">): T[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter((r) => {
    const l = lines.get(r.id);
    if (!l) return false;
    if (f.store !== "all" && l.store !== f.store) return false;
    if (f.cat !== "all" && l.cat !== f.cat) return false;
    if (q && !l.id.toLowerCase().includes(q) && !l.dept.toLowerCase().includes(q)) return false;
    return true;
  });
}

export function FilterBar({ f, stores, cats, children }: { f: FilterState; stores: string[]; cats: string[]; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-3" role="search" aria-label="Filter products">
      <SelectField label="Store" value={f.store} onChange={f.setStore} testId="filter-store" options={[{ value: "all", label: "All stores" }, ...stores.map((s) => ({ value: s, label: s }))]} />
      <SelectField label="Category" value={f.cat} onChange={f.setCat} testId="filter-category" options={[{ value: "all", label: "All categories" }, ...cats.map((c) => ({ value: c, label: CATEGORY_LABEL[c] ?? c }))]} />
      <SearchField value={f.q} onChange={f.setQ} />
      {children}
    </div>
  );
}
