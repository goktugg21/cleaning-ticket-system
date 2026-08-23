/**
 * W17 — the actual-hours finalize panel, extracted from
 * ExtraWorkDetailPage so the SAME component mounts in two places: the
 * Extra Work detail's Hours tab, and the operational ticket's Extra
 * work card group (a ticket born from an extra work is the same job,
 * and entering the hours must not require knowing which door you came
 * in through). One component, two mounts — the panel moved here, it
 * was not copied.
 *
 * The active-set derivation lives in `./activeHourlyLines.ts` (this
 * file may export only components — react-refresh rule); both mounts
 * derive their line set there.
 */
import { useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { submitActualHours } from "../../api/extraWork";
import type { ExtraWorkRequestDetail } from "../../api/types";
import { useToast } from "../ToastProvider";
import type { ActualHoursLine } from "./activeHourlyLines";

// Sprint 8A — map the actual-hours endpoint's stable 4xx `code` to an
// i18n key. Anything unrecognised falls back to the axios-derived
// message via getApiError at the call site.
const ACTUAL_HOURS_ERROR_I18N_KEY: Record<string, string> = {
  final_amount_locked: "detail.actual_hours_error_locked",
  actual_hours_invalid: "detail.actual_hours_error_invalid",
  actual_hours_not_hourly: "detail.actual_hours_error_not_hourly",
  actual_hours_forbidden: "detail.actual_hours_error_forbidden",
};

function actualHoursErrorCode(err: unknown): string | null {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data;
    if (data && typeof data === "object") {
      const code = (data as Record<string, unknown>).code;
      if (typeof code === "string" && code in ACTUAL_HOURS_ERROR_I18N_KEY) {
        return code;
      }
    }
  }
  return null;
}

// Sprint 8A — provider-only actual-hours entry for the hourly cart lines
// of an INSTANT-routed Extra Work request (the cart is the active priced
// set exactly when routing_decision === "INSTANT"; proposal/legacy active
// sets need serializer exposure of `actual_hours` = a backend change, so
// they are deferred from this FE-only surface). The parent KEYS this panel
// by `actualHoursPanelKey`, so a successful save (which bumps updated_at
// on the refreshed detail) remounts the panel and re-seeds the inputs from
// the fresh `actual_hours` — no prop-derived resync effect.
//
// W18 — TWO VARIANTS, ONE OWNER. "card" is the standalone card on the
// Extra Work Hours tab; "embedded" is the same fields inside the
// ticket's one Extra-work card, which carries its own amounts, so the
// final-total line renders only in "card". The old two-column
// data-table (th width:160) clipped the input out of view in the
// ticket's narrow rail; every line is now a stacked label-over-input
// `.field` (fluid, width:100%), and locked lines render as read-only
// values with no dead controls.
export function ActualHoursPanel({
  ewId,
  hourlyLines,
  finalTotalAmount,
  locked,
  onUpdated,
  variant = "card",
  successMessage,
}: {
  ewId: number;
  hourlyLines: ActualHoursLine[];
  finalTotalAmount: string | null;
  // True once a spawned operational ticket is APPROVED/CLOSED — the backend
  // freezes the final amount then (code `final_amount_locked`). Derived from
  // the spawned tickets already on the page so the locked state is shown up
  // front, not only after a rejected Save.
  locked: boolean;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  variant?: "card" | "embedded";
  /** W22 §4 — rule 4: the save answers. When set, the success toast is
   *  this sentence, composed by the caller from the REFRESHED detail
   *  and the hours just written (their sum is handed over so no caller
   *  re-derives it from stale props). Absent, the generic "saved". */
  successMessage?: (
    detail: ExtraWorkRequestDetail,
    hoursSaved: number,
  ) => string;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const [draft, setDraft] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      hourlyLines.map((line) => [line.id, line.actual_hours ?? ""]),
    ),
  );
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    const lines = hourlyLines
      .map((line) => ({
        line_id: line.id,
        actual_hours: (draft[line.id] ?? "").trim(),
      }))
      .filter((entry) => entry.actual_hours !== "");
    if (lines.length === 0) {
      pushToast({
        variant: "info",
        title: t("detail.actual_hours_none_entered"),
      });
      return;
    }
    setSaving(true);
    try {
      const detail = await submitActualHours(ewId, lines);
      onUpdated(detail);
      const hoursSaved = lines.reduce(
        (sum, entry) => sum + (Number.parseFloat(entry.actual_hours) || 0),
        0,
      );
      pushToast({
        variant: "success",
        title: successMessage
          ? successMessage(detail, hoursSaved)
          : t("detail.actual_hours_saved"),
      });
    } catch (err) {
      const code = actualHoursErrorCode(err);
      pushToast({
        variant: "error",
        title: code
          ? t(ACTUAL_HOURS_ERROR_I18N_KEY[code])
          : getApiError(err),
      });
    } finally {
      setSaving(false);
    }
  }

  const body = (
    <>
      {locked && (
        <div
          className="alert-warning"
          data-testid="extra-work-actual-hours-locked"
        >
          {t("detail.actual_hours_error_locked")}
        </div>
      )}
      {locked ? (
        <div className="detail-kv-list">
          {hourlyLines.map((line) => (
            <div
              key={line.id}
              className="detail-kv-row"
              data-testid="extra-work-actual-hours-row"
            >
              <span className="detail-kv-label">{line.label}</span>
              <span className="detail-kv-val">{line.actual_hours ?? "—"}</span>
            </div>
          ))}
        </div>
      ) : (
        hourlyLines.map((line) => (
          <div
            key={line.id}
            className="field"
            data-testid="extra-work-actual-hours-row"
          >
            <label
              className="field-label"
              htmlFor={`ew-actual-hours-${ewId}-${line.id}`}
            >
              {line.label}
            </label>
            <input
              id={`ew-actual-hours-${ewId}-${line.id}`}
              type="number"
              min="0"
              step="0.25"
              inputMode="decimal"
              className="field-input"
              aria-label={t("detail.actual_hours_input_aria", {
                line: line.label,
              })}
              value={draft[line.id] ?? ""}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  [line.id]: event.target.value,
                }))
              }
            />
          </div>
        ))
      )}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {variant === "card" && (
          <span className="muted small">
            {t("detail.actual_hours_final_total")}{" "}
            <strong data-testid="extra-work-actual-hours-final-total">
              {finalTotalAmount ?? "—"}
            </strong>
          </span>
        )}
        {!locked && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="extra-work-actual-hours-save"
            onClick={handleSave}
            disabled={saving}
          >
            {saving
              ? t("detail.actual_hours_saving")
              : t("detail.actual_hours_save")}
          </button>
        )}
      </div>
    </>
  );

  if (variant === "embedded") {
    return (
      <div
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
        data-testid="extra-work-actual-hours"
      >
        {body}
      </div>
    );
  }
  return (
    <div
      className="card"
      style={{ marginBottom: 16 }}
      data-testid="extra-work-actual-hours"
    >
      <div className="form-section">
        <div className="form-section-title">
          {t("detail.actual_hours_section_title")}
        </div>
        {body}
      </div>
    </div>
  );
}
