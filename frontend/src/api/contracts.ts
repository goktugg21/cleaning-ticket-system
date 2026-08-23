// Sprint 160 — client for the contracts module (`backend/contracts/`).
//
// Its own file rather than an extension of `admin.ts`, mirroring
// `timesheets.ts`: the module is independent on the backend and the
// frontend mirrors that.

import { api } from "./client";
import type { PaginatedResponse } from "./types";
import type {
  Contract,
  ContractFilters,
  ContractForecast,
  ContractLine,
  ContractLineWritePayload,
  ContractOptions,
  ContractPlanning,
  ContractRevision,
  ContractRevisionWritePayload,
  ContractStats,
  ContractType,
  ContractWritePayload,
  ExtraWorkRegister,
} from "./contracts.types";

/**
 * Drop empty / undefined params so an unset filter is ABSENT from the
 * query string rather than sent as `""`. The backend's
 * `parse_int_param` treats "" as absent too, so this is belt and
 * braces — but it also keeps the URLs readable in the network tab,
 * which is where a filter bug is diagnosed. Same helper shape as
 * `timesheets.ts`; copied rather than shared for the module-
 * independence reason in that file's header.
 */
function cleanParams<T extends object>(params: T): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    out[key] = String(value);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Contracts
// ---------------------------------------------------------------------------

/**
 * The contract list is PAGINATED server-side (`StandardResultsSet`),
 * and this returns the envelope rather than a flat array on purpose:
 * contracts are a growing server collection and the page has real
 * prev/next UI. The pickers that need everything call `getContractOptions`
 * instead — the Sprint 134/135 lesson, that loosening a shared list's
 * pagination to feed a picker breaks every other caller of it.
 */
export async function listContracts(
  filters: ContractFilters = {},
): Promise<PaginatedResponse<Contract>> {
  const { data } = await api.get<PaginatedResponse<Contract>>("/contracts/", {
    params: cleanParams(filters),
  });
  return data;
}

export async function getContract(id: number): Promise<Contract> {
  const { data } = await api.get<Contract>(`/contracts/${id}/`);
  return data;
}

export async function createContract(
  payload: ContractWritePayload,
): Promise<Contract> {
  const { data } = await api.post<Contract>("/contracts/", payload);
  return data;
}

export async function updateContract(
  id: number,
  payload: Partial<ContractWritePayload>,
): Promise<Contract> {
  const { data } = await api.patch<Contract>(`/contracts/${id}/`, payload);
  return data;
}

export async function deleteContract(id: number): Promise<void> {
  await api.delete(`/contracts/${id}/`);
}

/**
 * The stat tiles, computed over the SAME filters the list uses — pass
 * the filters through so the tiles describe what the table is showing
 * rather than the whole tenant.
 */
export async function getContractStats(
  filters: ContractFilters = {},
): Promise<ContractStats> {
  const { data } = await api.get<ContractStats>("/contracts/stats/", {
    params: cleanParams(filters),
  });
  return data;
}

/**
 * Everything the contract form's pickers need, in one call, already
 * scoped. What this returns is exactly what the write path accepts —
 * both read the same scoped querysets server-side — so a picker can
 * never offer an option that would be rejected.
 */
export async function getContractOptions(
  company?: number | "",
): Promise<ContractOptions> {
  const { data } = await api.get<ContractOptions>("/contracts/options/", {
    params: cleanParams({ company }),
  });
  return data;
}

// ---------------------------------------------------------------------------
// Revisions and their lines
// ---------------------------------------------------------------------------

export async function listContractRevisions(
  contractId: number,
): Promise<ContractRevision[]> {
  const { data } = await api.get<ContractRevision[]>(
    `/contracts/${contractId}/revisions/`,
  );
  return data;
}

export async function createContractRevision(
  contractId: number,
  payload: ContractRevisionWritePayload,
): Promise<ContractRevision> {
  const { data } = await api.post<ContractRevision>(
    `/contracts/${contractId}/revisions/`,
    payload,
  );
  return data;
}

