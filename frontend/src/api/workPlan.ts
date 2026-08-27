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
  | "OVERDUE"
  /** W-PLANTRUTH §1b — planned for a day that has passed, still not
   *  done, so the DISPLAY rolled it onto today's column. The planned
   *  date itself never moved: `rolled_from` is it. */
  | "ROLLED";

/** The normalised state, shared by both sources. NOT `slot_status` and
 *  NOT the extra-work status — those two enums agree about almost
 *  nothing; the server maps each onto these four once. */
export type WorkPlanState = "OPEN" | "IN_PROGRESS" | "DONE" | "BLOCKED";

/**
 * W-VIEWER — the three shapes a card can be, and WHO gets which.
 *
 *   TICKET       the JOB. One card per ticket, on the ticket's own
 *                scheduled date, whatever its people's days say. What a
 *                provider-management caller reading the company's week
 *                gets. `status` is a TICKET status.
 *   TICKET_SLOT  one person's dated piece of a ticket, on the day THEY
 *                were given, with THEIR parts. What a caller reading
 *                their own week gets, and the only ticket shape a STAFF
 *                caller can get. `status` is a SLOT status.
 *   EXTRA_WORK   an extra-work request nobody has spawned a ticket for
 *                yet. `status` is an extra-work status.
 *
 * The badge is picked off this field, which is why the first two are
 * separate kinds rather than one kind with a flag: they carry different
 * status vocabularies.
 */
export type WorkPlanKind = "TICKET" | "TICKET_SLOT" | "EXTRA_WORK";

/** One card. Both kinds answer with the SAME shape — extra work has no
 *  dated slot, so its three time fields are null rather than absent. */
/** W-LATE §3b — where a part stands against its own window. Mirrors
 *  `tickets/lateness.part_state`; `NONE` is "no window". */
export type WorkPlanPartState = "NONE" | "OPEN" | "LAST_DAY" | "MISSED" | "DONE";

/** One named part of a ticket, as the Work Plan shows it, with its own
 *  window (W-LATE §3a) and the STATE the server decided for it. */
export interface WorkPlanPart {
  id: number;
  title: string;
  planned_start: string | null;
  planned_end: string | null;
  time_window_label: string;
  is_done: boolean;
  state: WorkPlanPartState;
}

/** W-LATE — one rung of the ladder. `1` planned date passed, `2`
 *  deadline passed, `3` never done (thirty days past the anchor with no
 *  hour booked). Mirrors `tickets/lateness.py`, the ONE owner. */
export type LateLevel = 1 | 2 | 3;

/** W-LATE phase 2 — one escalation step that has fired for this job:
 *  which rung spoke, when, and to whom (display names resolved at
 *  render time from the recipients the step actually reached). */
export interface WorkPlanEscalationStep {
  /** The STORED step values. `L3_QUARANTINE` keeps its spelling because
   *  it is a stored choice (W-PLANTRUTH §1c renamed the rung, not the
   *  data); everything the reader sees says "never done". */
  step: "L2_MANAGERS" | "L2_ESCALATED" | "L3_QUARANTINE";
  notified_at: string;
  names: string[];
}

/** W-LATE §1b — the facts the ladder produced for one JOB. Always
 *  present on every entry; `level: null` means "not late". The server
 *  is the owner of the rule (`tickets/lateness.py`); the client only
 *  reads this through `components/workplan/lateness.ts`. */
