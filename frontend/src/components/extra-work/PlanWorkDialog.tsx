/**
 * W3-F — the plan modal. The screen for the layer W2-D built.
 *
 * W2-D shipped `POST /api/extra-work/<id>/plan/` complete and tested,
 * and nothing anywhere called it. From the owner's chair a feature with
 * no screen does not exist, so this is the screen.
 *
 * THE FOUR THINGS THIS DIALOG HAS TO GET RIGHT
 * --------------------------------------------
 * 1. **The dates are OURS, and they are labelled as ours.** The customer
 *    asked for a date and gave us a deadline; those live elsewhere on the
 *    page, they are written by a different endpoint, and this one cannot
 *    touch them. The whole reason the backend stores two pairs is that a
 *    provider's commitment is not the customer's request, so the two
 *    fields here say "we commit to" and the customer's dates are shown
 *    beside them, read-only, for comparison. An operator who cannot see
 *    what was asked for cannot judge what to commit to.
 *
 * 2. **Hours are distributed across the ASSIGNED crew, and only them.**
 *    The backend refuses hours for anybody not currently assigned, and it
 *    refuses them with the same body it uses for an id that does not
 *    exist, so a client that guessed would get an unexplainable 400. The
 *    assignment list is therefore read FIRST and the rows are built from
 *    it. With nobody assigned there is nothing to distribute, and the
 *    dialog says so and points at the fix rather than rendering an empty
 *    table.
 *
 * 3. **Overrun WARNS. It never blocks.** The warning is live, it is
 *    unmissable, and the submit button stays enabled behind it. This is
 *    not a UX preference: in the reference system the hard cap exists as
 *    a complete function, `validateTotalHours()`, it is never called, and
 *    the model still carries the comment "// Hours validation removed per
 *    user request". Somebody built the block and the business had it
 *    removed. Do not add `disabled={overrun}` to the submit button.
 *
 * 4. **Absence means "leave it alone".** The payload is read by KEY
 *    PRESENCE server-side, so a field this dialog did not collect is
 *    OMITTED. The two switches are the sharp case: they are only sent
 *    when the operator actually touched them, because sending `false`
 *    for a switch nobody looked at is how the reference system ended up
 *    with 0 of 78 records carrying either flag.
 *
 * The button says PLAN AND START because that is what the endpoint does
 * — planning and starting are one action, the way the reference system's
 * "Start Work" button is. Calling it "Save" would describe half of it.
 *
 * NO FIGURE IN HERE IS MONEY. Budget hours is a planning and control
 * number; `rowAmounts()` is not imported and must never be.
 *
 * A non-native overlay, conditionally mounted — the same split
 * `BulkAssignDialog` documents. CLAUDE.md's render-it-unconditionally
 * rule is about the native `<dialog>` element, which this is not.
 *
 * W7 — THE THREE THINGS THAT WERE WRONG WITH IT ON THE LIVE SITE
 * --------------------------------------------------------------
 * 5. **You could record a night shift and not plan one.**
 *    `ExtraWorkPlannedHours` had no hour type while `TimeEntry` has had
 *    one since it was written, so the hours panel could render
 *    "Noah Bakker | Normale uren | Aug 10 | 3.00" for work already done
 *    and the plan had no vocabulary for it. Each person now carries one
 *    LINE PER KIND OF HOUR, from the same `timesheets.HourType` catalog
 *    the actuals use — never a second catalog, or planned-vs-actual
 *    becomes a join between two vocabularies.
 *
 * 6. **The grid scrolled sideways and took the useful part with it.**
 *    Person and hour type slid out of view first, so an operator typing
 *    into a cell three weeks along could not see whose row it was. Two
 *    rules: the left columns are FROZEN (`position: sticky`, see
 *    `.ew-plan-grid-scroll`), and the days are PAGED a week at a time
 *    rather than laid end to end. Paging is display only — hours on a
 *    day that is off screen stay in state, stay in every total and are
 *    still submitted.
 *
 * 7. **The feature was invisible until you did something else first.**
 *    With no window set there are no day columns, so the grid was one
 *    blank column and a sentence UNDER a scrollbar explained why. The
 *    owner could not find the feature at all. The window now comes
 *    FIRST, before the budget and the grid, and the waiting state lives
 *    INSIDE the grid where the eye already is — with the control that
 *    fixes it. The sentence is gone.
 *
 * W-HOURS5 — "AHMET IS NOT PLANNABLE" (Task 1), AND THE CREW (Task 2)
 * ---------------------------------------------------------------------
 * 8. **The last crew row was below the dialog's own fold.** Measured on
 *    ticket 373 at 1366x768: the dialog is 92vh (707px) over 1047px of
 *    content, and the fourth row — Ahmet's, last because his assignment
 *    was created last — started 18px BELOW the dialog's bottom edge.
 *    At 800px it was 12px visible, and a click at his cell's centre
 *    landed on the dialog's clipped scroll box, not on the input:
 *    "refuses input while others accept it". Nothing froze him; the
 *    row was simply where a click could not reach, and the only hint
 *    that the dialog scrolls was an overlay scrollbar that is invisible
 *    on a touchpad.
 *
 *    Three things fix that, none of them per person. The dialog is now
 *    a fixed HEAD, a scrolling BODY and a fixed FOOT (`.ew-plan-body`,
 *    `.ew-plan-foot` in plan-crew.css): the footer's top edge marks the
 *    fold on every screen, and the actions never scroll away. A cell
 *    that gains focus scrolls itself fully into view (`onFocus` ->
 *    `scrollIntoView`), so a click on a half-visible input, or a Tab
 *    into one, brings the row up instead of leaving it clipped. And the
 *    crew pickers above the grid are one-line chip pickers rather than
 *    checkbox lists, so the grid starts higher on the screen.
 *
 * 9. **The modal owns the whole crew.** People AND responsible managers
 *    are added (multi-select, one Add) and removed (chip x) here, and
 *    the People tab stays the other door to the SAME crew: the page
 *    writes through the ticket's own endpoints and `tickets.crew_sync`
 *    mirrors every change onto the plan's `ExtraWorkAssignment` rows.
 *    Past-day interplay, as ruled: a person added in this session gets
 *    today-and-future cells only — their past cells stay frozen even
 *    when the past is unlocked (they were not there); removing a person
 *    clears only their today-and-future plan, their PAST planned hours
 *    stay as history, and deleting those is possible only by hand —
 *    unlock with a reason, then zero the cells.
 *
 * 10. **Unlock asks first.** "Unlock past days" opens the reason
 *    prompt; nothing unlocks until the reason is given and confirmed,
 *    and the state line then says that the reason lands on the save.
 *    Today never carries a lock glyph: `isPastDay` is strictly before
 *    today.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { dayRange } from "../../lib/planGridDays";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Lock,
  Users,
  X,
} from "lucide-react";

import type {
  ExtraWorkAssignment,
  ExtraWorkPlanPayload,
  ExtraWorkRequestDetail,
} from "../../api/types";
import type { HourType } from "../../api/timesheets.types";
import { listHourTypes } from "../../api/timesheets";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { Toggle } from "../Toggle";
import "./plan-crew.css";
import type { AssignmentCandidate } from "../../api/types";
import { formatDate } from "../../lib/intl";

/** W7 — how many day columns are on screen at once.
 *
 *  THE GRID USED TO SCROLL SIDEWAYS AND TAKE THE USEFUL PART WITH IT.
 *  Person and hour type slid out of view first, so an operator typing
 *  into a cell three weeks along could not see whose row it was. Two
 *  rules fix that and this is the second: the left columns are frozen
 *  (see `.ew-plan-grid-scroll` in index.css), and the day range is
 *  PAGED rather than laid out end to end. Seven is a week, which is the
 *  unit a work window is actually discussed in.
 *
 *  Paging is display only. Hours entered on a day that is not currently
 *  on screen stay in state, stay in every total, and are still
 *  submitted — the same rule that already applied to a day dropped out
 *  of the window entirely. */
