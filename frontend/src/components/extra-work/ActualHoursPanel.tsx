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
import { formatMoney } from "../../lib/intl";
import { useToast } from "../ToastProvider";
import type { ActualHoursLine } from "./activeHourlyLines";
import { finiteOrNull } from "./activeHourlyLines";

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

// W25 — the same two-place rounding the backend applies per line
// (`final_amounts._two_places`), so a client preview and the server's
// answer do not disagree over a half cent.
function twoPlaces(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

// W25 — what the backend will bill this line for: the entered hours if
// there are any, otherwise the ordered quantity
// (`final_amounts.billable_quantity`). `null` when neither is a number.
function billableQuantity(
  line: ActualHoursLine,
  typed: string | undefined,
): number | null {
  const entered = finiteOrNull((typed ?? "").trim());
  if (entered !== null) return entered;
  return finiteOrNull(line.actual_hours) ?? line.quantity;
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
  previewCoversTotal = false,
  finalSubtotalAmount = null,
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
  /** W25 — true only when these hourly lines ARE the whole active
   *  priced set, so the sum of their client-side math is comparable to
   *  the EW's server subtotal. The PATCH response carries no per-line
   *  amounts, so with other lines in the set no honest comparison
   *  exists and none is claimed. */
  previewCoversTotal?: boolean;
  /** W25 — the SERVER's stored subtotal for the whole active priced
   *  set. Read alongside `previewCoversTotal` to say so when the saved
   *  total is not what this screen computed. */
  finalSubtotalAmount?: string | null;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const [draft, setDraft] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      hourlyLines.map((line) => [line.id, line.actual_hours ?? ""]),
    ),
  );
  const [saving, setSaving] = useState(false);

  // W25 — per-line preview: hours x rate, two-placed exactly as the
  // backend does it. `null` means "no claim" (no rate, or no number in
  // the box yet), which renders as an em dash, never a EUR 0,00.
  const linePreview = (line: ActualHoursLine): number | null => {
    if (line.rate === null) return null;
    const typed = finiteOrNull((draft[line.id] ?? "").trim());
    if (typed === null) return null;
    return twoPlaces(typed * line.rate);
  };
  const anyRate = hourlyLines.some((line) => line.rate !== null);
  // W25 — the WHOLE-set preview, used only for the post-save
  // comparison: every line bills at its billable quantity, entered or
  // ordered. `null` if any line is unrateable or unquantified, because
  // a sum missing a term is not a prediction.
  const previewSubtotal = (): number | null => {
    let total = 0;
    for (const line of hourlyLines) {
      if (line.rate === null) return null;
      const qty = billableQuantity(line, draft[line.id]);
      if (qty === null) return null;
      total += twoPlaces(qty * line.rate);
    }
    return twoPlaces(total);
  };
  // W25 — the SERVER's saved subtotal beside what this screen computes
  // for the same set. Only asked when nothing is unsaved in the boxes
  // (an unsaved edit is SUPPOSED to differ), when these hourly lines
  // are the whole priced set, and when the server has actually stored a
  // subtotal. On disagreement the server's number is the one shown.
  // Compared as NUMBERS, not strings: the server stores "3.00" where
  // the operator typed "3", and a string compare would read an
  // untouched box as an unsaved edit.
  const nothingUnsaved = hourlyLines.every(
    (line) =>
      finiteOrNull((draft[line.id] ?? "").trim()) ===
      finiteOrNull(line.actual_hours),
  );
  const serverSubtotal = finiteOrNull(finalSubtotalAmount);
  const previewedSubtotal =
    previewCoversTotal && nothingUnsaved ? previewSubtotal() : null;
  const subtotalDisagrees =
    serverSubtotal !== null &&
    previewedSubtotal !== null &&
    Math.abs(serverSubtotal - previewedSubtotal) >= 0.005;

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
          {hourlyLines.map((line) => {
            const stored = finiteOrNull(line.actual_hours);
            return (
              <div
                key={line.id}
                className="detail-kv-row"
                data-testid="extra-work-actual-hours-row"
              >
                <span className="detail-kv-label">{line.label}</span>
                <span className="detail-kv-val">
                  {line.actual_hours ?? "—"}
                  {/* W25 — a locked row states the same arithmetic the
                      editable one does; the numbers are frozen, not
                      absent. */}
                  {line.rate !== null && (
                    <span
                      className="muted small"
                      style={{ marginLeft: 6, whiteSpace: "nowrap" }}
                      data-testid="extra-work-actual-hours-math"
                    >
                      {t("detail.actual_hours_unit")} {"\u00d7"}{" "}
                      {formatMoney(line.rate)} ={" "}
                      {stored !== null
                        ? formatMoney(twoPlaces(stored * line.rate))
                        : "—"}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        hourlyLines.map((line) => {
          const preview = linePreview(line);
          return (
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
              {/* W25 — the line shows its own arithmetic: hours x rate =
                  amount, recomputed as the operator types, an em dash
                  while the box is empty. A line whose source carries no
                  per-unit rate keeps the plain input alone — no invented
                  rate, no invented product. The row wraps rather than
                  overflowing the ~340px ticket rail. */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  flexWrap: "wrap",
                }}
              >
                <input
                  id={`ew-actual-hours-${ewId}-${line.id}`}
                  type="number"
                  min="0"
                  step="0.25"
                  inputMode="decimal"
                  className="field-input"
                  style={
                    line.rate !== null
                      ? { flex: "0 1 84px", minWidth: 64 }
                      : undefined
                  }
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
                {line.rate !== null && (
                  <span
                    style={{ whiteSpace: "nowrap" }}
                    data-testid="extra-work-actual-hours-math"
                  >
                    <span className="muted small">
                      {t("detail.actual_hours_unit")} {"\u00d7"}{" "}
                      {formatMoney(line.rate)} ={" "}
                    </span>
                    <strong data-testid="extra-work-actual-hours-line-amount">
                      {preview !== null ? formatMoney(preview) : "—"}
                    </strong>
                  </span>
                )}
              </div>
            </div>
          );
        })
      )}
      {anyRate && (
        <span className="muted small" data-testid="extra-work-actual-hours-note">
          {t("detail.actual_hours_math_note")}
        </span>
      )}
      {subtotalDisagrees && (
        <span
          className="muted small"
          data-testid="extra-work-actual-hours-server-diff"
        >
          {t("detail.actual_hours_server_subtotal", {
            server: formatMoney(serverSubtotal),
            preview: formatMoney(previewedSubtotal),
          })}
        </span>
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