export interface WorkPlanLateness {
  level: LateLevel | null;
  /** The last planned day — the window end — that L1 compares against. */
  planned_date: string | null;
  planned_days_late: number | null;
  deadline: string | null;
  deadline_days_late: number | null;
  /** What L3 counts from: the deadline, else the planned date. */
  anchor: string | null;
  anchor_days: number | null;
  /** Days late against the plan, else against the deadline. */
  days_late: number | null;
  /** Decimal as a string, the way every amount travels. */
  hours_booked: string;
  /** W-LATE §2 — the steps the ladder has spoken for this job; empty
   *  when nothing has fired. */
  escalation_steps: WorkPlanEscalationStep[];
}

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
  /** W-PLANTRUTH §1b — on a ROLLED card only: the day it was PLANNED
   *  for (the date that placed it, and the date its badge prints) and
   *  how many whole days past that today is. Null on every other card. */
  rolled_from: string | null;
  rolled_days: number | null;
  is_overdue: boolean;
  overdue_days: number | null;
  /** W-VIEWER §5 — this reader's standing against the promise, SIGNED
   *  and whole: `3` is three days left, `0` is today, `-2` is two days
   *  past. Null when nothing was promised. "Late or not" says it one day
   *  too late to act on; this is what lets somebody read where they
   *  stand without opening the ticket. */
  due_in_days: number | null;
  /** W-VIEWER §5 — nothing is being asked of THIS reader right now, so
   *  the card renders calm rather than urgent. For a worker: their slot
   *  is off their hands and every part of theirs is done. For a manager:
   *  the job is not in a status the provider side is holding — the
   *  ruling's own example is work sent to the customer and waiting on
   *  their answer, which they may still withdraw. Visible either way;
   *  just not shouting. */
  viewer_settled: boolean;
  assignee_names: string[];
  assignee_count: number;
  /** W-N1 §3 — the parts of this ticket THIS entry's person holds.
   *  Always an array, never null, and empty for extra work, which has
   *  no parts. Scope is the server's: a STAFF viewer's rows carry their
   *  own parts, a manager's carry everyone's. */
  parts: WorkPlanPart[];
  /** W-LATE §1b — the rung this JOB stands on. */
  lateness: WorkPlanLateness;
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
  /** W-LATE §1a — late JOBS (deduped), any week, the strip's own count. */
  late: number;
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
  /** Sprint 181 §8 — work that belongs to no week: a ticket slot with
   *  no `scheduled_start_at`, or an extra work with no planned start.
   *  `counts.undated` has always been here; the ROWS had not, so the
   *  page could only say how much work it was declining to show. */
  undated_entries: WorkPlanEntry[];
  /** W-LATE §1a — the late strip: one row per late JOB, sorted by the
   *  ladder (orange leftmost, bordeaux rightmost), each carrying the
   *  same `lateness` the week cards carry. */
  late_entries: WorkPlanEntry[];
  limits: {
    entries: number;
    overdue_entries: number;
    upcoming_entries: number;
    undated_entries: number;
    late_entries: number;
  };
  truncated: {
    entries: boolean;
    overdue_entries: boolean;
    upcoming_entries: boolean;
    undated_entries: boolean;
    late_entries: boolean;
  };
}

/**
 * Sprint 182 §3 — put an extra work on a day.
 *
 * The undated lane offered "Plan for today" on a ticket row and only
 * "Open extra work" on an extra-work row, because an extra work had no
 * provider-owned date to write to: `preferred_date` is the CUSTOMER's
 * wish (Sprint 176 §3) and the provider must not overwrite it to make a
 * planning board work.
 *
 * Sprint 182 gives it one — `provider_planned_date`, Agent A's field —
 * and this writes it through the EXISTING bulk-dates endpoint with a
 * batch of exactly one, rather than asking for a new endpoint. That one
 * already owns the rules this write needs: provider-only, scoped
 * resolution, and an out-of-scope id answered identically to a
 * non-existent one (H-1).
 *
 * **This call needs Agent A's branch merged to succeed**, and one more
 * line inside it: the bulk-dates input serializer has to accept
 * `provider_planned_date` the way it already accepts `deadline` and
 * `planned_end_date`. That file is A's, so this branch does not touch
 * it. Until it lands the server answers 400 and the button shows the
 * message — it does not pretend to have worked.
 */
export async function planExtraWorkForDate(
  extraWorkId: number,
  isoDate: string,
): Promise<void> {
  await api.post("/extra-work/bulk-dates/", {
    requests: [extraWorkId],
    provider_planned_date: isoDate,
  });
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
