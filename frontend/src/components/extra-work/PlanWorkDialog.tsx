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

  // Seeded from what is already planned, keyed by user id, so reopening
  // the dialog shows the plan rather than a blank grid.
  const seeded = useMemo(() => {
    const map = new Map<number, string>();
    for (const row of ew.planned_hours ?? []) map.set(row.user_id, row.hours);
    return map;
  }, [ew.planned_hours]);

  const [hours, setHours] = useState<Record<number, string>>(() => {
    const initial: Record<number, string> = {};
    for (const a of assignments) initial[a.user_id] = seeded.get(a.user_id) ?? "";
    return initial;
  });

  const distributed = assignments.reduce(
    (sum, a) => sum + toHours(hours[a.user_id] ?? ""),
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
      payload.planned_hours = assignments.map((a) => ({
        user: a.user_id,
        // Zero is legal and means "on the crew, no hours budgeted yet".
        hours: (hours[a.user_id] ?? "").trim() === ""
          ? "0"
          : (hours[a.user_id] ?? "").trim().replace(",", "."),
      }));
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
              <ul className="ew-plan-crew">
                {assignments.map((a) => (
                  <li
                    key={a.user_id}
                    className="ew-plan-crew-row"
                    data-testid="extra-work-plan-crew-row"
                  >
                    <span className="ew-plan-crew-name">
                      {a.user_full_name || a.user_email}
                    </span>
                    <input
                      type="number"
                      min="0"
                      step="0.25"
                      inputMode="decimal"
                      className="field-input ew-plan-crew-hours"
                      value={hours[a.user_id] ?? ""}
                      onChange={(e) =>
                        setHours((prev) => ({
                          ...prev,
                          [a.user_id]: e.target.value,
                        }))
                      }
                      aria-label={t("plan.hours_for", {
                        name: a.user_full_name || a.user_email,
                      })}
                      data-testid="extra-work-plan-crew-hours"
                    />
                  </li>
                ))}
              </ul>
              <div className="ew-plan-total" data-testid="extra-work-plan-total">
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
