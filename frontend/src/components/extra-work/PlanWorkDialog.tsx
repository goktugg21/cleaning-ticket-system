/**
 * P-4 (Part B) — the plan dialog, rebuilt as a guided staged flow.
 *
 * THE LAW (owner, 2026-08-30): a person who knows nothing about
 * computers or this system must be able to finish planning a job
 * without knowing it beforehand. The owner walked the old dialog and
 * got stressed, lost, and blocked by an invisible error. So: one thing
 * at a time, plain words, every number on screen, every error where
 * the person is.
 *
 * THE THREE STAGES
 *   1. WHEN — "First work day" / "Last work day". The customer's
 *      wish and deadline in one plain strip beside them. A day past
 *      the deadline warns INLINE, at the field, the moment it happens.
 *   2. WHO AND HOW MUCH — the people; each person gets the plan's days
 *      as chips, an hours box per chosen day, a box for "hours without
 *      a day yet", a visible per-person total and a grand total. Any
 *      day combination (2+3, 1+3, a single day) reads exactly as
 *      chosen. The hours budget is optional and sits under the total.
 *   3. DONE MEANS — the two completion switches, one line each.
 *
 * THE DOUBLE-COUNT (the reason this was rebuilt first). The owner typed
 * 4 in the "no day yet" box and 4 on one day and the total read 12.
 * The old grid kept hours on a day that had dropped out of the window
 * in state, in the total and in the payload (W7's "paging is display
 * only", one level too far): the phantom 4 was a day nobody could see.
 * Here a number counts only if it is ON SCREEN: a chosen day's box, the
 * "no day yet" box, or a clearly marked "outside the plan" day kept
 * from an earlier plan. Un-choosing a day deletes its hours, visibly.
 * The server refuses new hours outside the window too
 * (`planning.ERR_PLANNED_HOURS_OUTSIDE_WINDOW`, tested in
 * `extra_work/tests/test_p4_plan_days.py`).
 *
 * MOVING A PLAN. When the first work day moves and people already have
 * days, the dialog asks in plain words: "Also move everyone's planned
 * days along?" — yes shifts every dated row by the same difference
 * INSIDE THE SAME SAVE (the payload replaces the distribution; no new
 * endpoint); no keeps them and says "People's days stayed on the old
 * dates — adjust them below", showing them as outside-the-plan chips.
 *
 * ERRORS LIVE WHERE THE PERSON IS. Field-level messages at the field,
 * a one-line summary next to Save, the first error scrolled into
 * view. The server's coded refusals (`plan_past_day_locked`,
 * `planned_hours_outside_window`, the end-before-start pair, DRF
 * per-field entries) are mapped to fields through
 * `lib/apiFieldErrors`; the generic "That was not accepted" appears
 * only when the server truly gave no field detail.
 *
 * KEPT FROM BEFORE (the owner praised these): past days stay
 * unplannable — a past chip is locked and only "Unlock past days" with
 * a recorded reason opens it, the reason riding with the save
 * (`past_days_override_reason`); a person added in this session gets
 * today-and-future only; overrun WARNS and never blocks (the reference
 * system's hard cap was removed by the business — do not add
 * `disabled={overrun}`); absence means "leave it alone" for the two
 * switches; the submit says PLAN AND START where starting is a real
 * outcome and "Save the plan" elsewhere.
 *
 * NO FIGURE IN HERE IS MONEY. Hours only; `rowAmounts()` is never
 * imported.
 *
 * A non-native overlay, conditionally mounted — CLAUDE.md's
 * render-it-unconditionally rule is about the native `<dialog>`.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Lock, Users, X } from "lucide-react";

import type {
  AssignmentCandidate,
  ExtraWorkAssignment,
  ExtraWorkPlanPayload,
  ExtraWorkRequestDetail,
} from "../../api/types";
import type { HourType } from "../../api/timesheets.types";
import { listHourTypes } from "../../api/timesheets";
import { dayRange } from "../../lib/planGridDays";
import { readApiErrorDetail } from "../../lib/apiFieldErrors";
import { formatDate } from "../../lib/intl";
import { hourTypeLabel } from "../../lib/hourTypeLabel";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { ConfirmDialog, type ConfirmDialogHandle } from "../ConfirmDialog";
import { Toggle } from "../Toggle";
import "./plan-crew.css";

/** One line of a person's hours: ordinary (`hourType` null) or one
 *  kind of hour from the company's own `timesheets.HourType` catalog —
 *  never a second vocabulary. */
interface CrewLine {
  userId: number;
  hourType: number | null;
}

/** Hours arithmetic on the strings the person typed. Comparison only;
 *  what reaches the API is the string. */