export async function updateContractRevision(
  revisionId: number,
  payload: Partial<ContractRevisionWritePayload>,
): Promise<ContractRevision> {
  const { data } = await api.patch<ContractRevision>(
    `/contracts/revisions/${revisionId}/`,
    payload,
  );
  return data;
}

export async function deleteContractRevision(
  revisionId: number,
): Promise<void> {
  await api.delete(`/contracts/revisions/${revisionId}/`);
}

export async function createContractLine(
  revisionId: number,
  payload: ContractLineWritePayload,
): Promise<ContractLine> {
  const { data } = await api.post<ContractLine>(
    `/contracts/revisions/${revisionId}/lines/`,
    payload,
  );
  return data;
}

export async function updateContractLine(
  lineId: number,
  payload: Partial<ContractLineWritePayload>,
): Promise<ContractLine> {
  const { data } = await api.patch<ContractLine>(
    `/contracts/lines/${lineId}/`,
    payload,
  );
  return data;
}

export async function deleteContractLine(lineId: number): Promise<void> {
  await api.delete(`/contracts/lines/${lineId}/`);
}

// ---------------------------------------------------------------------------
// The Invoice Preview
// ---------------------------------------------------------------------------

/**
 * A READ. There is deliberately no `generateInvoices` counterpart:
 * turning a due forecast row into a real `Invoice` is Sprint 158's, and
 * the absence of a function here is part of what keeps that boundary.
 */
export async function getContractForecast(
  contractId: number,
  year: number,
): Promise<ContractForecast> {
  const { data } = await api.get<ContractForecast>(
    `/contracts/${contractId}/forecast/`,
    { params: { year: String(year) } },
  );
  return data;
}

// ---------------------------------------------------------------------------
// The contract-type catalog
// ---------------------------------------------------------------------------

export async function listContractTypes(
  company?: number | "",
): Promise<ContractType[]> {
  const { data } = await api.get<ContractType[]>("/contracts/types/", {
    params: cleanParams({ company }),
  });
  return data;
}

export async function createContractType(payload: {
  name: string;
  company?: number;
  sort_order?: number;
}): Promise<ContractType> {
  const { data } = await api.post<ContractType>("/contracts/types/", payload);
  return data;
}

export async function updateContractType(
  id: number,
  payload: { name?: string; is_active?: boolean; sort_order?: number },
): Promise<ContractType> {
  const { data } = await api.patch<ContractType>(
    `/contracts/types/${id}/`,
    payload,
  );
  return data;
}

export async function deleteContractType(id: number): Promise<void> {
  await api.delete(`/contracts/types/${id}/`);
}

// ---------------------------------------------------------------------------
// W16 — the extra works register
// ---------------------------------------------------------------------------

/**
 * The customer's register of chargeable work, created on first ask.
 *
 * Keyed on the CUSTOMER, not on a contract id — the caller has a
 * customer in hand and must not have to know whether a register has
 * been made yet. Same shape as the reference system's
 * `/contracts/extra-works/{customerId}`.
 *
 * The GET syncs before it answers, so what comes back is current. It
 * is idempotent, so calling it twice costs a query and changes
 * nothing.
 */
export async function getExtraWorkRegister(
  customerId: number,
): Promise<ExtraWorkRegister> {
  const { data } = await api.get<ExtraWorkRegister>(
    `/contracts/extra-works/${customerId}/`,
  );
  return data;
}

/** Rebuild the register and report what moved, so the page can say
 *  "3 jobs added" rather than "done". */
export async function syncExtraWorkRegister(
  customerId: number,
): Promise<ExtraWorkRegister> {
  const { data } = await api.post<ExtraWorkRegister>(
    `/contracts/extra-works/${customerId}/sync/`,
    {},
  );
  return data;
}

// W23 — the year×week planning grid for one contract.
export async function getContractPlanning(
  contractId: number,
  year: number,
): Promise<ContractPlanning> {
  const response = await api.get<ContractPlanning>(
    `/contracts/${contractId}/planning/`,
    { params: { year } },
  );
  return response.data;
}