const DAY_PAGE_SIZE = 7;

/** One line of the grid: a person, and which kind of hour this line
 *  budgets. `hourType` null is ORDINARY hours — the state every plan
 *  written before W7 is in, and the right answer for an operator who
 *  does not split the day. */
interface CrewLine {
  userId: number;
  hourType: number | null;
}

/** Hours arithmetic, in one place, on strings that arrive as decimals.
 *  Returns a number for comparison only — every value that reaches the
 *  API goes back out as the string the operator typed. */
function toHours(value: string): number {
  const parsed = Number.parseFloat((value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

/** `19-11` — short enough for a column head, unambiguous in a window
 *  that never spans a year. */
function formatDayHeader(day: string): string {
  const [, month, dayOfMonth] = day.split("-");
  return `${dayOfMonth}-${month}`;
}

/** The LOCAL wall date, not toISOString() — the UTC date is yesterday's
 *  or tomorrow's for half the world. */
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
    now.getDate(),
  )}`;
}

/** Whole days from `from` to `to`, both YYYY-MM-DD, in local time. */
function daysBetweenIso(from: string, to: string): number {
  const [fy, fm, fd] = from.split("-").map(Number);
  const [ty, tm, td] = to.split("-").map(Number);
  const a = new Date(fy, fm - 1, fd).getTime();
  const b = new Date(ty, tm - 1, td).getTime();
  return Math.max(0, Math.round((b - a) / 86400000));
}

export function PlanWorkDialog({
  ew,
  assignments,
  assignmentsLoading,
  busy,
  error,
  onCancel,
  onSubmit,
  candidates,
  candidatesLoading,
  assignBusy,
  assignError,
  onAssign,
  managerCandidates = [],
  managerBusy = false,
  onAssignManagers,
  onRemoveManager,
  onRemovePerson,
  removeBusy = false,
  postSpawn = false,
}: {
  ew: ExtraWorkRequestDetail;
  assignments: ExtraWorkAssignment[];
  assignmentsLoading: boolean;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onSubmit: (payload: ExtraWorkPlanPayload) => void;
  /** W-UX1 §2 — people the plan area may still add, from the SERVER's
   *  own eligibility helper. R2: the page hands over only the
   *  not-yet-assigned, so the picker offers exactly what is addable and
   *  the crew above is the default. */
  candidates: AssignmentCandidate[];
  candidatesLoading: boolean;
  assignBusy: boolean;
  assignError: string;
  onAssign: (userIds: number[]) => void;
  /** W-TABS Task 3b — the RESPONSIBLE MANAGER is assigned HERE. The
   *  current managers render from `assignments` (role=MANAGER), so this
   *  component still makes no visibility or eligibility decision of its
   *  own. Empty candidates = no picker. */
  managerCandidates?: AssignmentCandidate[];
  managerBusy?: boolean;
  onAssignManagers?: (userIds: number[]) => void;
  /** Renders an X on each manager chip. Absent = chips without remove. */
  onRemoveManager?: (userId: number) => void;
  /** W-HOURS5 Task 2 — renders an X on each PERSON chip. The page takes
   *  the person off the job through the ticket's own endpoint; the plan
   *  crew follows (`tickets.crew_sync`). Absent = chips without remove. */
  onRemovePerson?: (userId: number) => void;
  removeBusy?: boolean;
  /** W-PLAN Task 2 — mounted from an operational (spawned) ticket page.
   *  SAME dialog, SAME store (the plan lives on the EW pre- and
   *  post-spawn); what changes is the words: the submit says "Save the
   *  plan", because starting is the ticket's business now. The page
   *  passes `start: false` with the payload for the same reason. */
  postSpawn?: boolean;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  const [budget, setBudget] = useState(ew.budget_hours ?? "");
  const [start, setStart] = useState(ew.provider_planned_date ?? "");
  const [end, setEnd] = useState(ew.provider_planned_end_date ?? "");
  const [photoRequired, setPhotoRequired] = useState(
    ew.file_upload_required ?? false,
  );
  const [notesRequired, setNotesRequired] = useState(
    ew.completion_notes_required ?? false,
  );
  // Only sent when the operator moved them — see (4) in the docblock.
  // ONE FLAG PER SWITCH. Both are seeded from the row here, so a shared
  // flag would merely re-write what was already stored — but the bulk
  // dialog has nothing to seed from and there the same shortcut wipes
  // the untouched flag on every selected work. Same shape in both, so
  // the safe one cannot drift into the unsafe one.
  const [photoTouched, setPhotoTouched] = useState(false);
  const [notesTouched, setNotesTouched] = useState(false);

  // W6-H — THE GRID. Keyed `userId|YYYY-MM-DD`, with the empty string
  // as the day for "planned, day not decided". W7 adds the hour type as
  // a third segment, empty for ordinary hours. One flat map rather than
  // a nested one because every read here is a single cell and a flat
  // key makes an accidental whole-row overwrite unspellable.
  const cellKey = (userId: number, day: string, hourType: number | null) =>
    `${userId}|${day}|${hourType ?? ""}`;
  const lineKey = (line: CrewLine) => `${line.userId}|${line.hourType ?? ""}`;

  // Seeded from what is already planned, so reopening the dialog shows
  // the plan rather than a blank grid.
  const seeded = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of ew.planned_hours ?? []) {
      map.set(cellKey(row.user_id, row.date ?? "", row.hour_type), row.hours);
    }
    return map;
  }, [ew.planned_hours]);

  const [hours, setHours] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const [key, value] of seeded) initial[key] = value;
    return initial;
  });

  // W7 — THE HOUR-TYPE CATALOG, read from the work's OWN company.
  //
  // Fetched here rather than passed in: this dialog is the only screen
  // that plans hour types, and the page that mounts it is being rebuilt
  // by another chat this sprint. `is_active` because an archived type is
  // retired for NEW entries — the same contract the actuals have, and
  // the same rule the server enforces on the write.
  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  useEffect(() => {
    let cancelled = false;
    listHourTypes({ company: ew.company, is_active: true })
      .then((rows) => {
        if (!cancelled) setHourTypes(rows);
      })
      .catch(() => {
        // A catalog we could not read leaves the operator with ordinary
        // hours, which is exactly what they had before W7. Never an
        // error banner over a dialog whose main job still works.
        if (!cancelled) setHourTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ew.company]);

  const hourTypeName = (id: number | null) =>
    id === null
      ? t("plan.hour_type_ordinary")
      : (hourTypes.find((h) => h.id === id)?.name ??
        // Seeded from a row whose type has since been archived: name it
        // from the plan rather than printing a bare id.
        (ew.planned_hours ?? []).find((r) => r.hour_type === id)
          ?.hour_type_name ??
        t("plan.hour_type_unknown"));

  // WHICH LINES EXIST. One per person by default (ordinary hours), plus
  // any extra kind of hour already planned or added in this session.
  // Derived once from the plan and then owned locally: adding a line is
  // an edit, and re-deriving it from props would undo the operator's
  // click on the next render.
  const [extraLines, setExtraLines] = useState<CrewLine[]>(() => {
    const seen = new Set<string>();
    const out: CrewLine[] = [];
    for (const row of ew.planned_hours ?? []) {
      if (row.hour_type === null) continue;
      const key = `${row.user_id}|${row.hour_type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ userId: row.user_id, hourType: row.hour_type });
    }
    return out;
  });

  // EVERY LINE IN THE GRID, in render order: each assigned person, then
  // their ordinary-hours line, then their extra kinds in the order the
  // catalog lists them — so two people with the same kinds of hour read
  // the same way down the grid.
  //
  // ONE memo, keyed by person, and it is the single source for the
  // totals, the row spans and the submit. Deriving it three times would
  // be three chances for the screen and the payload to disagree about
  // which lines exist.
  const linesByUser = useMemo(() => {
    const map = new Map<number, CrewLine[]>();
    for (const a of assignments) {
      const extras = extraLines
        .filter((line) => line.userId === a.user_id)
        .sort((x, y) => {
          const xi = hourTypes.findIndex((h) => h.id === x.hourType);
          const yi = hourTypes.findIndex((h) => h.id === y.hourType);
          return (xi < 0 ? 999 : xi) - (yi < 0 ? 999 : yi);
        });
      map.set(a.user_id, [{ userId: a.user_id, hourType: null }, ...extras]);
    }
    return map;
  }, [assignments, extraLines, hourTypes]);

  const linesFor = (userId: number): CrewLine[] =>
    linesByUser.get(userId) ?? [{ userId, hourType: null }];

  const addLine = (userId: number, hourType: number) =>
    setExtraLines((prev) =>
      prev.some((l) => l.userId === userId && l.hourType === hourType)
        ? prev
        : [...prev, { userId, hourType }],
    );

  // Removing a line clears its cells too. A line with no cells submits
  // nothing, so leaving the values behind would resurrect them the next
  // time the same kind of hour was added — a stale number nobody typed.
  const removeLine = (userId: number, hourType: number) => {
    setExtraLines((prev) =>
      prev.filter((l) => !(l.userId === userId && l.hourType === hourType)),
    );
    setHours((prev) => {
      const next = { ...prev };
      const prefix = `${userId}|`;
      const suffix = `|${hourType}`;
      for (const key of Object.keys(next)) {
        if (key.startsWith(prefix) && key.endsWith(suffix)) delete next[key];
      }
      return next;
    });
  };

  // THE COLUMNS ARE THE COMMITTED WINDOW the plan already stores. They
  // follow the two date fields above live, so moving the window
  // re-draws the grid without a save — which is the only way the two
  // controls can be understood as one decision.
  const days = useMemo(() => dayRange(start, end), [start, end]);

  // Task 3 — PAST DAYS ARE HISTORY; WORKED HOURS OWN THEM.
  //
  // Columns strictly before today render FROZEN: value visible, cell
  // read-only. This is data safety, not permission — hiding the past
  // would hide the plan's history, so the numbers stay on screen and
  // only the INPUT is withheld. The one way in is the recorded
  // override: "Unlock past days" asks for a reason FIRST, the unlock
  // holds for this dialog session, and the reason rides with the save
  // (`past_days_override_reason`), which the server requires whenever
  // a past row actually changes and writes onto the timeline. Today
  // and the future stay free; today never carries a lock glyph.
  const todayStr = localToday();
  /* W-TABS Task 3c — WHAT THE BUTTON ACTUALLY DRIVES. `apply_plan`
     only starts work from CUSTOMER_APPROVED (`_start` -> the
     IN_PROGRESS transition; anything earlier reports a skipped start).
     On the pricing-gate flow (REQUESTED / UNDER_REVIEW) the button
     saves a plan and starts nothing — starting happens after pricing —
     so the label says "Save plan" there and keeps "Plan and start"
     only where starting is a real outcome. */
  const submitStarts = !postSpawn && ew.status === "CUSTOMER_APPROVED";
  const [pastUnlocked, setPastUnlocked] = useState(false);
  const [pastReason, setPastReason] = useState("");
  const [pastPromptOpen, setPastPromptOpen] = useState(false);
  const hasPastDays = days.some((day) => day < todayStr);
  const isPastDay = (day: string) => day !== "" && day < todayStr;

  /** W-HOURS5 Task 2 — people put on the job IN THIS SESSION. Their
   *  past cells stay frozen even when the past is unlocked: they were
   *  not on the job then, and "adding a person opens today and future
   *  cells only" is the ruling. Held as ids so a person removed and
   *  re-added in the same session is still "added this session". */
  const [addedThisSession, setAddedThisSession] = useState<number[]>([]);
  const isFrozen = (userId: number, day: string) =>
    isPastDay(day) && (!pastUnlocked || addedThisSession.includes(userId));
  const frozenTitle = (userId: number, day: string) =>
    isPastDay(day) && pastUnlocked && addedThisSession.includes(userId)
      ? t("plan.added_past_frozen")
      : t("plan.past_locked_tooltip");

  const handleAssign = (userIds: number[]) => {
    if (userIds.length === 0) return;
    setAddedThisSession((prev) => [
      ...prev,
      ...userIds.filter((id) => !prev.includes(id)),
    ]);
    onAssign(userIds);
  };
  const handleAssignManagers = (userIds: number[]) => {
    if (!onAssignManagers || userIds.length === 0) return;
    setAddedThisSession((prev) => [
      ...prev,
      ...userIds.filter((id) => !prev.includes(id)),
    ]);
    // W-FIX1 D10 (audit F35) — ONE write for the whole pick. The loop
    // this replaces fired N requests behind one busy flag: the button
    // re-enabled after the first answer and the last reload won.
    onAssignManagers(userIds);
  };

  // W7 — THE VISIBLE WEEK. Display only; `days` above stays the whole
  // window and is what every total and the submit read.
  const [dayPage, setDayPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(days.length / DAY_PAGE_SIZE));
  // Clamped rather than reset: shrinking the window while looking at
  // the last page should land on the new last page, not throw the
  // operator back to the first.
  const safePage = Math.min(dayPage, pageCount - 1);
  const visibleDays = days.slice(
    safePage * DAY_PAGE_SIZE,
    safePage * DAY_PAGE_SIZE + DAY_PAGE_SIZE,
  );

  // W7 fix 3 — the control the waiting state points at.
  const startRef = useRef<HTMLInputElement | null>(null);
  const focusWindow = () => {
    startRef.current?.focus();
    startRef.current?.scrollIntoView({ block: "center" });
  };

  // Every cell in the grid, plus every UNDATED cell, plus any cell on a
  // day that is no longer in the window. That last group matters: hours
  // planned for a Thursday that has since been dropped from the window
  // still exist server-side and still count, so hiding them from the
  // total would put the screen and the server at odds — the reference
  // system's §4.4 defect, one level down.
  //
  // W-HOURS5 — only keys of people ON THE CREW. A person removed in
  // this session may still have typed values in `hours`; they are
  // neither sent nor counted, or the total on screen would name hours
  // the save will not write.
  const liveKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const [userId, lines] of linesByUser) {
      for (const line of lines) {
        keys.add(`${userId}||${line.hourType ?? ""}`);
        for (const day of days) {
          keys.add(`${userId}|${day}|${line.hourType ?? ""}`);
        }
      }
    }
    for (const key of Object.keys(hours)) {
      if (linesByUser.has(Number(key.split("|")[0]))) keys.add(key);
    }
    return keys;
  }, [linesByUser, days, hours]);

  const distributed = Array.from(liveKeys).reduce(
    (sum, key) => sum + toHours(hours[key] ?? ""),
    0,
  );

  const personTotal = (userId: number) => {
    let sum = 0;
    for (const key of liveKeys) {
      if (key.startsWith(`${userId}|`)) sum += toHours(hours[key] ?? "");
    }
    return sum;
  };

  // Across every LINE on that day, not one cell per person: a day with
  // eight normal and four night hours totals twelve.
  const dayTotal = (day: string) => {
    let sum = 0;
    for (const [userId, lines] of linesByUser) {
      for (const line of lines) {
        sum += toHours(hours[cellKey(userId, day, line.hourType)] ?? "");
      }
    }
    return sum;
  };
  const budgetHours = toHours(budget);
  // A budget of zero is a real budget; only a BLANK one means "no budget
  // set", which is nothing to overrun. Same reading as the server's
  // `hours_overrun`, which returns None when `budget_hours` is null.
  const hasBudget = budget.trim() !== "";
  const overrun = hasBudget && distributed > budgetHours;
  const overBy = (distributed - budgetHours).toFixed(2);

  const workers = assignments.filter((a) => a.role !== "MANAGER");
  const managers = assignments.filter((a) => a.role === "MANAGER");
  const personName = (a: ExtraWorkAssignment) => a.user_full_name || a.user_email;

  function submit() {
    const payload: ExtraWorkPlanPayload = {};
    // OMIT, never default. A blank budget field means "leave the stored
    // budget alone"; clearing a budget is a different intention and this
    // dialog does not offer it.
    if (budget.trim() !== "") payload.budget_hours = budget.trim();
    if (start !== "") payload.provider_planned_date = start;
    if (end !== "") payload.provider_planned_end_date = end;
    if (assignments.length > 0) {
      // W6-H — one entry per NON-EMPTY cell. A blank cell is not "zero
      // hours on that day", it is "no plan for that day", and sending a
      // zero for every day of a two-week window would fill the grid
      // with rows nobody entered.
      const cells: {
        user: number;
        date?: string | null;
        hour_type?: number | null;
        hours: string;
      }[] = [];
      for (const [userId, lines] of linesByUser) {
        let any = false;
        for (const line of lines) {
          // Every day of the window PLUS the undated cell PLUS any day
          // this person already has hours on that has since dropped out
          // of the window — the last group is why this walks `liveKeys`
          // rather than `days`. Hours on a dropped day still exist
          // server-side and still count; omitting them here would
          // silently delete them.
          for (const key of liveKeys) {
            const [rawUser, rawDay, rawType] = key.split("|");
            if (Number(rawUser) !== userId) continue;
            if ((rawType === "" ? null : Number(rawType)) !== line.hourType) {
              continue;
            }
            const raw = (hours[key] ?? "").trim();
            if (raw === "") continue;
            cells.push({
              user: userId,
              date: rawDay === "" ? null : rawDay,
              // Omitted-or-null both mean ORDINARY hours server-side, so
              // the ordinary line sends null and reads identically to
              // every pre-W7 payload.
              hour_type: line.hourType,
              hours: raw.replace(",", "."),
            });
            any = true;
          }
        }
        // The person-level exception is deliberate and unchanged:
        // somebody on the crew with nothing anywhere still gets one
        // undated ordinary zero row, because "on the job, no hours
        // budgeted yet" is a state the plan has always expressed and
        // losing it would drop them off the screen entirely.
        if (!any) {
          cells.push({ user: userId, date: null, hour_type: null, hours: "0" });
        }
      }
      payload.planned_hours = cells;
    }
    if (photoTouched) payload.file_upload_required = photoRequired;
    if (notesTouched) payload.completion_notes_required = notesRequired;
    // Task 3 — the unlock's reason travels with the save. The server
    // demands it exactly when a past row actually changed, so sending
    // it on an unlock that touched nothing is inert.
    if (pastUnlocked && pastReason.trim() !== "") {
      (
        payload as ExtraWorkPlanPayload & {
          past_days_override_reason?: string;
        }
      ).past_days_override_reason = pastReason.trim();
    }
    onSubmit(payload);
  }

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("plan.dialog_title")}
      data-testid="extra-work-plan-dialog"
    >
      {/* W-HOURS5 Task 1 — HEAD / BODY / FOOT. The body is the one
          thing that scrolls; the foot's top edge is the fold, on every
          screen, and the actions never leave it. */}
      <div className="card ew-plan-dialog ew-plan-dialog--framed">
        <div className="ew-plan-head">
          <h3 className="section-title ew-plan-dialog-title">
            {t("plan.dialog_title")}
          </h3>
          <p className="muted small ew-plan-dialog-sub">
            {t("plan.dialog_subtitle")}
          </p>
        </div>

        <div className="ew-plan-body" data-testid="extra-work-plan-body">
        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-plan-error"
          >
            {error}
          </div>
        )}

        {/* W7 fix 3 — THE WINDOW COMES FIRST.
            It used to sit under the budget, and the grid below it drew
            no day columns until it was set — so the dialog opened on a
            budget box and one blank column, with a sentence beneath a
            scrollbar explaining why. The owner never found the feature.
            The decision that unlocks the rest of the screen is now the
            first thing on it, numbered, and the grid says the same
            thing again in its own body rather than in a footnote.

            OUR dates, with the customer's shown beside them read-only.
            Two pairs of dates on one screen is exactly the confusion the
            labels have to prevent. */}
        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            <span className="ew-plan-step">1</span>
            {t("plan.our_window_title")}
          </div>
          <div className="ew-plan-dates">
            <label className="field">
              <span className="muted small">
                {t("plan.our_start_label")}
                <span className="ew-plan-req" aria-hidden="true">*</span>
              </span>
              <input
                ref={startRef}
                type="date"
                className="field-input"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                data-testid="extra-work-plan-start"
              />
            </label>
            <label className="field">
              <span className="muted small">{t("plan.our_end_label")}</span>
              <input
                type="date"
                className="field-input"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                data-testid="extra-work-plan-end"
              />
            </label>
          </div>
          <div
            className="ew-plan-customer-dates"
            data-testid="extra-work-plan-customer-dates"
          >
            <span className="muted small">
              {t("plan.customer_asked_label")}
            </span>
            <span className="muted small">
              {t("plan.customer_preferred", {
                date: ew.preferred_date
                  ? formatDate(ew.preferred_date)
                  : t("detail.empty_dash"),
              })}
            </span>
            <span className="muted small">
              {t("plan.customer_deadline", {
                date: ew.deadline
                  ? formatDate(ew.deadline)
                  : t("detail.empty_dash"),
              })}
            </span>
          </div>
          {/* W-FIX1 B3 (audit F15) — allowed, flagged, never blocked. */}
          {end && ew.deadline && end > ew.deadline && (
            <p
              className="muted small ew-hours-tone-over"
              data-testid="extra-work-plan-end-after-deadline"
            >
              {t("plan.end_after_deadline", {
                count: daysBetweenIso(ew.deadline, end),
              })}
            </p>
          )}
        </div>

        <div className="ew-plan-section">
          <label className="field ew-plan-budget">
            <span className="muted small">
              {t("plan.budget_hours_label")}
              <span className="ew-plan-req" aria-hidden="true">*</span>
            </span>
            <input
              type="number"
              min="0"
              step="0.25"
              inputMode="decimal"
              className="field-input"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              data-testid="extra-work-plan-budget"
            />
            <span className="muted small">{t("plan.budget_hours_hint")}</span>
          </label>
        </div>

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            <span className="ew-plan-step">2</span>
            {t("plan.hours_title")}
            <span className="ew-plan-req" aria-hidden="true">*</span>
          </div>
          {/* W-HOURS5 Task 2 — THE CREW, both halves, owned here.
              People and responsible managers each read from the same
              `assignments` rows the grid reads, each carry a chip x
              (when the page offers a remove) and a one-line multi-select
              adder over the candidates the page handed over. Provider-
              only by construction: the plan dialog has no customer entry
              point. */}
          <div className="ew-plan-crew" data-testid="extra-work-plan-crew">
            <div
              className="ew-plan-crew-group"
              data-testid="extra-work-plan-people"
            >
              <span className="field-label">
                {t("plan.people_label")}
                <span className="ew-plan-req" aria-hidden="true">*</span>
              </span>
              <div className="ew-plan-manager-row">
                {workers.map((a) => (
                  <span
                    key={a.id}
                    className="parts-chip"
                    data-testid="extra-work-plan-person-chip"
                    data-user-id={a.user_id}
                  >
                    {personName(a)}
                    {onRemovePerson && (
                      <button
                        type="button"
                        className="ew-plan-type-remove"
                        disabled={removeBusy || assignBusy}
                        onClick={() => onRemovePerson(a.user_id)}
                        aria-label={t("plan.person_remove", {
                          name: personName(a),
                        })}
                        data-testid="extra-work-plan-person-remove"
                      >
                        <X size={12} aria-hidden="true" />
                      </button>
                    )}
                  </span>
                ))}
                {workers.length === 0 && (
                  <span
                    className="muted small"
                    data-testid="extra-work-plan-people-none"
                  >
                    {t("plan.people_none")}
                  </span>
                )}
              </div>
              {onRemovePerson && (
                <p
                  className="muted small ew-plan-crew-hint"
                  data-testid="extra-work-plan-remove-hint"
                >
                  {t("plan.remove_person_hint")}
                </p>
              )}
              <CrewAdder
                candidates={candidates}
                loading={candidatesLoading}
                busy={assignBusy}
                error={assignError}
                onAssign={handleAssign}
                placeholderKey="plan.add_people_pick"
                buttonKey="plan.add_people"
                testId="extra-work-plan-crew-add"
              />
            </div>

            {/* W-TABS Task 3b — RESPONSIBLE MANAGERS, beside the crew.
                Same rows, same chips, same adder. */}
            <div
              className="ew-plan-crew-group"
              data-testid="extra-work-plan-manager"
            >
              <span className="field-label">
                {t("plan.manager_label")}
                <span className="ew-plan-req" aria-hidden="true">*</span>
              </span>
              <div className="ew-plan-manager-row">
                {managers.map((a) => (
                  <span
                    key={a.id}
                    className="parts-chip"
                    data-testid="extra-work-plan-manager-chip"
                    data-user-id={a.user_id}
                  >
                    {personName(a)}
                    {onRemoveManager && (
                      <button
                        type="button"
                        className="ew-plan-type-remove"
                        disabled={managerBusy || removeBusy}
                        onClick={() => onRemoveManager(a.user_id)}
                        aria-label={t("plan.manager_remove", {
                          name: personName(a),
                        })}
                        data-testid="extra-work-plan-manager-remove"
                      >
                        <X size={12} aria-hidden="true" />
                      </button>
                    )}
                  </span>
                ))}
                {managers.length === 0 && (
                  <span
                    className="muted small"
                    data-testid="extra-work-plan-manager-none"
                  >
                    {t("plan.manager_none")}
                  </span>
                )}
              </div>
              {onAssignManagers && (
                <CrewAdder
                  candidates={managerCandidates}
                  loading={false}
                  busy={managerBusy}
                  error=""
                  onAssign={handleAssignManagers}
                  placeholderKey="plan.add_managers_pick"
                  buttonKey="plan.add_managers_button"
                  testId="extra-work-plan-manager-add"
                />
              )}
            </div>
          </div>
          {assignmentsLoading ? (
            <div className="loading-bar">
              <div className="loading-bar-fill" />
            </div>
          ) : assignments.length === 0 ? (
            /* Not an empty table — the backend refuses hours for anybody
               not assigned, so the fix is upstream and the message says
               where. */
            <div
              className="ew-plan-empty"
              data-testid="extra-work-plan-no-crew"
            >
              <Users size={18} aria-hidden="true" />
              <div>
                <div className="ew-plan-empty-title">
                  {t("plan.no_crew_title")}
                </div>
                <div className="muted small">{t("plan.no_crew_hint")}</div>
              </div>
            </div>
          ) : (
            <>
              {/* W6-H — PEOPLE DOWN THE SIDE, PLANNED DAYS ACROSS THE
                  TOP. The columns are the committed window the plan
                  already stores, so setting the window and filling the
                  grid are one decision rather than two screens.

                  The "no day yet" column is always present and is not a
                  fallback: a plan can legitimately say "Gokhan: 8
                  hours" before anyone has decided which day, and that
                  was the ONLY thing this dialog could say before W6-H.
                  Dropping it would break every existing plan. */}
              {/* The pager. Only when there is more than one week to
                  page through — a three-day job gets no controls it
                  does not need. */}
              {pageCount > 1 && (
                <div className="ew-plan-day-pager">
                  <span
                    className="ew-plan-day-pager-label"
                    data-testid="extra-work-plan-day-page-label"
                  >
                    {t("plan.day_page_label", {
                      from: safePage * DAY_PAGE_SIZE + 1,
                      to: safePage * DAY_PAGE_SIZE + visibleDays.length,
                      total: days.length,
                    })}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setDayPage(Math.max(0, safePage - 1))}
                    disabled={safePage === 0}
                    aria-label={t("plan.day_page_prev")}
                    data-testid="extra-work-plan-day-prev"
                  >
                    <ChevronLeft size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      setDayPage(Math.min(pageCount - 1, safePage + 1))
                    }
                    disabled={safePage >= pageCount - 1}
                    aria-label={t("plan.day_page_next")}
                    data-testid="extra-work-plan-day-next"
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                  </button>
                </div>
              )}
              {hasPastDays && (
                <div
                  className="ew-plan-past-bar"
                  data-testid="extra-work-plan-past-bar"
                >
                  {pastUnlocked ? (
                    <span
                      className="muted small"
                      data-testid="extra-work-plan-past-unlocked"
                    >
                      {t("plan.unlock_past_active")}
                    </span>
                  ) : pastPromptOpen ? (
                    /* Task 3 — the reason is asked BEFORE anything
                       unlocks. Confirm is disabled until it is given;
                       "Keep locked" backs out without unlocking. */
                    <div className="ew-plan-past-prompt">
                      <textarea
                        className="field-textarea"
                        rows={2}
                        autoFocus
                        value={pastReason}
                        onChange={(e) => setPastReason(e.target.value)}
                        placeholder={t("plan.unlock_past_reason_placeholder")}
                        aria-label={t(
                          "plan.unlock_past_reason_placeholder",
                        )}
                        data-testid="extra-work-plan-past-reason"
                      />
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={pastReason.trim() === ""}
                        onClick={() => setPastUnlocked(true)}
                        data-testid="extra-work-plan-past-unlock-confirm"
                      >
                        {t("plan.unlock_past_confirm")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          setPastPromptOpen(false);
                          setPastReason("");
                        }}
                        data-testid="extra-work-plan-past-unlock-cancel"
                      >
                        {t("plan.unlock_past_cancel")}
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setPastPromptOpen(true)}
                      title={t("plan.past_locked_tooltip")}
                      data-testid="extra-work-plan-past-unlock"
                    >
                      <Lock size={13} aria-hidden="true" />
                      <span style={{ marginLeft: 6 }}>
                        {t("plan.unlock_past")}
                      </span>
                    </button>
                  )}
                </div>
              )}
              <div className="ew-plan-grid-scroll">
                <table className="data-table ew-plan-grid">
                  <thead>
                    <tr>
                      <th className="ew-plan-grid-name">
                        {t("plan.grid_person")}
                      </th>
                      <th className="ew-plan-grid-type">
                        {t("plan.grid_hour_type")}
                      </th>
                      <th className="ew-plan-grid-cell">
                        {t("plan.grid_no_day")}
                      </th>
                      {visibleDays.map((day) => (
                        <th
                          key={day}
                          className="ew-plan-grid-cell"
                          title={
                            isPastDay(day)
                              ? t("plan.past_locked_tooltip")
                              : undefined
                          }
                          data-testid="extra-work-plan-day-head"
                          data-day={day}
                          data-past={isPastDay(day) ? "true" : "false"}
                        >
                          {isPastDay(day) && !pastUnlocked && (
                            <Lock
                              size={10}
                              aria-hidden="true"
                              className="ew-plan-past-lock"
                              data-testid="extra-work-plan-day-lock"
                            />
                          )}
                          {formatDayHeader(day)}
                        </th>
                      ))}
                      <th className="ew-plan-grid-cell">
                        {t("plan.grid_row_total")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((a) => {
                      const lines = linesFor(a.user_id);
                      const used = new Set(
                        lines
                          .map((l) => l.hourType)
                          .filter((id): id is number => id !== null),
                      );
                      const addable = hourTypes.filter(
                        (h) => !used.has(h.id),
                      );
                      return lines.map((line, index) => (
                        <tr
                          key={lineKey(line)}
                          data-testid="extra-work-plan-crew-row"
                          data-user-id={a.user_id}
                          data-hour-type={line.hourType ?? ""}
                        >
                          {/* The name is written ONCE and spans the
                              person's lines — the reference system's
                              shape, and the only way a crew of three
                              with a night shift each reads as three
                              blocks rather than six unrelated rows. */}
                          {index === 0 && (
                            <td
                              className="ew-plan-grid-name"
                              rowSpan={lines.length}
                            >
                              <div className="ew-plan-grid-person">
                                <span>{personName(a)}</span>
                                {addable.length > 0 && (
                                  <select
                                    className="ew-plan-add-type"
                                    value=""
                                    onChange={(e) => {
                                      if (e.target.value === "") return;
                                      addLine(
                                        a.user_id,
                                        Number(e.target.value),
                                      );
                                    }}
                                    aria-label={t("plan.add_hour_type", {
                                      name: personName(a),
                                    })}
                                    data-testid="extra-work-plan-add-hour-type"
                                  >
                                    <option value="">
                                      {t("plan.add_hour_type_placeholder")}
                                    </option>
                                    {addable.map((h) => (
                                      <option key={h.id} value={h.id}>
                                        {h.name}
                                      </option>
                                    ))}
                                  </select>
                                )}
                              </div>
                            </td>
                          )}
                          <td className="ew-plan-grid-type">
                            <div className="ew-plan-type-line">
                              <span>{hourTypeName(line.hourType)}</span>
                              {/* Ordinary hours cannot be removed: it is
                                  the line every plan has and the one a
                                  person with no split falls back to. */}
                              {line.hourType !== null && (
                                <button
                                  type="button"
                                  className="ew-plan-type-remove"
                                  onClick={() =>
                                    removeLine(a.user_id, line.hourType!)
                                  }
                                  aria-label={t("plan.remove_hour_type", {
                                    type: hourTypeName(line.hourType),
                                  })}
                                  data-testid="extra-work-plan-remove-hour-type"
                                >
                                  <X size={13} aria-hidden="true" />
                                </button>
                              )}
                            </div>
                          </td>
                          {["", ...visibleDays].map((day) => (
                            <td
                              key={day || "none"}
                              className="ew-plan-grid-cell"
                              title={
                                isFrozen(a.user_id, day)
                                  ? frozenTitle(a.user_id, day)
                                  : undefined
                              }
                            >
                              {isFrozen(a.user_id, day) ? (
                                /* FROZEN, not absent: the value stays
                                   on screen — hiding it would hide the
                                   plan's history. */
                                <span
                                  className="ew-plan-cell-frozen"
                                  data-testid="extra-work-plan-frozen-cell"
                                  data-day={day}
                                >
                                  {hours[
                                    cellKey(a.user_id, day, line.hourType)
                                  ] ?? "—"}
                                </span>
                              ) : (
                              <input
                                type="number"
                                min="0"
                                step="0.25"
                                inputMode="decimal"
                                className="field-input ew-plan-crew-hours"
                                value={
                                  hours[
                                    cellKey(a.user_id, day, line.hourType)
                                  ] ?? ""
                                }
                                onChange={(e) =>
                                  setHours((prev) => ({
                                    ...prev,
                                    [cellKey(
                                      a.user_id,
                                      day,
                                      line.hourType,
                                    )]: e.target.value,
                                  }))
                                }
                                /* W-HOURS5 Task 1 — a cell that gains
                                   focus brings its whole row into view,
                                   so a half-clipped last row is never
                                   typed into blind. */
                                onFocus={(e) =>
                                  e.currentTarget.scrollIntoView({
                                    block: "nearest",
                                  })
                                }
                                aria-label={`${t("plan.hours_for", {
                                  name: personName(a),
                                })} ${hourTypeName(line.hourType)} ${
                                  day || t("plan.grid_no_day")
                                }`}
                                data-testid="extra-work-plan-crew-hours"
                                data-day={day}
                                data-hour-type={line.hourType ?? ""}
                              />
                              )}
                            </td>
                          ))}
                          {index === 0 && (
                            <td
                              className="ew-plan-grid-cell"
                              rowSpan={lines.length}
                            >
                              <strong data-testid="extra-work-plan-row-total">
                                {personTotal(a.user_id).toFixed(2)}
                              </strong>
                            </td>
                          )}
                        </tr>
                      ));
                    })}
                    {/* W7 fix 3 — THE WAITING STATE, IN THE GRID.
                        With no window there are no day columns, and the
                        old dialog explained that in a sentence below a
                        scrollbar. It says it here instead, in the space
                        the day columns will occupy, with the control
                        that fills them. */}
                    {days.length === 0 && (
                      <tr data-testid="extra-work-plan-no-window">
                        <td
                          className="ew-plan-grid-waiting"
                          colSpan={4}
                        >
                          <div className="ew-plan-grid-waiting-title">
                            {t("plan.grid_waiting_title")}
                          </div>
                          <div className="muted small">
                            {t("plan.grid_waiting_hint")}
                          </div>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ marginTop: 8 }}
                            onClick={focusWindow}
                            data-testid="extra-work-plan-goto-window"
                          >
                            <CalendarPlus size={14} aria-hidden="true" />
                            {t("plan.grid_waiting_action")}
                          </button>
                        </td>
                      </tr>
                    )}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className="ew-plan-grid-name">
                        {t("plan.grid_day_total")}
                      </td>
                      <td className="ew-plan-grid-type" />
                      <td className="ew-plan-grid-cell" />
                      {visibleDays.map((day) => (
                        <td key={day} className="ew-plan-grid-cell">
                          {dayTotal(day).toFixed(2)}
                        </td>
                      ))}
                      <td className="ew-plan-grid-cell">
                        <strong data-testid="extra-work-plan-total">
                          {distributed.toFixed(2)}
                        </strong>
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
              <div className="ew-plan-total" data-testid="extra-work-plan-total-line">
                <span>{t("plan.distributed_label")}</span>
                <strong>
                  {t("plan.hours_value", { hours: distributed.toFixed(2) })}
                </strong>
              </div>
            </>
          )}
        </div>

        {/* WARNS, NEVER BLOCKS. The submit button below is not disabled
            by this and must never be — see (3) in the docblock. */}
        {overrun && (
          <div
            className="ew-plan-overrun"
            role="status"
            data-testid="extra-work-plan-overrun"
          >
            <AlertTriangle size={18} aria-hidden="true" />
            <div>
              <div className="ew-plan-overrun-title">
                {t("plan.overrun_title", {
                  over: overBy,
                })}
              </div>
              <div className="muted small">
                {t("plan.overrun_hint", {
                  distributed: distributed.toFixed(2),
                  budget: budgetHours.toFixed(2),
                })}
              </div>
            </div>
          </div>
        )}

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("plan.completion_title")}
          </div>
          <label className="ew-plan-switch">
            <Toggle
              checked={photoRequired}
              onChange={(e) => {
                setPhotoRequired(e.target.checked);
                setPhotoTouched(true);
              }}
              data-testid="extra-work-plan-photo-required"
            />
            <span>{t("plan.photo_required_label")}</span>
          </label>
          <label className="ew-plan-switch">
            <Toggle
              checked={notesRequired}
              onChange={(e) => {
                setNotesRequired(e.target.checked);
                setNotesTouched(true);
              }}
              data-testid="extra-work-plan-notes-required"
            />
            <span>{t("plan.notes_required_label")}</span>
          </label>
        </div>
        </div>

        <div className="ew-plan-foot" data-testid="extra-work-plan-foot">
          <div className="ew-plan-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
              disabled={busy}
              data-testid="extra-work-plan-cancel"
            >
              {t("common:cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              /* `busy` only. NOT `overrun`. */
              disabled={busy}
              onClick={submit}
              data-testid="extra-work-plan-submit"
            >
              {busy
                ? t("plan.submitting")
                : t(submitStarts ? "plan.submit" : "plan.submit_save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


/** W-HOURS5 Task 2 — the crew's adder: ONE line, several people, one Add.
 *
 *  Replaces the checkbox list (`.assign-picker`) that stood here since
 *  W-UX1 §2: on a crew of thirty that list was a scroll box the height
 *  of the grid itself, which is part of why the grid's last row sat
 *  below the fold (Task 1). `ChipMultiSelect` is the standing people
 *  picker — every picker multi-selects — and it keeps to a line.
 *
 *  R2 is enforced by the caller: `candidates` arrives already filtered
 *  to the not-yet-assigned, so a person on the crew never appears here
 *  as something to add again. Nothing to offer = nothing rendered.
 */
function CrewAdder({
  candidates,
  loading,
  busy,
  error,
  onAssign,
  placeholderKey,
  buttonKey,
  testId,
}: {
  candidates: AssignmentCandidate[];
  loading: boolean;
  busy: boolean;
  error: string;
  onAssign: (userIds: number[]) => void;
  placeholderKey: string;
  buttonKey: string;
  testId: string;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [picked, setPicked] = useState<number[]>([]);

  if (loading) {
    return (
      <div className="loading-bar">
        <div className="loading-bar-fill" />
      </div>
    );
  }
  if (candidates.length === 0 && !error) {
    return null;
  }
  return (
    <div className="ew-plan-crew-add" data-testid={testId}>
      <div className="ew-plan-crew-add-line">
        <div className="ew-plan-crew-add-picker">
          <ChipMultiSelect
            options={candidates.map((person) => ({
              id: person.id,
              label: person.full_name?.trim() || person.email,
              sublabel: person.email,
            }))}
            selectedIds={picked}
            onChange={setPicked}
            placeholder={t(placeholderKey)}
            removeLabel={(label) => t("plan.person_remove", { name: label })}
            emptyText={t("plan.no_candidates")}
            disabled={busy}
            testIdPrefix={`${testId}-picker`}
          />
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={busy || picked.length === 0}
          onClick={() => {
            onAssign(picked);
            setPicked([]);
          }}
          data-testid={`${testId}-button`}
        >
          {busy ? t("plan.adding_people") : t(buttonKey)}
        </button>
      </div>
      {error && (
        <p className="alert-error" role="alert" data-testid={`${testId}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}
