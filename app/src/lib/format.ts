// Formatting helpers. Every helper returns a readable dash for null, NaN or Infinity,
// so the interface never displays "NaN" or "Infinity".

const DASH = "—";

const ok = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);

export function int(x: number | null | undefined): string {
  return ok(x) ? Math.round(x).toLocaleString("en-US") : DASH;
}

export function num(x: number | null | undefined, digits = 1): string {
  return ok(x) ? x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : DASH;
}

export function usd(x: number | null | undefined, digits = 0): string {
  return ok(x)
    ? x.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits })
    : DASH;
}

export function compactUsd(x: number | null | undefined): string {
  if (!ok(x)) return DASH;
  const sign = x < 0 ? "-" : "";
  const a = Math.abs(x);
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${sign}$${(a / 1e3).toFixed(1)}K`;
  return `${sign}${usd(a)}`;
}

export function pct(x: number | null | undefined, digits = 1): string {
  return ok(x) ? `${(x * 100).toFixed(digits)}%` : DASH;
}

export function days(x: number | null | undefined): string {
  if (!ok(x)) return DASH;
  if (x >= 365) return "365+ d";
  return `${x.toFixed(x < 10 ? 1 : 0)} d`;
}

/** Add whole days to an ISO date (UTC, no time-zone drift). */
export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function longDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export const CATEGORY_LABEL: Record<string, string> = { FOODS: "Foods", HOBBIES: "Hobbies", HOUSEHOLD: "Household" };
export const PATTERN_LABEL: Record<string, string> = {
  smooth: "Smooth",
  erratic: "Erratic",
  intermittent: "Intermittent",
  lumpy: "Lumpy",
  no_demand: "No demand",
};
