"use client";

import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => number | string | null;
  align?: "left" | "right" | "center";
  className?: string;
  title?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  initialSort?: { key: string; dir: "asc" | "desc" };
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  pageSize?: number;
  empty?: ReactNode;
  caption: string;
  testId?: string;
  dense?: boolean;
}

export function DataTable<T>({ columns, rows, rowKey, initialSort, onRowClick, selectedKey, pageSize = 25, empty, caption, testId, dense = false }: Props<T>) {
  const pad = dense ? "px-2" : "px-3";
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const sv = col.sortValue;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = sv(a);
      const y = sv(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1; // missing values always last
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * dir;
    });
  }, [rows, sort, columns]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * pageSize, current * pageSize + pageSize);

  const toggle = (key: string) => {
    setPage(0);
    setSort((s) => (s?.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  };

  if (rows.length === 0) return <>{empty}</>;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm" data-testid={testId}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-line bg-canvas/60 text-xs uppercase tracking-wide text-muted">
              {columns.map((c) => {
                const active = sort?.key === c.key;
                const ariaSort = active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none";
                return (
                  <th key={c.key} scope="col" aria-sort={c.sortValue ? ariaSort : undefined} className={`whitespace-nowrap ${pad} py-2 font-semibold ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left"} ${c.className ?? ""}`} title={c.title}>
                    {c.sortValue ? (
                      <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 rounded uppercase hover:text-navy">
                        {c.label}
                        <span aria-hidden className={active ? "text-navy" : "text-line"}>
                          {active ? (sort!.dir === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </button>
                    ) : (
                      c.label
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const k = rowKey(r);
              const sel = selectedKey === k;
              return (
                <tr
                  key={k}
                  data-row-id={k}
                  tabIndex={onRowClick ? 0 : undefined}
                  aria-selected={onRowClick ? sel : undefined}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(r);
                          }
                        }
                      : undefined
                  }
                  className={`border-b border-line/70 ${onRowClick ? "cursor-pointer hover:bg-teal-50/60" : ""} ${sel ? "bg-teal-50" : ""}`}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={`whitespace-nowrap ${pad} py-2 ${c.align === "right" ? "tabular text-right" : c.align === "center" ? "text-center" : ""} ${c.className ?? ""}`}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-muted">
          <span>
            {current * pageSize + 1}–{Math.min((current + 1) * pageSize, sorted.length)} of {sorted.length}
          </span>
          <div className="flex gap-1">
            <button type="button" className="rounded border border-line px-2 py-1 hover:bg-canvas disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>
              Previous
            </button>
            <button type="button" className="rounded border border-line px-2 py-1 hover:bg-canvas disabled:opacity-40" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
