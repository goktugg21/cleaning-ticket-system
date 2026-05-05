import { useCallback, useEffect, useRef, useState } from "react";
import { getApiError } from "../api/client";
import type { ReportFilters } from "../api/reports";

export interface UseReportConfig<TResponse> {
  fetcher: (filters: ReportFilters) => Promise<TResponse>;
  filters: ReportFilters;
  refreshKey: number;
}

export interface UseReportResult<TResponse> {
  data: TResponse | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

function filtersKey(filters: ReportFilters): string {
  return [
    filters.from ?? "",
    filters.to ?? "",
    filters.company ?? "",
    filters.building ?? "",
  ].join("|");
}

export function useReport<TResponse>(
  config: UseReportConfig<TResponse>,
): UseReportResult<TResponse> {
  const [data, setData] = useState<TResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Local retry counter so chart-level retry triggers a refetch without
  // rolling the page-level refresh key.
  const [retryKey, setRetryKey] = useState<number>(0);

  // Hold the latest config in a ref so the load effect's deps shrink to the
  // primitive filtersKey, refreshKey, and retryKey. Without this the inline
  // config object recreates `fetcher` each render and the effect would cancel
  // its own fetch in flight (same trap as useEntityForm).
  const configRef = useRef(config);
  configRef.current = config;

  const fKey = filtersKey(config.filters);
  const rKey = config.refreshKey;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    configRef.current
      .fetcher(configRef.current.filters)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fKey, rKey, retryKey]);

  const retry = useCallback(() => {
    setRetryKey((n) => n + 1);
  }, []);

  return { data, loading, error, retry };
}
