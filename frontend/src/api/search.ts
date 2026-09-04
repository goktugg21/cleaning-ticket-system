// P-6 V4 — global search. ONE read-only endpoint, viewer-scoped by the
// backend's existing scope helpers, five groups of at most five rows;
// `truncated` says when a group was cut. Nothing fuzzy: the server
// matches `icontains` on number/title (tickets, meerwerk) and on name
// (customers, buildings, people).
import { api } from "./client";

export interface SearchTicketHit {
  id: number;
  ticket_no: string | null;
  title: string;
  status: string;
  display_phase: string | null;
  customer_name: string | null;
  building_name: string | null;
}

export interface SearchExtraWorkHit {
  id: number;
  title: string;
  status: string;
  display_phase: string | null;
  customer_name: string | null;
  building_name: string | null;
}

export interface SearchCustomerHit {
  id: number;
  name: string;
  company_name: string | null;
}

export interface SearchBuildingHit {
  id: number;
  name: string;
  city: string | null;
  company_name: string | null;
}

export interface SearchPersonHit {
  id: number;
  full_name: string;
  email: string;
  role: string;
}

export type SearchGroupKey =
  | "tickets"
  | "extra_work"
  | "customers"
  | "buildings"
  | "people";

export interface GlobalSearchResponse {
  q: string;
  limit: number;
  groups: {
    tickets: SearchTicketHit[];
    extra_work: SearchExtraWorkHit[];
    customers: SearchCustomerHit[];
    buildings: SearchBuildingHit[];
    people: SearchPersonHit[];
  };
  truncated: Record<SearchGroupKey, boolean>;
}

/** The order the groups are shown in — the work first, then the places
 *  and the people it belongs to. Exported so the box and any later
 *  consumer iterate ONE constant (CLAUDE.md: never a second local
 *  copy of a render order). */
export const SEARCH_GROUP_ORDER: readonly SearchGroupKey[] = [
  "tickets",
  "extra_work",
  "customers",
  "buildings",
  "people",
] as const;

export async function globalSearch(q: string): Promise<GlobalSearchResponse> {
  const response = await api.get<GlobalSearchResponse>("/search/", {
    params: { q },
  });
  return response.data;
}
