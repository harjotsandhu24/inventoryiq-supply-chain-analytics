"use client";

import { useId, useState, type ReactNode } from "react";
import type { Risk } from "@/lib/types";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className = "", title, aside, id }: { children: ReactNode; className?: string; title?: string; aside?: ReactNode; id?: string }) {
  return (
    <section id={id} className={`rounded-lg border border-line bg-white ${className}`} aria-label={title}>
      {title && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-navy">{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, tone = "default", testId }: { label: string; value: string; sub?: ReactNode; tone?: "default" | "alert"; testId?: string }) {
  return (
    <div className="rounded-lg border border-line bg-white px-4 py-3" data-testid={testId}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`tabular mt-1 text-2xl font-semibold ${tone === "alert" ? "text-risk-high" : "text-navy"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

const RISK_STYLE: Record<Risk, string> = {
  High: "bg-risk-high-bg text-risk-high",
  Medium: "bg-risk-med-bg text-risk-med",
  Low: "bg-risk-low-bg text-risk-low",
};

export function RiskBadge({ risk }: { risk: Risk }) {
  return <span className={`inline-flex rounded px-2 py-0.5 text-xs font-semibold ${RISK_STYLE[risk]}`}>{risk}</span>;
}

export function StatusText({ status }: { status: string }) {
  const tone = status.startsWith("Deferred") ? "text-risk-high" : status.startsWith("Reduced") ? "text-risk-med" : status === "Order" ? "text-teal-700" : "text-muted";
  return <span className={`text-xs font-medium ${tone}`}>{status}</span>;
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" };

export function Button({ variant = "secondary", className = "", ...p }: BtnProps) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const v = {
    primary: "bg-teal text-white hover:bg-teal-700 active:bg-navy disabled:hover:bg-teal",
    secondary: "border border-line bg-white text-navy hover:border-navy/40 hover:bg-navy-50 active:bg-navy-50",
    ghost: "text-teal-700 hover:bg-teal-50 active:bg-teal-50",
  }[variant];
  return <button type="button" className={`${base} ${v} ${className}`} {...p} />;
}

export function SelectField({ label, value, onChange, options, testId }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testId?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs font-medium text-muted">
      {label}
      <select
        id={id}
        value={value}
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 min-w-[9rem] rounded-md border border-line bg-white px-2 text-sm text-ink hover:border-navy/40"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SearchField({ value, onChange, placeholder = "Search product or ID" }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs font-medium text-muted">
      Search
      <input
        id={id}
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-56 rounded-md border border-line bg-white px-3 text-sm text-ink placeholder:text-muted/70 hover:border-navy/40"
      />
    </label>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center" role="status">
      <p className="text-sm font-semibold text-navy">{title}</p>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-navy hover:bg-canvas"
      >
        {summary}
        <span aria-hidden className={`transition-transform ${open ? "rotate-90" : ""}`}>›</span>
      </button>
      {open && <div className="border-t border-line px-4 py-3 text-sm leading-relaxed">{children}</div>}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; swatch: ReactNode }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          {i.swatch}
          {i.label}
        </li>
      ))}
    </ul>
  );
}
