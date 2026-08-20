/**
 * W3-F — plan a selection of works in one pass.
 *
 * WHAT THIS DIALOG IS, AND WHAT IT IS NOT
 * ---------------------------------------
 * `POST /api/extra-work/bulk-plan/` takes ONE plan payload and applies
 * it to every id in `requests`. It is not a grid of per-work values, and
 * this dialog does not pretend to be one: it collects one budget, one
 * committed window and one pair of completion flags, and states plainly
 * that they are written to every selected work. The table below the
 * fields lists the works that are about to receive them, because "6
 * selected" is not the same as knowing which six.
 *
 * The endpoint is all-or-nothing by design — one unresolvable id
 * rejects the whole batch with zero writes — so a partial result is not
 * a state this dialog has to render.
 *
 * PLANNED HOURS ARE DELIBERATELY ABSENT HERE. The distribution is
 * per-person and the server refuses hours for anybody not assigned to
 * EACH work in the batch, so one shared distribution is only ever valid
 * when the same crew is on every selected job. Offering the field would
 * produce a 400 that reads as a bug in the dialog. Hours are planned per
 * work, in the plan modal on the detail page.
 *
 * ABSENCE MEANS "LEAVE IT ALONE", and here that matters more than
 * anywhere else in the app. The payload is read by KEY PRESENCE, so a
 * blank budget leaves each work's own budget alone and the completion
 * switches are sent ONLY if somebody moved them. This is the exact
 * defect the backend was shaped to prevent: in the reference system a
 * bulk plan writes both flags to false on every selected work, and 0 of
 * their 78 live records carries either flag as a result.
 *
 * JSON, never FormData — the endpoint is pinned to `JSONParser` and
 * answers 415, because DRF reads an absent boolean out of form input as
 * `false`, which is the same wipe by another route.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExtraWorkPlanPayload, ExtraWorkRequestList } from "../../api/types";
import { Toggle } from "../Toggle";
import { BoundedList } from "../BoundedList";

export function BulkPlanDialog({
  rows,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  /** The selected works, resolved to rows so the operator can read what
   *  they picked without going back. */
  rows: ExtraWorkRequestList[];
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: (payload: ExtraWorkPlanPayload) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  const [budget, setBudget] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [photoRequired, setPhotoRequired] = useState(false);
  const [notesRequired, setNotesRequired] = useState(false);
  // ONE FLAG PER SWITCH, not one for the pair.
  //
  // Caught by measuring a real submit: with a single `flagsTouched`,
  // flipping "photo required" also sent `completion_notes_required:
  // false`. On the single-work dialog that is harmless because both
  // switches are seeded from the row, so the second value is a no-op
  // write of what was already there. HERE it is the reference system's
  // exact defect: these two start at false because the selected works
  // disagree, and there is nothing to seed from — so one flip would
  // clear the notes flag on every work in the batch, silently, which is
  // how 0 of their 78 live records ended up carrying either flag.
  const [photoTouched, setPhotoTouched] = useState(false);
  const [notesTouched, setNotesTouched] = useState(false);

  const nothingToSend =
    budget.trim() === "" &&
    start === "" &&
    end === "" &&
    !photoTouched &&
    !notesTouched;

  function submit() {
    const payload: ExtraWorkPlanPayload = {};
    if (budget.trim() !== "") payload.budget_hours = budget.trim();
    if (start !== "") payload.provider_planned_date = start;
    if (end !== "") payload.provider_planned_end_date = end;
    if (photoTouched) payload.file_upload_required = photoRequired;
    if (notesTouched) payload.completion_notes_required = notesRequired;
    onConfirm(payload);
  }

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("plan.bulk_title")}
      data-testid="extra-work-bulk-plan-dialog"
    >
      <div className="card ew-plan-dialog">
        <h3 className="section-title ew-plan-dialog-title">
          {t("plan.bulk_title")}
        </h3>
        {/* The one-line statement of what is about to happen to how
            many things. Never omit it. */}
        <p
          className="muted small ew-plan-dialog-sub"
          data-testid="extra-work-bulk-plan-summary"
        >
          {t("plan.bulk_summary", { count: rows.length })}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-bulk-plan-error"
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
              data-testid="extra-work-bulk-plan-budget"
            />
          </label>
        </div>

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
                data-testid="extra-work-bulk-plan-start"
              />
            </label>
            <label className="field">
              <span className="muted small">{t("plan.our_end_label")}</span>
              <input
                type="date"
                className="field-input"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                data-testid="extra-work-bulk-plan-end"
              />
            </label>
          </div>
        </div>

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
              data-testid="extra-work-bulk-plan-photo-required"
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
              data-testid="extra-work-bulk-plan-notes-required"
            />
            <span>{t("plan.notes_required_label")}</span>
          </label>
          {/* The rule that keeps a bulk edit from wiping what it never
              asked about, said out loud where somebody can act on it. */}
          <p className="muted small ew-plan-section-hint">
            {t("plan.bulk_untouched_hint")}
          </p>
        </div>

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("plan.bulk_targets_title")}
          </div>
          {/* Bounded — a selection can be the whole page of results,
              and CLAUDE.md's no-unbounded-server-list rule points at
              exactly this primitive. */}
          <BoundedList
            size="sm"
            count={rows.length}
            ariaLabel={t("plan.bulk_targets_title")}
            testIdPrefix="extra-work-bulk-plan-targets"
          >
            <ul className="ew-plan-bulk-targets">
              {rows.map((row) => (
                <li
                  key={row.id}
                  className="ew-plan-bulk-target"
                  data-testid="extra-work-bulk-plan-target"
                >
                  <span>{row.title}</span>
                  <span className="muted small">{row.building_name}</span>
                </li>
              ))}
            </ul>
          </BoundedList>
        </div>

        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid="extra-work-bulk-plan-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            /* Disabled ONLY when there is literally nothing to write —
               the endpoint rejects an empty plan. Never disabled for an
               overrun; that warning belongs to the per-work dialog and
               blocks nothing there either. */
            disabled={busy || nothingToSend}
            title={nothingToSend ? t("plan.bulk_nothing_to_send") : undefined}
            onClick={submit}
            data-testid="extra-work-bulk-plan-confirm"
          >
            {busy ? t("plan.submitting") : t("plan.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
