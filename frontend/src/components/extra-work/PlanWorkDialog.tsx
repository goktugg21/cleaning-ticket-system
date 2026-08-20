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
 */
import { useMemo, useState } from "react";

import { dayRange } from "../../lib/planGridDays";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Users } from "lucide-react";

import type {
  ExtraWorkAssignment,
  ExtraWorkPlanPayload,
  ExtraWorkRequestDetail,
} from "../../api/types";
import { Toggle } from "../Toggle";
import { formatDate } from "../../lib/intl";

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

export function PlanWorkDialog({
  ew,
  assignments,
  assignmentsLoading,
  busy,
  error,
  onCancel,
  onSubmit,
}: {
  ew: ExtraWorkRequestDetail;
  assignments: ExtraWorkAssignment[];
  assignmentsLoading: boolean;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onSubmit: (payload: ExtraWorkPlanPayload) => void;
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
  // as the day for "planned, day not decided". One flat map rather than
  // a nested one because every read here is a single cell and a flat
  // key makes an accidental whole-row overwrite unspellable.
  const cellKey = (userId: number, day: string) => `${userId}|${day}`;

  // Seeded from what is already planned, so reopening the dialog shows
  // the plan rather than a blank grid.
  const seeded = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of ew.planned_hours ?? []) {
      map.set(cellKey(row.user_id, row.date ?? ""), row.hours);
    }
    return map;
  }, [ew.planned_hours]);

  const [hours, setHours] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const [key, value] of seeded) initial[key] = value;
    return initial;
  });

  // THE COLUMNS ARE THE COMMITTED WINDOW the plan already stores. They
  // follow the two date fields above live, so moving the window
  // re-draws the grid without a save — which is the only way the two
  // controls can be understood as one decision.
  const days = useMemo(() => dayRange(start, end), [start, end]);

  // Every cell in the grid, plus every UNDATED cell, plus any cell on a
  // day that is no longer in the window. That last group matters: hours
  // planned for a Thursday that has since been dropped from the window
  // still exist server-side and still count, so hiding them from the
  // total would put the screen and the server at odds — the reference
  // system's §4.4 defect, one level down.
  const liveKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const a of assignments) {
      keys.add(cellKey(a.user_id, ""));
      for (const day of days) keys.add(cellKey(a.user_id, day));
    }
    for (const key of Object.keys(hours)) keys.add(key);
    return keys;
  }, [assignments, days, hours]);

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

  const dayTotal = (day: string) =>
    assignments.reduce(
      (sum, a) => sum + toHours(hours[cellKey(a.user_id, day)] ?? ""),
      0,
    );
  const budgetHours = toHours(budget);
  // A budget of zero is a real budget; only a BLANK one means "no budget
  // set", which is nothing to overrun. Same reading as the server's
  // `hours_overrun`, which returns None when `budget_hours` is null.
  const hasBudget = budget.trim() !== "";
  const overrun = hasBudget && distributed > budgetHours;
  const overBy = (distributed - budgetHours).toFixed(2);

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
      //
      // The person-level exception is deliberate: somebody on the crew
      // with nothing anywhere still gets one undated zero row, because
      // "on the job, no hours budgeted yet" is a state the plan has
      // always been able to express and losing it would drop them off
      // the screen entirely.
      const cells: { user: number; date?: string | null; hours: string }[] = [];
      for (const a of assignments) {
        let any = false;
        for (const key of liveKeys) {
          if (!key.startsWith(`${a.user_id}|`)) continue;
          const raw = (hours[key] ?? "").trim();
          if (raw === "") continue;
          const day = key.slice(key.indexOf("|") + 1);
          cells.push({
            user: a.user_id,
            date: day === "" ? null : day,
            hours: raw.replace(",", "."),
          });
          any = true;
        }
        if (!any) cells.push({ user: a.user_id, date: null, hours: "0" });
      }
      payload.planned_hours = cells;
    }
    if (photoTouched) payload.file_upload_required = photoRequired;
    if (notesTouched) payload.completion_notes_required = notesRequired;
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
      <div className="card ew-plan-dialog">
        <h3 className="section-title ew-plan-dialog-title">
          {t("plan.dialog_title")}
        </h3>
        <p className="muted small ew-plan-dialog-sub">
          {t("plan.dialog_subtitle")}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-plan-error"
          >
            {error}
          </div>
        )}

        <div className="ew-plan-section">
          <label className="field ew-plan-budget">
            <span className="muted small">{t("plan.budget_hours_label")}</span>
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

        {/* OUR dates, with the customer's shown beside them read-only.
            Two pairs of dates on one screen is exactly the confusion the
            labels have to prevent. */}
        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("plan.our_window_title")}
          </div>
          <p className="muted small ew-plan-section-hint">
            {t("plan.our_window_hint")}
          </p>
          <div className="ew-plan-dates">
            <label className="field">
              <span className="muted small">{t("plan.our_start_label")}</span>
              <input
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
        </div>

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">{t("plan.hours_title")}</div>
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
              <div className="table-wrap">
                <table className="data-table ew-plan-grid">
                  <thead>
                    <tr>
                      <th className="ew-plan-grid-name">
                        {t("plan.grid_person")}
                      </th>
                      <th className="ew-plan-grid-cell">
                        {t("plan.grid_no_day")}
                      </th>
                      {days.map((day) => (
                        <th key={day} className="ew-plan-grid-cell">
                          {formatDayHeader(day)}
                        </th>
                      ))}
                      <th className="ew-plan-grid-cell">
                        {t("plan.grid_row_total")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((a) => (
                      <tr
                        key={a.user_id}
                        data-testid="extra-work-plan-crew-row"
                        data-user-id={a.user_id}
                      >
                        <td className="ew-plan-grid-name">
                          {a.user_full_name || a.user_email}
                        </td>
                        {["", ...days].map((day) => (
                          <td key={day || "none"} className="ew-plan-grid-cell">
                            <input
                              type="number"
                              min="0"
                              step="0.25"
                              inputMode="decimal"
                              className="field-input ew-plan-crew-hours"
                              value={hours[cellKey(a.user_id, day)] ?? ""}
                              onChange={(e) =>
                                setHours((prev) => ({
                                  ...prev,
                                  [cellKey(a.user_id, day)]: e.target.value,
                                }))
                              }
                              aria-label={`${t("plan.hours_for", {
                                name: a.user_full_name || a.user_email,
                              })} ${day || t("plan.grid_no_day")}`}
                              data-testid="extra-work-plan-crew-hours"
                              data-day={day}
                            />
                          </td>
                        ))}
                        <td className="ew-plan-grid-cell">
                          <strong data-testid="extra-work-plan-row-total">
                            {personTotal(a.user_id).toFixed(2)}
                          </strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className="ew-plan-grid-name">
                        {t("plan.grid_day_total")}
                      </td>
                      <td className="ew-plan-grid-cell" />
                      {days.map((day) => (
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
              {days.length === 0 && (
                <p
                  className="muted small"
                  data-testid="extra-work-plan-no-window"
                >
                  {t("plan.grid_no_window")}
                </p>
              )}
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
            {busy ? t("plan.submitting") : t("plan.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
