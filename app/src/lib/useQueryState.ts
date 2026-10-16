"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";

/**
 * Local state mirrored into the URL query string.
 *
 * Local React state is the source of truth while the user interacts (no lag, no lost keystrokes);
 * every update is written to the URL synchronously with history.replaceState, which Next.js
 * syncs with useSearchParams. Reloading the page restores the values from the URL.
 */
export function useUrlState<T extends Record<string, string>>(defaults: T): [T, (patch: Partial<T>) => void] {
  const params = useSearchParams();
  const [state, setState] = useState<T>(() => {
    const init = { ...defaults };
    for (const k of Object.keys(defaults) as (keyof T)[]) {
      const v = params.get(k as string);
      if (v !== null) init[k] = v as T[keyof T];
    }
    return init;
  });
  const update = useCallback(
    (patch: Partial<T>) => {
      setState((prev) => {
        const next = { ...prev, ...patch };
        const url = new URL(window.location.href);
        for (const k of Object.keys(defaults)) {
          const v = next[k];
          if (v === undefined || v === defaults[k]) url.searchParams.delete(k);
          else url.searchParams.set(k, v);
        }
        window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
        return next;
      });
    },
    [defaults],
  );
  return [state, update];
}

/** Single URL value managed with useUrlState. */
export function useQueryState(key: string, fallback = ""): [string, (v: string) => void] {
  const [defaults] = useState(() => ({ [key]: fallback }));
  const [state, update] = useUrlState(defaults);
  return [state[key], (v: string) => update({ [key]: v })];
}

/** Push (not replace) a value, creating a browser history entry (used for product selection). */
export function usePushQuery() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  return useCallback(
    (key: string, v: string | null) => {
      const next = new URLSearchParams(Array.from(params.entries()));
      if (v === null || v === "") next.delete(key);
      else next.set(key, v);
      const qs = next.toString();
      router.push(qs ? `${path}?${qs}` : path, { scroll: false });
    },
    [params, router, path],
  );
}

/** Value read straight from the URL (for state that changes through navigation, e.g. the selected product). */
export function useUrlValue(key: string, fallback = ""): string {
  return useSearchParams().get(key) ?? fallback;
}
