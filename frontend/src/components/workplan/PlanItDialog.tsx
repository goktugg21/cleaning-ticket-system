import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { WorkPlanEntry } from "../../api/workPlan";

/** What the operator chose in the Plan-it dialog. */
export interface PlanItChoice {
  /** "YYYY-MM-DD" */
  day: string;
  /** "HH:MM" or "" for a day without a time. */
  time: string;
  /** P-9 ruling 12(e) — everyone on the job moves with it (ticket only). */
  applyToSlots: boolean;
}

/**
 * P-9 §A.1 — "Plan it": the one button on a "Not planned yet" row opens
 * this, today pre-filled. A plain overlay (`.plan-modal-backdrop`, the
 * ticket schedule card's own shape) rather than a native <dialog>: it
 * is mounted only while open, so it can never be an invisible dialog
 * or an inert page (the Sprint 118/128 bugs).
 *
 * Keyed by the entry at the mount site, so the initial state is the
 * entry's — no effect resyncs it.
 */
export function PlanItDialog({
  entry,
  todayIso,
  busy,
  error,
  onCancel,
  onSave,
}: {
  entry: WorkPlanEntry;
  todayIso: string;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onSave: (choice: PlanItChoice) => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [day, setDay] = useState(todayIso);
  const [time, setTime] = useState("");
  const [applyToSlots, setApplyToSlots] = useState(true);
  const isTicket = entry.ticket_id !== null;
  const heading = entry.ticket_no ? `${entry.ticket_no} · ${entry.title}` : entry.title;

  return (
    <div
      className="plan-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="agenda-plan-it-dialog"
    >
      <div className="plan-modal">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (day) onSave({ day, time: time.trim(), applyToSlots });
          }}
        >
          <h3 className="plan-modal-title">{t("agenda.plan_it_title", { title: heading })}</h3>
          <div className="plan-modal-grid">
            <div className="field">
              <label className="field-label" htmlFor="agenda-plan-it-day">
                {t("agenda.plan_it_day")}
              </label>
              <input
                id="agenda-plan-it-day"
                className="field-input"
                type="date"
                value={day}
                onChange={(event) => setDay(event.target.value)}
                disabled={busy}
                required
                data-testid="agenda-plan-it-day"
              />
            </div>
            {isTicket && (
              <div className="field">
                <label className="field-label" htmlFor="agenda-plan-it-time">
                  {t("agenda.plan_it_time")}
                </label>
                <input
                  id="agenda-plan-it-time"
                  className="field-input"
                  type="time"
                  value={time}
                  onChange={(event) => setTime(event.target.value)}
                  disabled={busy}
                  data-testid="agenda-plan-it-time"
                />
              </div>
            )}
          </div>
          {isTicket && (
            <label className="wp-plan-check">
              <input
                type="checkbox"
                checked={applyToSlots}
                onChange={(event) => setApplyToSlots(event.target.checked)}
                disabled={busy}
                data-testid="agenda-plan-it-everyone"
              />
              {t("agenda.plan_it_everyone")}
            </label>
          )}
          {error && (
            <div className="alert-error" role="alert" data-testid="agenda-plan-it-error">
              {error}
            </div>
          )}
          <div className="plan-modal-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
              disabled={busy}
              data-testid="agenda-plan-it-cancel"
            >
              {t("common:cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy || !day}
              data-testid="agenda-plan-it-save"
            >
              {busy ? t("common:admin_form.saving") : t("agenda.plan_it_save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