function toHours(value: string): number {
  const parsed = Number.parseFloat((value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

/** The LOCAL wall date — the UTC date is yesterday's or tomorrow's for
 *  half the world. */
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Signed whole days from `from` to `to`, both YYYY-MM-DD, local. */
function daysBetweenIso(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / 86400000);
}

function shiftDay(day: string, delta: number): string {
  const date = parseDay(day);
  date.setDate(date.getDate() + delta);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** A cell key: `user|YYYY-MM-DD|hourType`, the day "" for "no day yet"
 *  and the type "" for ordinary hours. One flat key per number on
 *  screen, so an accidental whole-row overwrite is unspellable. */
function cellKey(userId: number, day: string, hourType: number | null): string {
  return `${userId}|${day}|${hourType ?? ""}`;
}
function splitKey(key: string): { userId: number; day: string; hourType: number | null } {
  const [rawUser, rawDay, rawType] = key.split("|");
  return { userId: Number(rawUser), day: rawDay, hourType: rawType === "" ? null : Number(rawType) };
}

/** Which fields the dialog can point an error at. */
type FieldKey = "start" | "end" | "people" | "manager" | "hours" | "move" | "past" | "budget";

const FIELD_ORDER: FieldKey[] = ["start", "end", "move", "people", "manager", "hours", "past", "budget"];

/** P-5 S2.4 — the parts of the plan a "this is missing" pointer can
 *  land on, and the sentence each one says when it does. */
export type PlanFocus = "start" | "people" | "manager" | "hours";
const FOCUS_NEEDS: Record<PlanFocus, string> = {
  start: "plan_gate.missing_start_date",
  people: "plan_gate.missing_staff",
  manager: "plan_gate.missing_manager",
  hours: "plan_gate.missing_hours",
};

/** Scroll the first field that has an error into view. Looks the field
 *  up by its `data-plan-field` attribute inside the open dialog. */
function scrollToFirstField(fields: Partial<Record<FieldKey, string>>): void {
  const first = FIELD_ORDER.find((key) => fields[key]);
  if (!first) return;
  const el = document.querySelector<HTMLElement>(
    `[data-testid="extra-work-plan-dialog"] [data-plan-field="${first}"]`,
  );
  el?.scrollIntoView({ block: "center", behavior: "smooth" });
}

export function PlanWorkDialog({
  ew,
  assignments,
  assignmentsLoading,
  busy,
  error,
  rawError,
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
  initialFocus = null,
}: {
  ew: ExtraWorkRequestDetail;
  assignments: ExtraWorkAssignment[];
  assignmentsLoading: boolean;
  busy: boolean;
  /** The page's one-sentence reading of the last refusal. Shown next to
   *  Save ONLY when `rawError` carries no field detail. */
  error: string;
  /** P-4 — the refusal itself, so its field detail can land at the
   *  field. Optional: a page that passes none gets the sentence only. */
  rawError?: unknown;
  onCancel: () => void;
  onSubmit: (payload: ExtraWorkPlanPayload) => void;
  candidates: AssignmentCandidate[];
  candidatesLoading: boolean;
  assignBusy: boolean;
  assignError: string;
  onAssign: (userIds: number[]) => void;
  managerCandidates?: AssignmentCandidate[];
  managerBusy?: boolean;
  onAssignManagers?: (userIds: number[]) => void;
  onRemoveManager?: (userId: number) => void;
  onRemovePerson?: (userId: number) => void;
  removeBusy?: boolean;
  /** Mounted from a spawned ticket: same dialog, same store; the
   *  submit says "Save the plan" because starting is the ticket's
   *  business now. */
  postSpawn?: boolean;
  /** P-5 S2.4 — open scrolled to and highlighting this missing part,
   *  which says what it needs. The missing-piece pointer pattern. */
  initialFocus?: PlanFocus | null;
}) {
  const { t, i18n } = useTranslation(["extra_work", "common"]);
  const locale = i18n.language || "nl";

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel, busy]);

  // ---- stage 1: when ---------------------------------------------------
  // P-5 S2.4 — land on the missing part once, after the first paint.
  useEffect(() => {
    if (!initialFocus) return;
    const el = document.querySelector<HTMLElement>(
      `[data-testid="extra-work-plan-dialog"] [data-plan-field="${initialFocus}"]`,
    );
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("piece-highlight");
    const timer = window.setTimeout(() => el.classList.remove("piece-highlight"), 4000);
    return () => window.clearTimeout(timer);
  }, [initialFocus]);
  const focusNotice = (key: PlanFocus) =>
    initialFocus === key ? (
      <p className="alert-notice" role="status" data-testid={`extra-work-plan-needs-${key}`}>
        {t("plan.piece_needed", { what: t(FOCUS_NEEDS[key]) })}
      </p>
    ) : null;
  // P-5 S2.3 — an hours box COMMITS on blur / Enter: the value is
  // normalised and the totals flash "counted" for a moment, so the
  // operator sees the number land instead of wondering whether it did.
  const [committedAt, setCommittedAt] = useState(0);
  useEffect(() => {
    if (!committedAt) return;
    const timer = window.setTimeout(() => setCommittedAt(0), 900);
    return () => window.clearTimeout(timer);
  }, [committedAt]);
  const commitHours = (key: string) => {
    setHours((prev) => {
      const raw = (prev[key] ?? "").trim().replace(",", ".");
      if (raw === "") return prev;
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 0) return prev;
      const normalised = String(Math.round(n * 100) / 100);
      return normalised === prev[key] ? prev : { ...prev, [key]: normalised };
    });
    // A counter, not `Date.now()`: the value only has to CHANGE to
    // re-arm the flash, and a pure updater keeps the render pure.
    setCommittedAt((tick) => tick + 1);
  };
  const committedClass = committedAt ? " is-committed" : "";
  const seededStart = ew.provider_planned_date ?? "";
  const [start, setStart] = useState(seededStart);
  const [end, setEnd] = useState(ew.provider_planned_end_date ?? "");
  const days = useMemo(() => dayRange(start, end || start), [start, end]);
  const todayStr = localToday();
  const isPastDay = (day: string) => day !== "" && day < todayStr;

  // ---- stage 2: who and how much ------------------------------------
  const [budget, setBudget] = useState(ew.budget_hours ?? "");
  /** What the server holds right now, keyed like the cells. Unchanged
   *  values on days outside the window are allowed through the save
   *  (the server keeps them); anything else outside is refused. */
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
  /** Which days each person has CHOSEN: `user|day`. A chosen day shows
   *  its box even while empty; un-choosing deletes the day's hours. */
  const [chosen, setChosen] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const row of ew.planned_hours ?? []) {
      if (row.date) initial[`${row.user_id}|${row.date}`] = true;
    }
    return initial;
  });

  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  useEffect(() => {
    let cancelled = false;
    listHourTypes({ company: ew.company, is_active: true })
      .then((rows) => {
        if (!cancelled) setHourTypes(rows);
      })
      .catch(() => {
        if (!cancelled) setHourTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ew.company]);

  const hourTypeName = (id: number | null) =>
    id === null
      ? t("plan.hour_type_ordinary")
      : ((() => {
          const known = hourTypes.find((h) => h.id === id);
          return known ? hourTypeLabel(known, t) : undefined;
        })() ??
        (ew.planned_hours ?? []).find((r) => r.hour_type === id)?.hour_type_name ??
        t("plan.hour_type_unknown"));

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

  const workers = assignments.filter((a) => a.role !== "MANAGER");
  const managers = assignments.filter((a) => a.role === "MANAGER");
  // P-5 S2.2 — managers plan hours too (they did before the rebuild;
  // the server stores their rows like anyone's). Workers first.
  const crew = useMemo(() => [...workers, ...managers], [workers, managers]);
  const personName = (a: ExtraWorkAssignment) => a.user_full_name || a.user_email;

  const linesFor = (userId: number): CrewLine[] => {
    const extras = extraLines
      .filter((line) => line.userId === userId)
      .sort((x, y) => {
        const xi = hourTypes.findIndex((h) => h.id === x.hourType);
        const yi = hourTypes.findIndex((h) => h.id === y.hourType);
        return (xi < 0 ? 999 : xi) - (yi < 0 ? 999 : yi);
      });
    return [{ userId, hourType: null }, ...extras];
  };

  const addLine = (userId: number, hourType: number) =>
    setExtraLines((prev) =>
      prev.some((l) => l.userId === userId && l.hourType === hourType)
        ? prev
        : [...prev, { userId, hourType }],
    );
  const removeLine = (userId: number, hourType: number) => {
    setExtraLines((prev) =>
      prev.filter((l) => !(l.userId === userId && l.hourType === hourType)),
    );
    setHours((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next)) {
        const k = splitKey(key);
        if (k.userId === userId && k.hourType === hourType) delete next[key];
      }
      return next;
    });
  };

  // ---- past days: history, worked hours own them -----------------------
  const [pastUnlocked, setPastUnlocked] = useState(false);
  const [pastReason, setPastReason] = useState("");
  const [pastPromptOpen, setPastPromptOpen] = useState(false);
  const [addedThisSession, setAddedThisSession] = useState<number[]>([]);
  const isFrozen = (userId: number, day: string) =>
    isPastDay(day) && (!pastUnlocked || addedThisSession.includes(userId));

  const handleAssign = (userIds: number[]) => {
    if (userIds.length === 0) return;
    setAddedThisSession((prev) => [...prev, ...userIds.filter((id) => !prev.includes(id))]);
    onAssign(userIds);
  };
  const handleAssignManagers = (userIds: number[]) => {
    if (!onAssignManagers || userIds.length === 0) return;
    setAddedThisSession((prev) => [...prev, ...userIds.filter((id) => !prev.includes(id))]);
    onAssignManagers(userIds);
  };

  // P-7 S2.1 — taking someone off, from the X. Adding is written the
  // moment it happens (the crew lives server-side), so a removal is
  // always a removal of a PERSISTED assignment: it asks once, in one
  // sentence that says what goes (the open plan) and what stays (the
  // past), then runs the page's EXISTING unassign. A native <dialog>,
  // rendered unconditionally and driven through the ref (CLAUDE.md).
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);
  const [pendingRemove, setPendingRemove] = useState<{
    userId: number;
    name: string;
    role: "WORKER" | "MANAGER";
  } | null>(null);
  const askRemove = (a: ExtraWorkAssignment) => {
    setPendingRemove({
      userId: a.user_id,
      name: personName(a),
      role: a.role === "MANAGER" ? "MANAGER" : "WORKER",
    });
    removeDialogRef.current?.open();
  };
  const confirmRemove = () => {
    if (!pendingRemove) return;
    const { userId, role } = pendingRemove;
    removeDialogRef.current?.close();
    setPendingRemove(null);
    // Their typed, unsaved cells go with them, so a later Save cannot
    // post hours for a person who is no longer on the crew.
    setHours((prev) => {
      const next: Record<string, string> = {};
      for (const [key, value] of Object.entries(prev)) {
        if (splitKey(key).userId !== userId) next[key] = value;
      }
      return next;
    });
    setChosen((prev) => {
      const next: Record<string, boolean> = {};
      for (const key of Object.keys(prev)) {
        if (Number(key.split("|")[0]) !== userId) next[key] = true;
      }
      return next;
    });
    if (role === "MANAGER") onRemoveManager?.(userId);
    else onRemovePerson?.(userId);
  };

  // ---- the day chips ----------------------------------------------------
  const isChosen = (userId: number, day: string) => Boolean(chosen[`${userId}|${day}`]);
  const chooseDay = (userId: number, day: string) => {
    setChosen((prev) => ({ ...prev, [`${userId}|${day}`]: true }));
  };
  const unchooseDay = (userId: number, day: string) => {
    setChosen((prev) => {
      const next = { ...prev };
      delete next[`${userId}|${day}`];
      return next;
    });
    setHours((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next)) {
        const k = splitKey(key);
        if (k.userId === userId && k.day === day) delete next[key];
      }
      return next;
    });
  };

  /** Days a person has hours on that are NOT between first and last
   *  work day — kept from an earlier plan. Shown, never hidden, never
   *  counted silently. */
  const outsideDaysFor = (userId: number): string[] => {
    const inWindow = new Set(days);
    const out = new Set<string>();
    for (const key of Object.keys(hours)) {
      const k = splitKey(key);
      if (k.userId !== userId || k.day === "" || inWindow.has(k.day)) continue;
      if ((hours[key] ?? "").trim() === "") continue;
      out.add(k.day);
    }
    return Array.from(out).sort();
  };
  const removeOutsideDay = (userId: number, day: string) => unchooseDay(userId, day);

  // ---- moving the plan --------------------------------------------------
  const [moveBaseline, setMoveBaseline] = useState(seededStart);
  const [moveDecision, setMoveDecision] = useState<"moved" | "kept" | null>(null);
  const crewIds = useMemo(() => new Set(crew.map((a) => a.user_id)), [crew]);
  const datedKeys = useMemo(
    () =>
      Object.keys(hours).filter((key) => {
        const k = splitKey(key);
        return k.day !== "" && crewIds.has(k.userId) && (hours[key] ?? "").trim() !== "";
      }),
    [hours, crewIds],
  );
  const moveDelta = moveBaseline && start ? daysBetweenIso(moveBaseline, start) : 0;
  const moveQuestionOpen = moveDelta !== 0 && datedKeys.length > 0 && moveDecision === null;

  const moveDaysAlong = () => {
    let touchesPast = false;
    setHours((prev) => {
      const next: Record<string, string> = {};
      for (const [key, value] of Object.entries(prev)) {
        const k = splitKey(key);
        if (k.day === "" || !crewIds.has(k.userId)) {
          next[key] = value;
          continue;
        }
        const moved = shiftDay(k.day, moveDelta);
        if (isPastDay(k.day) || isPastDay(moved)) touchesPast = true;
        next[cellKey(k.userId, moved, k.hourType)] = value;
      }
      return next;
    });
    setChosen((prev) => {
      const next: Record<string, boolean> = {};
      for (const key of Object.keys(prev)) {
        const [rawUser, day] = key.split("|");
        if (!crewIds.has(Number(rawUser))) {
          next[key] = true;
          continue;
        }
        next[`${rawUser}|${shiftDay(day, moveDelta)}`] = true;
      }
      return next;
    });
    // The last work day is the person's own field: it is never shifted.
    // (Replayed on crmtest: shifting it by the stored delta dragged a
    // freshly typed end date into July.)
    setMoveBaseline(start);
    setMoveDecision("moved");
    if (touchesPast && !pastUnlocked) setPastPromptOpen(true);
  };
  const keepOldDays = () => {
    setMoveBaseline(start);
    setMoveDecision("kept");
  };
  // A further change of the first day re-asks relative to the new baseline.
  const onStartChange = (value: string) => {
    setStart(value);
    if (moveDecision !== null && value !== moveBaseline) setMoveDecision(null);
  };

  // ---- totals: only what is on screen ------------------------------------
  const inWindow = useMemo(() => new Set(days), [days]);
  const countsKey = (key: string): boolean => {
    const k = splitKey(key);
    if (!crewIds.has(k.userId)) return false;
    if (k.day === "") return true;
    if (inWindow.has(k.day)) return isChosen(k.userId, k.day);
    // Outside the plan: counted only while it is SHOWN as an outside chip.
    return (hours[key] ?? "").trim() !== "";
  };
  const personTotal = (userId: number) =>
    Object.keys(hours).reduce(
      (sum, key) =>
        splitKey(key).userId === userId && countsKey(key) ? sum + toHours(hours[key] ?? "") : sum,
      0,
    );
  const distributed = Object.keys(hours).reduce(
    (sum, key) => (countsKey(key) ? sum + toHours(hours[key] ?? "") : sum),
    0,
  );
  const budgetHours = toHours(budget);
  const hasBudget = budget.trim() !== "";
  const overrun = hasBudget && distributed > budgetHours;
  const overBy = (distributed - budgetHours).toFixed(2);
  const fmtHours = (n: number) => n.toFixed(2).replace(".", locale.startsWith("nl") ? "," : ".");

  // ---- stage 3: done means ------------------------------------------------
  const [photoRequired, setPhotoRequired] = useState(ew.file_upload_required ?? false);
  const [notesRequired, setNotesRequired] = useState(ew.completion_notes_required ?? false);
  const [photoTouched, setPhotoTouched] = useState(false);
  const [notesTouched, setNotesTouched] = useState(false);

  // ---- errors live where the person is -------------------------------------
  const [clientErrors, setClientErrors] = useState<Partial<Record<FieldKey, string>>>({});
  /** Each field container carries `data-plan-field`; the first error is
   *  scrolled to by looking it up in the dialog — no refs read during
   *  render. */
  const bind = (key: FieldKey) => ({ "data-plan-field": key });

  /** The server's refusal, read for its field detail. */
  const serverErrors = useMemo((): {
    fields: Partial<Record<FieldKey, string>>;
    summary: string;
    pastDays: string[];
  } => {
    const empty = { fields: {}, summary: "", pastDays: [] as string[] };
    if (!rawError) return { ...empty, summary: error };
    const d = readApiErrorDetail(rawError);
    const fields: Partial<Record<FieldKey, string>> = {};
    let pastDays: string[] = [];
    const dayList = d.days.map((day) => formatDate(day)).join(", ");
    switch (d.code) {
      case "provider_planned_end_before_start":
        fields.end = t("plan.err_end_before_start");
        break;
      case "provider_planned_end_without_start":
        fields.start = t("plan.err_start_required");
        break;
      case "plan_past_day_locked":
        fields.past = t("plan.err_past_locked", { days: dayList });
        pastDays = d.days;
        break;
      case "planned_hours_outside_window":
        fields.hours = t("plan.err_outside_window", { days: dayList });
        break;
      case "planned_hours_invalid":
      case "planned_hours_duplicate_user":
      case "planned_hours_hour_type_invalid":
        fields.hours = t("plan.err_hours_rejected");
        break;
      default:
        break;
    }
    for (const name of Object.keys(d.fields)) {
      if (name === "provider_planned_date") fields.start ??= t("plan.err_field_rejected");
      else if (name === "provider_planned_end_date") fields.end ??= t("plan.err_field_rejected");
      else if (name === "budget_hours") fields.budget ??= t("plan.err_field_rejected");
      else if (name === "planned_hours") fields.hours ??= t("plan.err_hours_rejected");
    }
    const hasField = Object.keys(fields).length > 0;
    return {
      fields,
      // The generic sentence ONLY when the server gave no field detail.
      summary: hasField ? t("plan.summary_fix_marked", { count: Object.keys(fields).length }) : error,
      pastDays,
    };
  }, [rawError, error, t]);

  // P-7 S2.2 — the last day before the first is refused AT the field
  // the moment it happens, not at Save. Derived from the two values,
  // so it appears and disappears with the typing.
  const endBeforeStart = end !== "" && start !== "" && end < start;
  const fieldError = (key: FieldKey): string | undefined =>
    clientErrors[key] ??
    serverErrors.fields[key] ??
    (key === "end" && endBeforeStart ? t("plan.err_end_before_start") : undefined);

  // A past-day refusal opens the unlock prompt where the reason goes —
  // derived, not synced: the prompt is open while the server says so
  // and the person has neither unlocked nor dismissed THAT refusal.
  const [dismissedPastError, setDismissedPastError] = useState<unknown>(null);
  const promptOpen =
    pastPromptOpen ||
    (serverErrors.pastDays.length > 0 && !pastUnlocked && dismissedPastError !== rawError);

  // The first error scrolls into view. Client errors scroll from
  // `submit()` itself; a server refusal scrolls when it arrives. The
  // latest field map is read through a ref so the effect depends on
  // the refusal alone.
  useEffect(() => {
    if (!rawError) return;
    scrollToFirstField(serverErrors.fields);
  }, [rawError, serverErrors]);

  const submitStarts = !postSpawn && ew.status === "CUSTOMER_APPROVED";
  // P-7 S2.3 — one thing at a time, on the one page: the dates first;
  // the people and hours appear once a first day exists (or once
  // someone is already on the crew, or the caller pointed at that
  // stage); "done means" appears once someone is on the crew. Nothing
  // moves or resets — a stage only reveals, never hides again.
  const stageWhoOpen =
    start !== "" ||
    assignments.length > 0 ||
    initialFocus === "people" ||
    initialFocus === "manager" ||
    initialFocus === "hours";
  const stageDoneOpen = stageWhoOpen && (workers.length > 0 || photoTouched || notesTouched);
  const startAfterDeadline = Boolean(start && ew.deadline && start > ew.deadline);
  const endAfterDeadline = Boolean(end && ew.deadline && end > ew.deadline);

  function submit() {
    const errors: Partial<Record<FieldKey, string>> = {};
    if (start === "") errors.start = t("plan.err_start_required");
    if (end !== "" && start !== "" && end < start) errors.end = t("plan.err_end_before_start");
    if (workers.length === 0) errors.people = t("plan.err_people_required");
    if (moveQuestionOpen) errors.move = t("plan.err_move_undecided");
    if (promptOpen && !pastUnlocked) errors.past = t("plan.err_past_reason_required");
    setClientErrors(errors);
    if (Object.keys(errors).length > 0) {
      scrollToFirstField(errors);
      return;
    }
    const payload: ExtraWorkPlanPayload = {};
    if (budget.trim() !== "") payload.budget_hours = budget.trim();
    payload.provider_planned_date = start;
    payload.provider_planned_end_date = end !== "" ? end : start;
    if (assignments.length > 0) {
      const cells: { user: number; date?: string | null; hour_type?: number | null; hours: string }[] = [];
      for (const a of assignments) {
        let any = false;
        for (const key of Object.keys(hours)) {
          const k = splitKey(key);
          if (k.userId !== a.user_id) continue;
          if (!countsKey(key) && k.day !== "") continue;
          const raw = (hours[key] ?? "").trim();
          if (raw === "") continue;
          cells.push({
            user: a.user_id,
            date: k.day === "" ? null : k.day,
            hour_type: k.hourType,
            hours: raw.replace(",", "."),
          });
          any = true;
        }
        // On the crew with nothing anywhere: one undated ordinary zero
        // row, the state the plan has always used for "on the job, no
        // hours yet".
        if (!any) cells.push({ user: a.user_id, date: null, hour_type: null, hours: "0" });
      }
      payload.planned_hours = cells;
    }
    if (photoTouched) payload.file_upload_required = photoRequired;
    if (notesTouched) payload.completion_notes_required = notesRequired;
    if (pastUnlocked && pastReason.trim() !== "") {
      (payload as ExtraWorkPlanPayload & { past_days_override_reason?: string }).past_days_override_reason =
        pastReason.trim();
    }
    onSubmit(payload);
  }

  const summaryLine =
    Object.values(clientErrors).find(Boolean) ??
    (Object.keys(serverErrors.fields).length > 0 ? serverErrors.summary : error);

  const dayChipLabel = (day: string) =>
    parseDay(day).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });

  // ---- render --------------------------------------------------------------
  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t(postSpawn ? "plan.dialog_title_planned" : "plan.dialog_title")}
      data-testid="extra-work-plan-dialog"
    >
      <div className="card ew-plan-dialog ew-plan-dialog--framed ew-plan-dialog--guided">
        <div className="ew-plan-head">
          <h3 className="section-title ew-plan-dialog-title">
            {t(postSpawn ? "plan.dialog_title_planned" : "plan.dialog_title")}
          </h3>
          <p className="muted small ew-plan-dialog-sub">{t("plan.dialog_subtitle")}</p>
        </div>

        <div className="ew-plan-body" data-testid="extra-work-plan-body">
          {/* ---- 1. WHEN ---- */}
          <div className="ew-plan-section" data-testid="extra-work-plan-stage-when">
            <div className="ew-plan-section-title">
              <span className="ew-plan-step">1</span>
              {t("plan.stage_when")}
            </div>
            <div className="ew-plan-dates">
              <label className="field" {...bind("start")}>
                <span className="field-label">{t("plan.first_day_label")}</span>
                <input
                  type="date"
                  className={`field-input${fieldError("start") ? " field-input-invalid" : ""}`}
                  value={start}
                  onChange={(e) => onStartChange(e.target.value)}
                  aria-invalid={Boolean(fieldError("start"))}
                  data-testid="extra-work-plan-start"
                />
                {fieldError("start") && (
                  <span className="field-error" role="alert" data-testid="extra-work-plan-start-error">
                    {fieldError("start")}
                  </span>
                )}
                {!fieldError("start") && startAfterDeadline && (
                  <span
                    className="field-warning"
                    role="status"
                    data-testid="extra-work-plan-start-after-deadline"
                  >
                    {t("plan.after_deadline_inline", { date: formatDate(ew.deadline ?? "") })}
                  </span>
                )}
              </label>
              <label className="field" {...bind("end")}>
                <span className="field-label">{t("plan.last_day_label")}</span>
                <input
                  type="date"
                  className={`field-input${fieldError("end") ? " field-input-invalid" : ""}`}
                  value={end}
                  min={start || undefined}
                  onChange={(e) => setEnd(e.target.value)}
                  aria-invalid={Boolean(fieldError("end"))}
                  data-testid="extra-work-plan-end"
                />
                <span className="muted small">{t("plan.last_day_hint")}</span>
                {fieldError("end") && (
                  <span className="field-error" role="alert" data-testid="extra-work-plan-end-error">
                    {fieldError("end")}
                  </span>
                )}
                {!fieldError("end") && endAfterDeadline && (
                  <span
                    className="field-warning"
                    role="status"
                    data-testid="extra-work-plan-end-after-deadline"
                  >
                    {t("plan.after_deadline_inline", { date: formatDate(ew.deadline ?? "") })}
                  </span>
                )}
              </label>
            </div>
            {(ew.preferred_date || ew.deadline) && (
              <p className="ew-plan-customer-strip" data-testid="extra-work-plan-customer-dates">
                {[
                  ew.preferred_date &&
                    t("plan.customer_would_like", { date: formatDate(ew.preferred_date) }),
                  ew.deadline && t("plan.must_be_done_by", { date: formatDate(ew.deadline) }),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
            {moveQuestionOpen && (
              <div
                className="ew-plan-question"
                {...bind("move")}
                role="group"
                data-testid="extra-work-plan-move-question"
              >
                <p className="ew-plan-question-text">
                  {t("plan.move_question", {
                    from: formatDate(moveBaseline),
                    to: formatDate(start),
                    count: Math.abs(moveDelta),
                  })}
                </p>
                <div className="ew-plan-question-actions">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={moveDaysAlong}
                    data-testid="extra-work-plan-move-yes"
                  >
                    {t("plan.move_yes")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={keepOldDays}
                    data-testid="extra-work-plan-move-no"
                  >
                    {t("plan.move_no")}
                  </button>
                </div>
                {fieldError("move") && (
                  <span className="field-error" role="alert">
                    {fieldError("move")}
                  </span>
                )}
              </div>
            )}
            {moveDecision === "kept" && datedKeys.some((key) => !inWindow.has(splitKey(key).day)) && (
              <p className="field-warning" role="status" data-testid="extra-work-plan-move-kept">
                {t("plan.move_kept_warning")}
              </p>
            )}
          </div>

          {/* ---- 2. WHO AND HOW MUCH ---- */}
          <div className="ew-plan-section" data-testid="extra-work-plan-stage-who">
            <div className="ew-plan-section-title">
              <span className="ew-plan-step">2</span>
              {t("plan.stage_who")}
            </div>
            {!stageWhoOpen && (
              <p className="muted small ew-plan-section-waiting" data-testid="extra-work-plan-stage-who-waiting">
                {t("plan.stage_who_waiting")}
              </p>
            )}
            {stageWhoOpen && (<>

            <div className="ew-plan-crew" data-testid="extra-work-plan-crew">
              <div className="ew-plan-crew-group" data-testid="extra-work-plan-people" {...bind("people")}>
                <span className="field-label">{t("plan.people_label")}</span>
                {focusNotice("people")}
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
                          onClick={() => askRemove(a)}
                          aria-label={t("plan.person_remove", { name: personName(a) })}
                          data-testid="extra-work-plan-person-remove"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      )}
                    </span>
                  ))}
                  {workers.length === 0 && (
                    <span className="muted small" data-testid="extra-work-plan-people-none">
                      {t("plan.people_none")}
                    </span>
                  )}
                </div>
                {fieldError("people") && (
                  <span className="field-error" role="alert" data-testid="extra-work-plan-people-error">
                    {fieldError("people")}
                  </span>
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

              <div className="ew-plan-crew-group" data-testid="extra-work-plan-manager" {...bind("manager")}>
                <span className="field-label">{t("plan.manager_label")}</span>
                {focusNotice("manager")}
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
                          onClick={() => askRemove(a)}
                          aria-label={t("plan.manager_remove", { name: personName(a) })}
                          data-testid="extra-work-plan-manager-remove"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      )}
                    </span>
                  ))}
                  {managers.length === 0 && (
                    <span className="muted small" data-testid="extra-work-plan-manager-none">
                      {t("plan.manager_none")}
                    </span>
                  )}
                </div>
                <span className="muted small">{t("plan.manager_hint")}</span>
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
            ) : crew.length === 0 ? (
              <div className="ew-plan-empty" data-testid="extra-work-plan-no-crew">
                <Users size={18} aria-hidden="true" />
                <div>
                  <div className="ew-plan-empty-title">{t("plan.no_crew_title")}</div>
                  <div className="muted small">{t("plan.no_crew_hint")}</div>
                </div>
              </div>
            ) : (
              <div className="ew-plan-people" {...bind("hours")} data-testid="extra-work-plan-hours">
                {fieldError("hours") && (
                  <p className="field-error" role="alert" data-testid="extra-work-plan-hours-error">
                    {fieldError("hours")}
                  </p>
                )}
                {days.some(isPastDay) && (
                  <div className="ew-plan-past-bar" {...bind("past")} data-testid="extra-work-plan-past-bar">
                    {pastUnlocked ? (
                      <span className="muted small" data-testid="extra-work-plan-past-unlocked">
                        {t("plan.unlock_past_active")}
                      </span>
                    ) : promptOpen ? (
                      <div className="ew-plan-past-prompt">
                        <textarea
                          className="field-textarea"
                          rows={2}
                          autoFocus
                          value={pastReason}
                          onChange={(e) => setPastReason(e.target.value)}
                          placeholder={t("plan.unlock_past_reason_placeholder")}
                          aria-label={t("plan.unlock_past_reason_placeholder")}
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
                            setDismissedPastError(rawError ?? null);
                            setPastReason("");
                          }}
                          data-testid="extra-work-plan-past-unlock-cancel"
                        >
                          {t("plan.unlock_past_cancel")}
                        </button>
                      </div>
                    ) : (
                      <>
                        <span className="muted small">{t("plan.past_days_note")}</span>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => setPastPromptOpen(true)}
                          title={t("plan.past_locked_tooltip")}
                          data-testid="extra-work-plan-past-unlock"
                        >
                          <Lock size={13} aria-hidden="true" />
                          <span style={{ marginLeft: 6 }}>{t("plan.unlock_past")}</span>
                        </button>
                      </>
                    )}
                    {fieldError("past") && (
                      <span className="field-error" role="alert" data-testid="extra-work-plan-past-error">
                        {fieldError("past")}
                      </span>
                    )}
                  </div>
                )}

                {focusNotice("hours")}
                {crew.map((a) => {
                  const lines = linesFor(a.user_id);
                  const used = new Set(lines.map((l) => l.hourType).filter((id): id is number => id !== null));
                  const addable = hourTypes.filter((h) => !used.has(h.id));
                  const chosenDays = days.filter((day) => isChosen(a.user_id, day));
                  const outside = outsideDaysFor(a.user_id);
                  return (
                    <div
                      key={a.id}
                      className="ew-plan-person"
                      data-testid="extra-work-plan-crew-row"
                      data-user-id={a.user_id}
                    >
                      <div className="ew-plan-person-head">
                        <strong>
                          {personName(a)}
                          {a.role === "MANAGER" && (
                            <span className="ew-plan-person-tag">{t("plan.manager_tag")}</span>
                          )}
                        </strong>
                        <span
                          className={`ew-plan-person-total${committedClass}`}
                          data-testid="extra-work-plan-row-total"
                        >
                          {t("plan.person_total", { hours: fmtHours(personTotal(a.user_id)) })}
                          {committedAt > 0 && (
                            <span className="ew-plan-committed-word">{t("plan.hours_committed")}</span>
                          )}
                        </span>
                        {/* P-5 S2.1 — removable AFTER add, from the row itself. */}
                        {(a.role === "MANAGER" ? onRemoveManager : onRemovePerson) && (
                          <button
                            type="button"
                            className="ew-plan-type-remove"
                            disabled={removeBusy || assignBusy || managerBusy}
                            onClick={() => askRemove(a)}
                            aria-label={t(
                              a.role === "MANAGER" ? "plan.manager_remove" : "plan.person_remove",
                              { name: personName(a) },
                            )}
                            data-testid="extra-work-plan-row-remove"
                          >
                            <X size={12} aria-hidden="true" />
                          </button>
                        )}
                      </div>

                      {days.length === 0 ? (
                        <p className="muted small" data-testid="extra-work-plan-no-window">
                          {t("plan.pick_first_day_hint")}
                        </p>
                      ) : (
                        <div className="ew-plan-day-chips" role="group" aria-label={t("plan.days_label")}>
                          <span className="muted small ew-plan-day-chips-label">{t("plan.days_label")}</span>
                          {days.map((day) => {
                            const on = isChosen(a.user_id, day);
                            const locked = isPastDay(day) && !on && isFrozen(a.user_id, day);
                            return (
                              <button
                                key={day}
                                type="button"
                                className={`ew-plan-day-chip${on ? " is-on" : ""}${locked ? " is-locked" : ""}`}
                                aria-pressed={on}
                                disabled={locked}
                                title={locked ? t("plan.past_locked_tooltip") : undefined}
                                onClick={() => (on ? unchooseDay(a.user_id, day) : chooseDay(a.user_id, day))}
                                data-testid="extra-work-plan-day-chip"
                                data-day={day}
                                data-on={on ? "true" : "false"}
                              >
                                {locked && <Lock size={10} aria-hidden="true" className="ew-plan-past-lock" />}
                                {dayChipLabel(day)}
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {lines.map((line) => (
                        <div
                          key={`${line.userId}|${line.hourType ?? ""}`}
                          className="ew-plan-hours-line"
                          data-testid="extra-work-plan-hours-line"
                          data-hour-type={line.hourType ?? ""}
                        >
                          {lines.length > 1 && (
                            <span className="ew-plan-hours-line-type">
                              {hourTypeName(line.hourType)}
                              {line.hourType !== null && (
                                <button
                                  type="button"
                                  className="ew-plan-type-remove"
                                  onClick={() => line.hourType !== null && removeLine(a.user_id, line.hourType)}
                                  aria-label={t("plan.remove_hour_type", { type: hourTypeName(line.hourType) })}
                                  data-testid="extra-work-plan-remove-hour-type"
                                >
                                  <X size={13} aria-hidden="true" />
                                </button>
                              )}
                            </span>
                          )}
                          {chosenDays.map((day) => {
                            const key = cellKey(a.user_id, day, line.hourType);
                            const frozen = isFrozen(a.user_id, day);
                            return (
                              <label key={day} className="ew-plan-hours-box">
                                <span className="muted small">{dayChipLabel(day)}</span>
                                {frozen ? (
                                  <span
                                    className="ew-plan-cell-frozen"
                                    title={t("plan.past_locked_tooltip")}
                                    data-testid="extra-work-plan-frozen-cell"
                                    data-day={day}
                                  >
                                    {hours[key] ?? "—"}
                                  </span>
                                ) : (
                                  <input
                                    type="number"
                                    min="0"
                                    step="0.25"
                                    inputMode="decimal"
                                    className="field-input ew-plan-crew-hours"
                                    value={hours[key] ?? ""}
                                    onChange={(e) => setHours((prev) => ({ ...prev, [key]: e.target.value }))}
                                    onBlur={() => commitHours(key)}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        commitHours(key);
                                      }
                                    }}
                                    aria-label={`${t("plan.hours_for", { name: personName(a) })} ${hourTypeName(line.hourType)} ${dayChipLabel(day)}`}
                                    data-testid="extra-work-plan-crew-hours"
                                    data-day={day}
                                    data-hour-type={line.hourType ?? ""}
                                  />
                                )}
                                <span className="muted small">{t("plan.hours_unit")}</span>
                              </label>
                            );
                          })}
                          <label className="ew-plan-hours-box ew-plan-hours-box--undated">
                            <span className="muted small">{t("plan.no_day_yet")}</span>
                            <input
                              type="number"
                              min="0"
                              step="0.25"
                              inputMode="decimal"
                              className="field-input ew-plan-crew-hours"
                              value={hours[cellKey(a.user_id, "", line.hourType)] ?? ""}
                              onChange={(e) =>
                                setHours((prev) => ({ ...prev, [cellKey(a.user_id, "", line.hourType)]: e.target.value }))
                              }
                              onBlur={() => commitHours(cellKey(a.user_id, "", line.hourType))}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  commitHours(cellKey(a.user_id, "", line.hourType));
                                }
                              }}
                              aria-label={`${t("plan.hours_for", { name: personName(a) })} ${hourTypeName(line.hourType)} ${t("plan.no_day_yet")}`}
                              data-testid="extra-work-plan-crew-hours"
                              data-day=""
                              data-hour-type={line.hourType ?? ""}
                            />
                            <span className="muted small">{t("plan.hours_unit")}</span>
                          </label>
                        </div>
                      ))}

                      {outside.length > 0 && (
                        <div className="ew-plan-outside" data-testid="extra-work-plan-outside">
                          <span className="muted small">{t("plan.outside_label")}</span>
                          {outside.map((day) => {
                            const total = lines.reduce(
                              (sum, line) => sum + toHours(hours[cellKey(a.user_id, day, line.hourType)] ?? ""),
                              0,
                            );
                            return (
                              <span key={day} className="ew-plan-outside-chip" data-day={day}>
                                {dayChipLabel(day)} · {fmtHours(total)} {t("plan.hours_unit")}
                                {!isFrozen(a.user_id, day) && (
                                  <button
                                    type="button"
                                    className="ew-plan-type-remove"
                                    onClick={() => removeOutsideDay(a.user_id, day)}
                                    aria-label={t("plan.outside_remove", { day: dayChipLabel(day) })}
                                    data-testid="extra-work-plan-outside-remove"
                                  >
                                    <X size={12} aria-hidden="true" />
                                  </button>
                                )}
                              </span>
                            );
                          })}
                        </div>
                      )}

                      {addable.length > 0 && (
                        <select
                          className="ew-plan-add-type"
                          value=""
                          onChange={(e) => {
                            if (e.target.value === "") return;
                            addLine(a.user_id, Number(e.target.value));
                          }}
                          aria-label={t("plan.add_hour_type", { name: personName(a) })}
                          data-testid="extra-work-plan-add-hour-type"
                        >
                          <option value="">{t("plan.add_hour_type_placeholder")}</option>
                          {addable.map((h) => (
                            <option key={h.id} value={h.id}>
                              {h.name}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  );
                })}

                <div className="ew-plan-total" data-testid="extra-work-plan-total-line">
                  <span>{t("plan.grand_total_label")}</span>
                  <strong data-testid="extra-work-plan-total" className={committedClass.trim()}>
                    {t("plan.hours_value", { hours: fmtHours(distributed) })}
                  </strong>
                </div>

                <label className="field ew-plan-budget" {...bind("budget")}>
                  <span className="muted small">{t("plan.budget_optional_label")}</span>
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
                  {fieldError("budget") && (
                    <span className="field-error" role="alert">
                      {fieldError("budget")}
                    </span>
                  )}
                </label>
                {overrun && (
                  <div className="ew-plan-overrun" role="status" data-testid="extra-work-plan-overrun">
                    <AlertTriangle size={18} aria-hidden="true" />
                    <div>
                      <div className="ew-plan-overrun-title">{t("plan.overrun_title", { over: overBy })}</div>
                      <div className="muted small">
                        {t("plan.overrun_hint", {
                          distributed: distributed.toFixed(2),
                          budget: budgetHours.toFixed(2),
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
            </>)}
          </div>

          {/* ---- 3. DONE MEANS ---- */}
          <div className="ew-plan-section" data-testid="extra-work-plan-stage-done">
            <div className="ew-plan-section-title">
              <span className="ew-plan-step">3</span>
              {t("plan.stage_done")}
            </div>
            {!stageDoneOpen && (
              <p className="muted small ew-plan-section-waiting" data-testid="extra-work-plan-stage-done-waiting">
                {t("plan.stage_done_waiting")}
              </p>
            )}
            {stageDoneOpen && (<>
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
            </>)}
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
            {summaryLine && (
              <p className="form-error ew-plan-summary-error" role="alert" data-testid="extra-work-plan-required">
                {summaryLine}
              </p>
            )}
            <button
              type="button"
              className="btn btn-primary"
              /* `busy` only. NOT `overrun`. */
              disabled={busy}
              onClick={submit}
              data-testid="extra-work-plan-submit"
            >
              {busy ? t("plan.submitting") : t(submitStarts ? "plan.submit" : "plan.submit_save")}
            </button>
          </div>
        </div>
        <ConfirmDialog
          ref={removeDialogRef}
          title={t("plan.remove_title", { name: pendingRemove?.name ?? "" })}
          body={t(
            pendingRemove?.role === "MANAGER" ? "plan.remove_manager_body" : "plan.remove_body",
            { name: pendingRemove?.name ?? "" },
          )}
          confirmLabel={t("plan.remove_confirm")}
          busy={removeBusy}
          onConfirm={confirmRemove}
          onCancel={() => setPendingRemove(null)}
        />
      </div>
    </div>
  );
}

/** The crew's adder: one line, several people, one Add. `candidates`
 *  arrives already filtered to the not-yet-assigned. */
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
