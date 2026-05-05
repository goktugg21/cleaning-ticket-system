import { api } from "./client";
import type {
  AgeBucketsResponse,
  ManagerThroughputResponse,
  StatusDistributionResponse,
  TicketsOverTimeResponse,
} from "./reports.types";

export interface ReportFilters {
  from?: string;
  to?: string;
  company?: number;
  building?: number;
}

function paramsFor(filters: ReportFilters): Record<string, string> {
  const out: Record<string, string> = {};
  if (filters.from) out.from = filters.from;
  if (filters.to) out.to = filters.to;
  if (filters.company !== undefined) out.company = String(filters.company);
  if (filters.building !== undefined) out.building = String(filters.building);
  return out;
}

export async function fetchStatusDistribution(
  filters: ReportFilters,
): Promise<StatusDistributionResponse> {
  const { data } = await api.get<StatusDistributionResponse>(
    "/reports/status-distribution/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchTicketsOverTime(
  filters: ReportFilters,
): Promise<TicketsOverTimeResponse> {
  const { data } = await api.get<TicketsOverTimeResponse>(
    "/reports/tickets-over-time/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchManagerThroughput(
  filters: ReportFilters,
): Promise<ManagerThroughputResponse> {
  const { data } = await api.get<ManagerThroughputResponse>(
    "/reports/manager-throughput/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchAgeBuckets(
  filters: ReportFilters,
): Promise<AgeBucketsResponse> {
  const { data } = await api.get<AgeBucketsResponse>(
    "/reports/age-buckets/",
    { params: paramsFor(filters) },
  );
  return data;
}
