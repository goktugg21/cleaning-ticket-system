import { api } from "./client";
import type { PaginatedResponse } from "./types";

/**
 * W4-R — the per-person hourly rate.
 *
 * `GET/POST /api/reports/employee-hourly-rates/` and the detail route
 * over one row. **SUPER_ADMIN and COMPANY_ADMIN only** — the endpoint
 * 403s a BUILDING_MANAGER, a STAFF member (including for their own
 * rate) and every customer-side role. That is enforced server-side; the
 * tab that renders this is additionally hidden, but the hiding is a
 * courtesy and the 403 is the permission.
 *
 * ## Why a rate is DATED
 *
 * One row per (employee, company, `valid_from`), open-ended and
 * superseded rather than edited. The rate that costs an hour is the row
 * in force ON THE DAY OF THAT HOUR, so a raise in March leaves January's
 * cost figures exactly where they were. Recording a raise means adding a
 * row with a new start date — never editing the standing one, which is
 * what the UI's "New rate from…" form does.
 *
 * Editing a row IS possible and means "this row was typed wrong",
 * which re-prices the period it covers. Deliberate, and audited.
 */
export interface EmployeeHourlyRate {
  id: number;
  company: number;
  company_name: string;
  employee: number;
  employee_name: string;
  employee_email: string;
  /** Euros per hour, a fixed 2dp STRING — never a float. */
  hourly_rate: string;
  /** ISO date. The FIRST day this rate is in force. */
  valid_from: string;
  note: string;
  created_by: number;
  created_by_name: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeHourlyRateWritePayload {
  company: number;
  employee: number;
  hourly_rate: string;
  valid_from: string;
  note?: string;
}

export interface EmployeeHourlyRateListParams {
  company?: number;
  employee?: number;
}

/**
 * Every rate row in scope, paged EXHAUSTIVELY.
 *
 * The Sprint 120/135 pattern: the caller has no pagination UI, so it
 * loops rather than the endpoint loosening its `pagination_class` —
 * which is a contract with every other caller, present and future. A
 * company with two hundred employees and five years of rate history is
 * a real list, and the screen that reads this bounds what it DRAWS
 * (`BoundedList`) rather than what it fetches.
 */
export async function listEmployeeHourlyRates(
  params: EmployeeHourlyRateListParams = {},
): Promise<EmployeeHourlyRate[]> {
  const all: EmployeeHourlyRate[] = [];
  let page = 1;
  for (let i = 0; i < 100; i++) {
    const response = await api.get<PaginatedResponse<EmployeeHourlyRate>>(
      "/reports/employee-hourly-rates/",
      {
        params: {
          ...(params.company === undefined
            ? {}
            : { company: String(params.company) }),
          ...(params.employee === undefined
            ? {}
            : { employee: String(params.employee) }),
          page_size: 200,
          page,
        },
      },
    );
    all.push(...response.data.results);
    if (!response.data.next) break;
    page += 1;
  }
  return all;
}

export async function createEmployeeHourlyRate(
  payload: EmployeeHourlyRateWritePayload,
): Promise<EmployeeHourlyRate> {
  const response = await api.post<EmployeeHourlyRate>(
    "/reports/employee-hourly-rates/",
    payload,
  );
  return response.data;
}

export async function updateEmployeeHourlyRate(
  id: number,
  payload: Partial<EmployeeHourlyRateWritePayload>,
): Promise<EmployeeHourlyRate> {
  const response = await api.patch<EmployeeHourlyRate>(
    `/reports/employee-hourly-rates/${id}/`,
    payload,
  );
  return response.data;
}

export async function deleteEmployeeHourlyRate(id: number): Promise<void> {
  await api.delete(`/reports/employee-hourly-rates/${id}/`);
}
