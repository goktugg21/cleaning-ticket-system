import { api } from "./client";
import type {
  AgeBucketsResponse,
  ManagerThroughputResponse,
  SLABreachRateOverTimeResponse,
  SLADistributionResponse,
  StatusDistributionResponse,
  TicketsByBuildingResponse,
  TicketsByCustomerResponse,
  TicketsByTypeResponse,
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

export async function fetchSLADistribution(
  filters: ReportFilters,
): Promise<SLADistributionResponse> {
  const { data } = await api.get<SLADistributionResponse>(
    "/reports/sla-distribution/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchSLABreachRateOverTime(
  filters: ReportFilters,
): Promise<SLABreachRateOverTimeResponse> {
  const { data } = await api.get<SLABreachRateOverTimeResponse>(
    "/reports/sla-breach-rate-over-time/",
    { params: paramsFor(filters) },
  );
  return data;
}

// ---- Sprint 5 dimensions -------------------------------------------------

export async function fetchTicketsByType(
  filters: ReportFilters,
): Promise<TicketsByTypeResponse> {
  const { data } = await api.get<TicketsByTypeResponse>(
    "/reports/tickets-by-type/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchTicketsByCustomer(
  filters: ReportFilters,
): Promise<TicketsByCustomerResponse> {
  const { data } = await api.get<TicketsByCustomerResponse>(
    "/reports/tickets-by-customer/",
    { params: paramsFor(filters) },
  );
  return data;
}

export async function fetchTicketsByBuilding(
  filters: ReportFilters,
): Promise<TicketsByBuildingResponse> {
  const { data } = await api.get<TicketsByBuildingResponse>(
    "/reports/tickets-by-building/",
    { params: paramsFor(filters) },
  );
  return data;
}

// Export download helpers. Each returns the URL the browser should
// hit; the chart card's button just sets `window.location.href` so
// the existing axios auth header is bypassed and the browser receives
// the file via a normal navigation. (Axios + blob downloads work too
// but require manual JWT-attaching which would duplicate api/client.ts.)
//
// Important: because these go through window.location, the JWT must
// be in a header that the browser will send — which it isn't for
// Authorization: Bearer. So we use api.get with responseType=blob and
// trigger a programmatic download instead. See helper below.
export type DimensionExportFormat = "csv" | "pdf";

const EXPORT_PATHS = {
  type: "/reports/tickets-by-type",
  customer: "/reports/tickets-by-customer",
  building: "/reports/tickets-by-building",
} as const;

export async function downloadDimensionExport(
  dimension: keyof typeof EXPORT_PATHS,
  format: DimensionExportFormat,
  filters: ReportFilters,
): Promise<void> {
  const url = `${EXPORT_PATHS[dimension]}/export.${format}`;
  const response = await api.get(url, {
    params: paramsFor(filters),
    responseType: "blob",
  });
  const contentDisposition = response.headers["content-disposition"] ?? "";
  const match = /filename="?([^"]+)"?/i.exec(contentDisposition);
  const filename = match ? match[1] : `${dimension}-export.${format}`;
  const blobUrl = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(blobUrl);
}
