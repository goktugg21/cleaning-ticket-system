// Sprint 11/12 frontend — RecurringJob detail: read-only job summary +
// archive/unarchive + generate-occurrences + the per-job occurrence list
// with skip / cancel / override actions. Provider-only surface.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  archiveRecurringJob,
  generateOccurrences,
  getRecurringJob,
  listPlannedOccurrences,
  skipOccurrence,
  cancelOccurrence,
  unarchiveRecurringJob,
} from "../../api/plannedWork";
import type {
  PlannedOccurrence,
  RecurringJob,
  RecurringJobWindow,
} from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { RejectReasonDialog } from "../../components/RejectReasonDialog";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/ToastProvider";
import { formatDate, formatDateTime, formatMoney } from "../../lib/intl";
import { OccurrenceStatusBadge } from "./OccurrenceStatusBadge";
import { OccurrenceOverrideDialog } from "./OccurrenceOverrideDialog";
import { RecurringJobCalendar } from "./RecurringJobCalendar";

type ReasonMode = "skip" | "cancel";

function occurrenceWindow(occ: PlannedOccurrence): string {
  const parts: string[] = [];
  if (occ.preferred_start_time) parts.push(occ.preferred_start_time.slice(0, 5));
  if (occ.time_window_label) parts.push(occ.time_window_label);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function formatWindow(window: RecurringJobWindow): string {
  const parts: string[] = [];
  if (window.start_time) parts.push(window.start_time.slice(0, 5));
  if (window.label) parts.push(window.label);
  return parts.length > 0 ? parts.join(" ") : "—";
}

export function RecurringJobDetailPage() {
  const { id } = useParams();
  const { push } = useToast();
  const { t } = useTranslation(["planned_work", "common"]);

  const [job, setJob] = useState<RecurringJob | null>(null);
  const [occurrences, setOccurrences] = useState<PlannedOccurrence[]>([]);
  const [occCount, setOccCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  // Generate dialog state.
  const generateRef = useRef<ConfirmDialogHandle>(null);
  const archiveRef = useRef<ConfirmDialogHandle>(null);
  const [daysAhead, setDaysAhead] = useState("14");

  // Occurrence action dialogs.
  const [reasonDialog, setReasonDialog] = useState<{
    mode: ReasonMode;
    occ: PlannedOccurrence;
  } | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<PlannedOccurrence | null>(
    null,
  );

  async function loadOccurrences(jobId: string | number) {
    const resp = await listPlannedOccurrences({
      recurring_job: Number(jobId),
      page_size: 200,
    });
    setOccurrences(resp.results);
    setOccCount(resp.count);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (id === undefined) return;
      setLoading(true);
      setError("");
      try {
        const [jobData, occResp] = await Promise.all([
          getRecurringJob(id),
          listPlannedOccurrences({ recurring_job: Number(id), page_size: 200 }),
        ]);
        if (cancelled) return;
        setJob(jobData);
        setOccurrences(occResp.results);
        setOccCount(occResp.count);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  function pricingSummary(j: RecurringJob): string {
    if (j.pricing_mode === "FIXED" && j.fixed_price != null) {
      return `${formatMoney(j.fixed_price)} ${t("pricing.ex_vat_suffix")}`;
    }
    if (j.pricing_mode === "HOURLY") return t("pricing_mode.HOURLY");
    return t("pricing.included");
  }

  function occurrencePricing(occ: PlannedOccurrence): string {
    if (occ.pricing_mode === "FIXED" && occ.total_inc_vat != null) {
      return formatMoney(occ.total_inc_vat);
    }
    if (occ.pricing_mode === "CONTRACT_INCLUDED") return t("pricing.included");
    return "—";
  }

  function replaceOccurrence(updated: PlannedOccurrence) {
    setOccurrences((prev) =>
      prev.map((o) => (o.id === updated.id ? updated : o)),
    );
  }

  async function handleArchive() {
    if (!job) return;
    setActionBusy(true);
    try {
      const updated = await archiveRecurringJob(job.id);
      setJob(updated);
      archiveRef.current?.close();
      push({ variant: "success", title: t("archive.toast_archived") });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    } finally {
      setActionBusy(false);
    }
  }

  async function handleUnarchive() {
    if (!job) return;
    setActionBusy(true);
    try {
      const updated = await unarchiveRecurringJob(job.id);
      setJob(updated);
      push({ variant: "success", title: t("archive.toast_unarchived") });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    } finally {
      setActionBusy(false);
    }
  }

  async function handleGenerate() {
    if (!job) return;
    const trimmed = daysAhead.trim();
    const value = trimmed === "" ? undefined : Number(trimmed);
    setActionBusy(true);
    try {
      const result = await generateOccurrences(job.id, value);
      generateRef.current?.close();
      push({
        variant: "success",
        title: t("generate.result_toast_title"),
        description: t("generate.result_toast_desc", {
          occurrences: result.occurrences_created,
          tickets: result.tickets_created,
        }),
      });
      // Refresh both the occurrence list and the job (count changed).
      const [jobData] = await Promise.all([
        getRecurringJob(job.id),
        loadOccurrences(job.id),
      ]);
      setJob(jobData);
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    } finally {
      setActionBusy(false);
    }
  }

  async function handleReasonConfirm(reason: string) {
    if (!reasonDialog) return;
    const { mode, occ } = reasonDialog;
    setReasonDialog(null);
    try {
      const updated =
        mode === "skip"
          ? await skipOccurrence(occ.id, reason)
          : await cancelOccurrence(occ.id, reason);
      replaceOccurrence(updated);
      push({
        variant: "success",
        title:
          mode === "skip" ? t("skip.toast_title") : t("cancel.toast_title"),
      });
    } catch (err) {
      push({ variant: "error", title: getApiError(err) });
    }
  }

  const daysAheadNum = useMemo(() => {
    const trimmed = daysAhead.trim();
    if (trimmed === "") return undefined;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : NaN;
  }, [daysAhead]);
  const generateDisabled =
    daysAheadNum !== undefined &&
    (Number.isNaN(daysAheadNum) || daysAheadNum < 1 || daysAheadNum > 365);

  if (loading) {
    return (
      <div className="loading-bar">
        <div className="loading-bar-fill" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div>
        <Link to="/planned-work" className="link-back">
          {t("detail.back_to_list")}
        </Link>
        <div className="alert-error" role="alert" style={{ marginTop: 16 }}>
          {error || t("errors.load_failed")}
        </div>
      </div>
    );
  }

  return (
    <div data-testid="recurring-job-detail-page">
      <PageHeader
        backLink={{ to: "/planned-work", label: t("detail.back_to_list") }}
        eyebrow={t("common:ops")}
        title={job.title}
        statusPill={
          <StatusBadge
            status={{
              kind: "generic",
              tone: job.is_active ? "approved" : "closed",
              label: job.is_active
                ? t("detail.status_active")
                : t("detail.status_archived"),
            }}
          />
        }
        subtitle={`${job.building_name} · ${job.customer_name}`}
        actions={
          <>
            <Link
              className="btn btn-secondary btn-sm"
              to={`/planned-work/${job.id}/edit`}
              data-testid="recurring-job-edit-link"
            >
              {t("detail.edit")}
            </Link>
            {job.is_active ? (
              <>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => archiveRef.current?.open()}
                  disabled={actionBusy}
                  data-testid="recurring-job-archive"
                >
                  {t("detail.archive")}
                </button>
                {/* Codex P1 — Generate only on an ACTIVE job. An archived
                    job must not spawn occurrences/tickets, so its trigger
                    is hidden (a backend guard on the generate action is a
                    separate follow-up). */}
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => generateRef.current?.open()}
                  disabled={actionBusy}
                  data-testid="recurring-job-generate"
                >
                  {t("detail.generate")}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleUnarchive}
                disabled={actionBusy}
                data-testid="recurring-job-unarchive"
              >
                {t("detail.unarchive")}
              </button>
            )}
          </>
        }
      />

      {/* Summary */}
      <div className="card" style={{ padding: "18px 22px", marginBottom: 16 }}>
        <div className="section-head">
          <div className="section-head-title">{t("detail.summary_title")}</div>
        </div>
        <div className="preview-list" style={{ marginTop: 8 }}>
          <SummaryRow label={t("detail.field_building")} value={job.building_name} />
          <SummaryRow label={t("detail.field_customer")} value={job.customer_name} />
          <SummaryRow label={t("detail.field_company")} value={job.company_name} />
          <SummaryRow
            label={t("detail.field_frequency")}
            value={t(`frequency.${job.frequency}`)}
          />
          <SummaryRow
            label={t("detail.field_period")}
            value={
              job.end_date
                ? t("detail.period_value", {
                    start: formatDate(job.start_date),
                    end: formatDate(job.end_date),
                  })
                : t("detail.period_open", { start: formatDate(job.start_date) })
            }
          />
          {(job.frequency === "WEEKLY" || job.frequency === "BIWEEKLY") && (
            <SummaryRow
              label={t("detail.field_weekdays")}
              value={
                job.weekdays.length > 0
                  ? job.weekdays
                      .map((d) => t(`weekday_short.${d}`))
                      .join(", ")
                  : t("detail.no_weekdays")
              }
            />
          )}
          <SummaryRow
            label={t("detail.field_windows")}
            value={
              job.windows.length > 0
                ? job.windows.map((w) => formatWindow(w)).join(" · ")
                : t("detail.no_window")
            }
          />
          <SummaryRow label={t("detail.field_pricing")} value={pricingSummary(job)} />
          {job.pricing_mode === "FIXED" && (
            <SummaryRow label={t("detail.field_vat")} value={`${job.vat_pct}%`} />
          )}
          <SummaryRow
            label={t("detail.field_default_staff")}
            value={String(job.default_staff_ids.length)}
          />
          <SummaryRow
            label={t("detail.field_default_managers")}
            value={String(job.default_manager_ids.length)}
          />
          <SummaryRow
            label={t("detail.field_occurrences_count")}
            value={String(job.occurrences_count)}
          />
          <SummaryRow
            label={t("detail.field_created_by")}
            value={job.created_by_email}
          />
          <SummaryRow
            label={t("detail.field_created_at")}
            value={formatDateTime(job.created_at)}
          />
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          {job.description?.trim() ? job.description : t("detail.no_description")}
        </p>
      </div>

      {/* Sprint 6 — occurrence calendar (explicit per-date tick control).
          Keyed by job id so it remounts + re-seeds on a job change (no
          resync effect). Read-only when the job is archived. */}
      <RecurringJobCalendar
        key={job.id}
        jobId={job.id}
        canManage={job.is_active}
      />

      {/* Occurrences */}
      <div className="card" style={{ overflow: "hidden" }}>
        <div className="section-head" style={{ padding: "16px 18px 0" }}>
          <div>
            <div className="section-head-title">
              {t("detail.occurrences_title")}
            </div>
            <p className="muted small" style={{ marginTop: 2 }}>
              {t("detail.occurrences_subtitle")}
            </p>
          </div>
        </div>

        {occurrences.length === 0 ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title={t("detail.occurrences_empty_title")}
              description={t("detail.occurrences_empty_desc")}
              testId="planned-work-occurrences-empty"
            />
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("detail.occ_col_date")}</th>
                    <th>{t("detail.occ_col_status")}</th>
                    <th>{t("detail.occ_col_window")}</th>
                    <th>{t("detail.occ_col_pricing")}</th>
                    <th>{t("detail.occ_col_ticket")}</th>
                    <th aria-label={t("detail.occ_col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {occurrences.map((occ) => {
                    const canSkip =
                      occ.status === "PLANNED" && occ.ticket_id == null;
                    const canCancel =
                      occ.status === "PLANNED" ||
                      occ.status === "TICKET_CREATED" ||
                      occ.status === "RESCHEDULED";
                    const canOverride = occ.status !== "CANCELLED";
                    return (
                      <tr key={occ.id} data-testid="planned-occurrence-row">
                        <td className="td-date">{formatDate(occ.planned_date)}</td>
                        <td>
                          <OccurrenceStatusBadge status={occ.status} />
                        </td>
                        <td>{occurrenceWindow(occ)}</td>
                        <td>{occurrencePricing(occ)}</td>
                        <td>
                          {occ.ticket_id != null ? (
                            <Link to={`/tickets/${occ.ticket_id}`}>
                              {t("detail.view_ticket", { id: occ.ticket_id })}
                            </Link>
                          ) : (
                            <span className="muted">{t("detail.no_ticket")}</span>
                          )}
                        </td>
                        <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                          {canSkip && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() =>
                                setReasonDialog({ mode: "skip", occ })
                              }
                              data-testid="occurrence-skip"
                            >
                              {t("detail.action_skip")}
                            </button>
                          )}
                          {canCancel && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() =>
                                setReasonDialog({ mode: "cancel", occ })
                              }
                              data-testid="occurrence-cancel"
                            >
                              {t("detail.action_cancel")}
                            </button>
                          )}
                          {canOverride && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() => setOverrideTarget(occ)}
                              data-testid="occurrence-override"
                            >
                              {t("detail.action_override")}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {occCount > occurrences.length && (
              <p className="muted small" style={{ padding: "10px 18px" }}>
                {t("detail.occurrences_truncated", {
                  count: occurrences.length,
                })}
              </p>
            )}
          </>
        )}
      </div>

      {/* Generate occurrences dialog */}
      <ConfirmDialog
        ref={generateRef}
        title={t("generate.dialog_title")}
        body={
          <div>
            <p style={{ marginBottom: 12 }}>{t("generate.dialog_body")}</p>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label" htmlFor="gen-days">
                {t("generate.field_days_ahead")}
              </label>
              <input
                id="gen-days"
                className="field-input"
                type="number"
                min="1"
                max="365"
                value={daysAhead}
                onChange={(event) => setDaysAhead(event.target.value)}
              />
              <div className="form-section-helper">
                {t("generate.field_days_ahead_hint")}
              </div>
            </div>
          </div>
        }
        confirmLabel={t("generate.confirm")}
        cancelLabel={t("form.cancel")}
        onConfirm={handleGenerate}
        busy={actionBusy}
        confirmDisabled={generateDisabled}
      />

      {/* Archive confirm dialog */}
      <ConfirmDialog
        ref={archiveRef}
        title={t("archive.dialog_title")}
        body={t("archive.dialog_body")}
        confirmLabel={t("archive.confirm")}
        cancelLabel={t("form.cancel")}
        onConfirm={handleArchive}
        busy={actionBusy}
      />

      {/* Skip / cancel reason dialog */}
      <RejectReasonDialog
        open={reasonDialog !== null}
        title={
          reasonDialog?.mode === "cancel"
            ? t("cancel.dialog_title")
            : t("skip.dialog_title")
        }
        description={
          reasonDialog?.mode === "cancel"
            ? t("cancel.dialog_desc")
            : t("skip.dialog_desc")
        }
        placeholder={
          reasonDialog?.mode === "cancel"
            ? t("cancel.dialog_placeholder")
            : t("skip.dialog_placeholder")
        }
        confirmLabel={
          reasonDialog?.mode === "cancel"
            ? t("cancel.dialog_confirm")
            : t("skip.dialog_confirm")
        }
        cancelLabel={t("form.cancel")}
        onCancel={() => setReasonDialog(null)}
        onConfirm={handleReasonConfirm}
      />

      {/* Override dialog (remount per occurrence via key) */}
      {overrideTarget && (
        <OccurrenceOverrideDialog
          key={overrideTarget.id}
          occurrence={overrideTarget}
          onCancel={() => setOverrideTarget(null)}
          onSaved={(updated) => {
            replaceOccurrence(updated);
            setOverrideTarget(null);
            push({ variant: "success", title: t("override.toast_title") });
          }}
        />
      )}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="preview-row">
      <span className="preview-key">{label}</span>
      <span className="preview-val">{value}</span>
    </div>
  );
}
