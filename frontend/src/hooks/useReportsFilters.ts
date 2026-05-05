import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

export type RangePreset = "last_7" | "last_30" | "last_90" | "custom";

export interface ReportFiltersState {
  from: string;
  to: string;
  company?: number;
  building?: number;
  preset: RangePreset;
}

export interface UseReportsFiltersResult {
  filters: ReportFiltersState;
  setFilter: <K extends "from" | "to" | "company" | "building">(
    key: K,
    value: ReportFiltersState[K] | undefined,
  ) => void;
  setRangePreset: (preset: "last_7" | "last_30" | "last_90") => void;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function parseDateOrNull(raw: string | null): string | null {
  if (!raw || !ISO_DATE.test(raw)) return null;
  // sanity: round-trip through Date to reject impossible dates like 2026-02-30
  const d = new Date(`${raw}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  if (d.toISOString().slice(0, 10) !== raw) return null;
  return raw;
}

function parsePosIntOrNull(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) return undefined;
  return n;
}

function presetFor(from: string, to: string): RangePreset {
  if (to !== todayIso()) return "custom";
  const days = (new Date(`${to}T00:00:00Z`).getTime() -
    new Date(`${from}T00:00:00Z`).getTime()) / 86400000;
  if (days === 6) return "last_7";
  if (days === 29) return "last_30";
  if (days === 89) return "last_90";
  return "custom";
}

export function useReportsFilters(): UseReportsFiltersResult {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<ReportFiltersState>(() => {
    const today = todayIso();
    const defaultFrom = shiftDays(today, -29);
    const from = parseDateOrNull(searchParams.get("from")) ?? defaultFrom;
    const to = parseDateOrNull(searchParams.get("to")) ?? today;
    const company = parsePosIntOrNull(searchParams.get("company"));
    const building = parsePosIntOrNull(searchParams.get("building"));
    return { from, to, company, building, preset: presetFor(from, to) };
  }, [searchParams]);

  const writeParams = useCallback(
    (mutator: (next: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams);
      mutator(next);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const setFilter = useCallback<UseReportsFiltersResult["setFilter"]>(
    (key, value) => {
      writeParams((next) => {
        if (value === undefined || value === null || value === "") {
          next.delete(key);
        } else {
          next.set(key, String(value));
        }
        // Changing the company invalidates any building selection.
        if (key === "company") {
          next.delete("building");
        }
      });
    },
    [writeParams],
  );

  const setRangePreset = useCallback<UseReportsFiltersResult["setRangePreset"]>(
    (preset) => {
      const today = todayIso();
      const span = preset === "last_7" ? 7 : preset === "last_30" ? 30 : 90;
      const from = shiftDays(today, -(span - 1));
      writeParams((next) => {
        next.set("from", from);
        next.set("to", today);
      });
    },
    [writeParams],
  );

  return { filters, setFilter, setRangePreset };
}
