// Sprint 179A — the Work Plan's own client.
//
// `GET /api/tickets/work-plan/` is a COMPOSITE, not a model list: two
// sources (ticket slots and extra work), a placement decision per card,
// three bounded lists and a count block. It therefore has no paginated
// envelope and no `results` key, and it deliberately does not live in
// `admin.ts` beside `getMySlots` — that helper still exists, still
// returns slot rows, and is still what other callers speak.
//
// Every number on this page comes from here. The chips used to be
// counted in the browser over whatever had been fetched, so a chip could
// report a figure that described one page and looked authoritative doing
// it. `counts` is `COUNT(*)` over the scoped queryset on the server and
// stays right even when `entries` hits its bound — which the response
// says out loud through `truncated`.
import { api } from "./client";

/** Why a card is in the week it is in. §12B: a card shown outside its
 *  planned week must say why. */
export type WorkPlanPlacement =
  | "PLANNED"
  | "STARTED_EARLY"
  | "STARTED"
  | "OVERDUE";

/** The normalised state, shared by both sources. NOT `slot_status` and
 *  NOT the extra-work status — those two enums agree about almost
 *  nothing; the server maps each onto these four once. */
export type WorkPlanState = "OPEN" | "IN_PROGRESS" | "DONE" | "BLOCKED";

export type WorkPlanKind = "TICKET_SLOT" | "EXTRA_WORK";

/** One card. Both kinds answer with the SAME shape — extra work has no
 *  dated slot, so its three time fields are null rather than absent. */
export interface WorkPlanEntry {
  kind: WorkPlanKind;
  /** "slot-12" / "ew-7" — unique across both sources, so a merged list
   *  keys on it without inventing an index. */
  key: string;
  source_id: number;
  ticket_id: number | null;
  ticket_no: string | null;
  extra_work_id: number | null;
  title: string;
  /** The source's OWN status string: a slot status or an extra-work
   *  status. Rendered through the existing badges. */
  status: string;
  state: WorkPlanState;
  ticket_status: string | null;
  ticket_type: string | null;
  urgency: string | null;
  customer_name: string | null;
  building_id: number | null;
  building_name: string | null;
  planned_start: string | null;
  planned_end: string | null;
  due_date: string | null;
  scheduled_start_at: string | null;
  scheduled_end_at: string | null;
  time_window_label: string | null;
  assignment_note: string | null;
  completion_note: string | null;
  unable_to_complete_reason: string | null;
  /** The day column this card hangs on, "YYYY-MM-DD". */
  day: string;
  placement: WorkPlanPlacement;
  is_overdue: boolean;
  overdue_days: number | null;
  assignee_names: string[];
  assignee_count: number;
  /** The completion actions belong to the person holding the slot — an
   *  admin reading the team's week is not working it. */
  can_complete: boolean;
}

export interface WorkPlanCounts {
  total: number;
  overdue: number;
  open: number;
  in_progress: number;
  done: number;
  blocked: number;
  /** Every overdue job in scope, any week — the Overdue button's own
   *  question, which is not the week chip's. */
  overdue_all: number;
  upcoming: number;
  undated: number;
}

export interface WorkPlanWeek {
  iso_year: number;
  iso_week: number;
  label: string;
  start: string;
  end: string;
  is_current: boolean;
}

export interface WorkPlanResponse {
  week: WorkPlanWeek;
  today: string;
  scope: "own" | "company";
  counts: WorkPlanCounts;
  entries: WorkPlanEntry[];
  overdue_entries: WorkPlanEntry[];
  upcoming_entries: WorkPlanEntry[];
  limits: {
    entries: number;
    overdue_entries: number;
    upcoming_entries: number;
  };
  truncated: {
    entries: boolean;
    overdue_entries: boolean;
    upcoming_entries: boolean;
  };
}

/**
 * One week of the Work Plan.
 *
 * `teamWeek` asks for every job the actor may see rather than only
 * their own. The server admits it for a provider-management role and
 * ignores it otherwise, so passing it is never a way to widen what a
 * STAFF user gets — the response echoes back the `scope` it actually
 * applied.
 */
export async function getWorkPlan(
  week: string,
  teamWeek = false,
): Promise<WorkPlanResponse> {
  const response = await api.get<WorkPlanResponse>("/tickets/work-plan/", {
    params: {
      week,
      ...(teamWeek ? { scope: "company" } : {}),
    },
  });
  return response.data;
}
