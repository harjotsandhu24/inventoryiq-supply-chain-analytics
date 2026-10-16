"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAppState } from "@/lib/data";
import { longDate } from "@/lib/format";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/forecasts", label: "Demand Forecasts" },
  { href: "/planner", label: "Replenishment Planner" },
  { href: "/scenarios", label: "Scenario Lab" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const state = useAppState();
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-navy">
        Skip to content
      </a>
      <header className="bg-navy text-white">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <Link href="/" className="flex items-center gap-2 text-[17px] font-semibold tracking-tight">
            <span aria-hidden className="inline-block h-5 w-5 rounded-sm border-2 border-teal-50 bg-teal" />
            InventoryIQ
          </Link>
          <nav aria-label="Main" className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={`whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                    active ? "bg-white/15 text-white" : "text-white/75 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-white/80">
            {state.status === "ready" && (
              <>
                <span>
                  Planning date <strong className="text-white">{longDate(state.data.manifest.planningDate)}</strong>
                </span>
                <span
                  className={`rounded px-2 py-0.5 font-medium ${state.data.manifest.source === "m5" ? "bg-white/15 text-white" : "bg-amber-300 text-navy"}`}
                  title={state.data.manifest.sourceLabel}
                  data-testid="source-badge"
                >
                  {state.data.manifest.source === "m5" ? "M5 sales · simulated inventory" : "Synthetic demo data"}
                </span>
              </>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[1440px] px-4 pb-16 pt-6 sm:px-6">
        {state.status === "loading" && <LoadingState />}
        {state.status === "error" && <ErrorState message={state.message} />}
        {state.status === "ready" && children}
      </main>
      <footer className="mx-auto max-w-[1440px] px-4 pb-8 text-xs text-muted sm:px-6">
        {state.status === "ready" && state.data.manifest.source === "synthetic" ? (
          <>
            <strong>Synthetic demo data:</strong> randomly generated sales, prices and calendar in the M5 file layout. These are not Walmart records.{" "}
            <strong>Modeled:</strong> forecasts, safety stock and recommendations. <strong>Simulated:</strong> suppliers, stock on hand, purchase orders and costs.
          </>
        ) : (
          <>
            <strong>Observed:</strong> Walmart M5 sales, prices and calendar. <strong>Modeled:</strong> forecasts, safety stock and recommendations.{" "}
            <strong>Simulated:</strong> suppliers, stock on hand, purchase orders and costs (assumptions, not Walmart operations).
          </>
        )}
      </footer>
    </div>
  );
}

export function LoadingState({ label = "Loading planning data…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-3 rounded-lg border border-line bg-white p-6 text-sm">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-teal border-t-transparent" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-risk-high/30 bg-risk-high-bg p-6 text-sm text-risk-high">
      <p className="font-semibold">The planning data could not be loaded.</p>
      <p className="mt-1">{message}</p>
      <p className="mt-3 text-ink">
        Run <code className="rounded bg-white px-1">python -m inventoryiq.pipeline --source m5</code> (or{" "}
        <code className="rounded bg-white px-1">npm run data:demo</code> for synthetic demo data), then reload the page.
      </p>
    </div>
  );
}
