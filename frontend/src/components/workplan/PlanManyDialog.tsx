import { useState } from "react";
import { useTranslation } from "react-i18next";

import { setTicketSchedule } from "../../api/admin";
import { getApiError } from "../../api/client";
import type { WorkPlanEntry } from "../../api/workPlan";
import { planExtraWorkForDate } from "../../api/workPlan";
import { plannedDayIso } from "../../lib/isoWeek";
import { entryLabel } from "./entryHelpers";

/** What one Save did: how many rows landed, and which were refused. */
export interface PlanManyResult {
  planned: number;
  refused: { key: string; label: string; error: string }[];
}

interface RowDraft {
  day: string;
  time: string;
}

/**
 * P-10 A5 — SELECT → PLAN N. One dialog: a row per job (title, building,
 * a day input pre-filled with today, an optional time for tickets), the
 * 12(e) box ticked ONCE for all, one Save. Every row is written through
 * the same two doors the single "Plan it" uses (`POST /tickets/<id>/
 * schedule/`, `POST /extra-work/bulk-dates/`), one after another, so a
 * refusal (plan_past_day_locked, a forbidden role) lands on ITS row and
 * never aborts the others. Saved rows leave the dialog; refused rows
 * stay with their reason. The caller toasts once, after the reload, so
 * the strip count, the board and the toast agree in the same render (A6).
 *
 * A plain overlay (`.plan-modal-backdrop`), mounted only while open —
 * never an invisible <dialog> (Sprint 118/128).
 */
