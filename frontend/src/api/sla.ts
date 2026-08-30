// Sprint W4-Q §2 — the per-company SLA warning thresholds
// (backend/sla/views_thresholds.py, mounted at /api/sla/).
//
// SUPER_ADMIN / COMPANY_ADMIN only, server-side. A COMPANY_ADMIN's list
// comes back already narrowed to the companies they are a member of, so
// the screen never has to filter a tenant boundary itself — it renders
// what it is given.
import { api } from "./client";
import type {
  SlaCompanyThresholds,
  SlaThresholdListResponse,
} from "./types";

/** The write body. A field set to null CLEARS that override and returns
 *  the knob to the platform default; a field left out is untouched. 0 is
 *  a legal value and is NOT a way to clear anything. */
/** Numbers (null clears an override) and — P-5 S8 — the choices,
 *  flattened to their column names (`manager_review_also_notify`,
 *  `not_started_extra_email`, `count_calendar_days`, ...). */
export type SlaThresholdPatch = Record<
  string,
  number | null | boolean | string | string[]
>;

export async function listSlaWarningThresholds(): Promise<SlaThresholdListResponse> {
  const response = await api.get<SlaThresholdListResponse>(
    "/sla/warning-thresholds/",
  );
  return response.data;
}

export async function saveSlaWarningThresholds(
  companyId: number,
  patch: SlaThresholdPatch,
): Promise<SlaCompanyThresholds> {
  const response = await api.put<SlaCompanyThresholds>(
    `/sla/warning-thresholds/${companyId}/`,
    patch,
  );
  return response.data;
}

/** Drop every override for one company — the "back to the platform
 *  defaults" action. Returns the company's state after the reset, which
 *  is the defaults. */
export async function resetSlaWarningThresholds(
  companyId: number,
): Promise<SlaCompanyThresholds> {
  const response = await api.delete<SlaCompanyThresholds>(
    `/sla/warning-thresholds/${companyId}/`,
  );
  return response.data;
}
