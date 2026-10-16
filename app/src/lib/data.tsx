"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { recommend, type EngineLine, type Recommendation } from "./engine/engine";
import type { Evaluation, LineData, Manifest, SeriesForecast, Settings, Simulation, Supplier } from "./types";

export interface AppData {
  manifest: Manifest;
  lines: LineData[];
  suppliers: Supplier[];
  evaluation: Evaluation;
  simulation: Simulation;
  /** Recommendations under the immutable default (Balanced) settings. */
  baseline: Recommendation[];
  baselineById: Map<string, Recommendation>;
  lineById: Map<string, LineData>;
}

type State = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: AppData };

const Ctx = createContext<State>({ status: "loading" });

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "force-cache" });
  if (!res.ok) throw new Error(`Could not load ${path} (HTTP ${res.status}).`);
  return (await res.json()) as T;
}

export function toEngineLines(lines: LineData[]): EngineLine[] {
  return lines;
}

export function defaultSettings(m: Manifest): Settings {
  return { ...m.defaults };
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });
  useEffect(() => {
    let alive = true;
    Promise.all([
      getJson<Manifest>("/data/manifest.json"),
      getJson<LineData[]>("/data/lines.json"),
      getJson<Supplier[]>("/data/suppliers.json"),
      getJson<Evaluation>("/data/evaluation.json"),
      getJson<Simulation>("/data/simulation.json"),
    ])
      .then(([manifest, lines, suppliers, evaluation, simulation]) => {
        if (!alive) return;
        const baseline = recommend(toEngineLines(lines), defaultSettings(manifest), manifest.capacity, manifest.planningDay);
        setState({
          status: "ready",
          data: {
            manifest,
            lines,
            suppliers,
            evaluation,
            simulation,
            baseline,
            baselineById: new Map(baseline.map((r) => [r.id, r])),
            lineById: new Map(lines.map((l) => [l.id, l])),
          },
        });
      })
      .catch((e: unknown) => alive && setState({ status: "error", message: e instanceof Error ? e.message : String(e) }));
    return () => {
      alive = false;
    };
  }, []);
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export function useAppState(): State {
  return useContext(Ctx);
}

const forecastCache = new Map<string, Promise<SeriesForecast>>();

export function useSeriesForecast(id: string | null) {
  const [state, setState] = useState<{ id: string | null; data: SeriesForecast | null; error: string | null }>({ id: null, data: null, error: null });
  useEffect(() => {
    if (!id) return;
    let alive = true;
    let p = forecastCache.get(id);
    if (!p) {
      p = getJson<SeriesForecast>(`/data/forecasts/${encodeURIComponent(id)}.json`);
      forecastCache.set(id, p);
      p.catch(() => forecastCache.delete(id));
    }
    p.then((d) => alive && setState({ id, data: d, error: null })).catch(
      (e: unknown) => alive && setState({ id, data: null, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      alive = false;
    };
  }, [id]);
  const current = state.id === id;
  return { data: current ? state.data : null, error: current ? state.error : null, loading: !!id && !current };
}

export function useMemoRecs(lines: LineData[], settings: Settings, capacity: Record<string, number>, day: number) {
  return useMemo(() => {
    try {
      return { recs: recommend(lines, settings, capacity, day), error: null as string | null };
    } catch (e) {
      return { recs: null, error: e instanceof Error ? e.message : String(e) };
    }
  }, [lines, settings, capacity, day]);
}