export function PlanManyDialog({
  entries,
  todayIso,
  onCancel,
  onSaved,
}: {
  entries: WorkPlanEntry[];
  todayIso: string;
  onCancel: () => void;
  /** Called once per Save with what happened; the dialog stays open
   *  while any row was refused. */
  onSaved: (result: PlanManyResult) => Promise<void> | void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [rows, setRows] = useState<WorkPlanEntry[]>(entries);
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>(() =>
    Object.fromEntries(entries.map((entry) => [entry.key, { day: todayIso, time: "" }])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [applyToSlots, setApplyToSlots] = useState(true);
  const [busy, setBusy] = useState(false);
  // P-11 A2 — one day for all, or a day each. "Same day" fills every
  // row from the shared pair; the rows stay visible and editable under
  // either mode (an edited row simply diverges), and one Save writes
  // whatever the rows hold.
  const [mode, setMode] = useState<"same" | "each">("same");
  const [shared, setShared] = useState<RowDraft>({ day: todayIso, time: "" });

  const setDraft = (key: string, patch: Partial<RowDraft>) =>
    setDrafts((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));

  const applyShared = (next: RowDraft) => {
    setShared(next);
    setDrafts((prev) =>
      Object.fromEntries(Object.keys(prev).map((key) => [key, { ...next }])),
    );
  };

  async function save() {
    if (busy) return;
    setBusy(true);
    const refused: { key: string; label: string; error: string }[] = [];
    const nextErrors: Record<string, string> = {};
    const saved = new Set<string>();
    for (const entry of rows) {
      const draft = drafts[entry.key] ?? { day: todayIso, time: "" };
      if (!draft.day) {
        nextErrors[entry.key] = t("agenda.plan_many_no_day");
        refused.push({ key: entry.key, label: entryLabel(entry), error: nextErrors[entry.key] });
        continue;
      }
      try {
        if (entry.ticket_id !== null) {
          await setTicketSchedule(entry.ticket_id, {
            // P-3 §A.3 — a DAY, not a moment, unless a time was chosen.
            scheduled_start_at: draft.time
              ? `${draft.day}T${draft.time}:00`
              : plannedDayIso(draft.day),
            apply_to_slots: applyToSlots,
          });
        } else if (entry.extra_work_id !== null) {
          await planExtraWorkForDate(entry.extra_work_id, draft.day);
        } else {
          continue;
        }
        saved.add(entry.key);
      } catch (err) {
        const message = getApiError(err);
        nextErrors[entry.key] = message;
        refused.push({ key: entry.key, label: entryLabel(entry), error: message });
      }
    }
    const remaining = rows.filter((entry) => !saved.has(entry.key));
    setRows(remaining);
    setErrors(nextErrors);
    setBusy(false);
    await onSaved({ planned: saved.size, refused });
  }

  return (
    <div
      className="plan-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="agenda-plan-many-dialog"
    >
      <div className="plan-modal plan-modal-wide">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <h3 className="plan-modal-title">{t("agenda.plan_many_title", { count: rows.length })}</h3>
          {/* P-11 A2 — the switch. */}
          <div className="composer-toggle" role="group" data-testid="agenda-plan-many-mode">
            <button
              type="button"
              className={`composer-toggle-btn ${mode === "same" ? "active" : ""}`}
              aria-pressed={mode === "same"}
              onClick={() => {
                setMode("same");
                applyShared(shared);
              }}
              disabled={busy}
              data-testid="agenda-plan-many-mode-same"
            >
              {t("agenda.plan_many_mode_same")}
            </button>
            <button
              type="button"
              className={`composer-toggle-btn ${mode === "each" ? "active" : ""}`}
              aria-pressed={mode === "each"}
              onClick={() => setMode("each")}
              disabled={busy}
              data-testid="agenda-plan-many-mode-each"
            >
              {t("agenda.plan_many_mode_each")}
            </button>
          </div>
          {mode === "same" && (
            <div className="wp-plan-many-shared" data-testid="agenda-plan-many-shared">
              <label className="field wp-plan-many-field">
                <span className="field-label">{t("agenda.plan_many_day")}</span>
                <input
                  className="field-input"
                  type="date"
                  value={shared.day}
                  onChange={(event) => applyShared({ ...shared, day: event.target.value })}
                  disabled={busy}
                  data-testid="agenda-plan-many-shared-day"
                />
              </label>
              {rows.some((entry) => entry.ticket_id !== null) && (
                <label className="field wp-plan-many-field">
                  <span className="field-label">{t("agenda.plan_many_time")}</span>
                  <input
                    className="field-input"
                    type="time"
                    value={shared.time}
                    onChange={(event) => applyShared({ ...shared, time: event.target.value })}
                    disabled={busy}
                    data-testid="agenda-plan-many-shared-time"
                  />
                </label>
              )}
            </div>
          )}
          <ul className="wp-plan-many" data-testid="agenda-plan-many-rows">
            {rows.map((entry) => {
              const draft = drafts[entry.key] ?? { day: todayIso, time: "" };
              const isTicket = entry.ticket_id !== null;
              const where = [entry.building_name, entry.customer_name].filter(Boolean).join(" · ");
              return (
                <li
                  key={entry.key}
                  className={`wp-plan-many-row${errors[entry.key] ? " wp-plan-many-row-refused" : ""}`}
                  data-testid={`agenda-plan-many-row-${entry.key}`}
                >
                  <div className="wp-plan-many-main">
                    <span className="wp-plan-many-title">{entryLabel(entry)}</span>
                    {where && <span className="muted small">{where}</span>}
                    {errors[entry.key] && (
                      <span
                        className="wp-plan-many-error"
                        role="alert"
                        data-testid={`agenda-plan-many-error-${entry.key}`}
                      >
                        {errors[entry.key]}
                      </span>
                    )}
                  </div>
                  <label className="field wp-plan-many-field">
                    <span className="field-label">{t("agenda.plan_many_day")}</span>
                    <input
                      className="field-input"
                      type="date"
                      value={draft.day}
                      onChange={(event) => setDraft(entry.key, { day: event.target.value })}
                      disabled={busy}
                      required
                      data-testid={`agenda-plan-many-day-${entry.key}`}
                    />
                  </label>
                  {isTicket && (
                    <label className="field wp-plan-many-field">
                      <span className="field-label">{t("agenda.plan_many_time")}</span>
                      <input
                        className="field-input"
                        type="time"
                        value={draft.time}
                        onChange={(event) => setDraft(entry.key, { time: event.target.value })}
                        disabled={busy}
                        data-testid={`agenda-plan-many-time-${entry.key}`}
                      />
                    </label>
                  )}
                </li>
              );
            })}
          </ul>
          {rows.some((entry) => entry.ticket_id !== null) && (
            <label className="wp-plan-check">
              <input
                type="checkbox"
                checked={applyToSlots}
                onChange={(event) => setApplyToSlots(event.target.checked)}
                disabled={busy}
                data-testid="agenda-plan-many-everyone"
              />
              {t("agenda.plan_it_everyone")}
            </label>
          )}
          <div className="plan-modal-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
              disabled={busy}
              data-testid="agenda-plan-many-cancel"
            >
              {t("common:cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy || rows.length === 0}
              data-testid="agenda-plan-many-save"
            >
              {busy ? t("common:admin_form.saving") : t("agenda.plan_many_save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
