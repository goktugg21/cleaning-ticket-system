// RecurringJob detail. Provider-only surface.
//
// W-PW1 — a recurring job is a MEMBERSHIP, and this page says three things
// in this order and nothing else at first sight:
//
//   1. THE AGREEMENT  ONE header card: the agreement sentence on top —
//                     what was agreed, how often, for whom — and the
//                     job's facts under it as a label-over-value grid.
//                     W-P5.1 folded away the "All details" disclosure
//                     that used to hold those facts: pinned to the
//                     card's right edge it left the middle of the top
//                     line empty and, opened, made a 472px card whose
//                     ink covered 3.8% of it. Facts with no value are
//                     absent rather than rendered as a dash.
//   2. THE VISITS     the calendar, the page's primary surface. Every date
//                     is an occurrence and every date's actions open where
//                     it was clicked. The occurrence TABLE is gone: it was
//                     a second list of the dates the calendar already
//                     shows, with the actions attached to the copy instead
//                     of to the thing.
//   3. THE MONEY      one line — the contract line this work is billed
//                     through, or the picker that links one.
//
// Per-visit pricing is gone from this page by the owner's ruling: a
// recurring job is billed as a membership through its contract line, or it
// is a single job. The COLUMNS and the API are untouched; stored values are
// simply no longer displayed or offered as a control.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  archiveRecurringJob,
  generateOccurrences,
  updateRecurringJob,
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
  RecurringJobWritePayload,
} from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { canAccessContracts } from "../../auth/permissions";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { RejectReasonDialog } from "../../components/RejectReasonDialog";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/ToastProvider";
import { formatDate, formatDateTime } from "../../lib/intl";
import { OccurrenceStatusBadge } from "./OccurrenceStatusBadge";
import { OccurrenceOverrideDialog } from "./OccurrenceOverrideDialog";
import { RecurringJobCalendar } from "./RecurringJobCalendar";
import { customerLabelName } from "../../lib/customerLabelName";
import { listContracts } from "../../api/contracts";
import "../../styles/planned-work.css";

// W-PW1 — the contract-line link, declared LOCALLY for the same reason
// `RecurringJobFormPage` already declares it locally: the backend carries
// `contract_line` + `contract_line_name` on the read and `contract_line` on
// the write, but `api/plannedWork.types.ts` belongs to another wave. Fold
// both into that file and delete these when it is free.
type ContractLineLinkRead = { contract_line: number | null; contract_line_name: string | null };
type ContractLineLinkWrite = { contract_line: number | null };

/** One offerable line: the line plus the contract it sits on, because a
 *  line name repeats across a customer's contracts and only the contract
 *  number separates them. Same shape the form's picker uses. */
interface ContractLineOption {
  id: number;
  lineName: string;
  contractNo: string;
  contractId: number;
}

type ReasonMode = "skip" | "cancel";

/** A window as words, or "" when it carries neither a time nor a label.
 *  It used to answer "—" for that case, which put a dash in the facts
 *  grid where the reader wanted a fact: a job CAN hold a window row that
 *  says nothing, and "—" does not tell an operator whether the window is
 *  missing or merely blank. The caller turns an all-empty set into "no
 *  fixed window", which is the actual answer. */
function formatWindow(window: RecurringJobWindow): string {
  const parts: string[] = [];
  if (window.start_time) parts.push(window.start_time.slice(0, 5));
  if (window.label) parts.push(window.label);
  return parts.join(" ");
}

export function RecurringJobDetailPage() {
  const { id } = useParams();
  const { push } = useToast();
  const { me } = useAuth();
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
  // Treatment 1 — each dialog carries its own failure in its own body.
  const [generateError, setGenerateError] = useState("");
  const [archiveError, setArchiveError] = useState("");
  const [daysAhead, setDaysAhead] = useState("14");

  // Occurrence action dialogs.
  const [reasonDialog, setReasonDialog] = useState<{
    mode: ReasonMode;
    occ: PlannedOccurrence;
  } | null>(null);
  const [overrideTarget, setOverrideTarget] = useState<PlannedOccurrence | null>(
    null,
  );
  // Treatment 1 — the skip/cancel failure, shown in the dialog itself.
  const [reasonError, setReasonError] = useState("");
  // Treatment 1 — Unarchive has no dialog, so its failure sits beside it.
  const [unarchiveError, setUnarchiveError] = useState("");

  // W-PW1 THE MONEY — the customer's offerable contract lines, and the
  // pending pick while a link is being saved. `null` means NOT LOADED,
  // which is a different fact from "loaded and empty": only the second
  // one may be used to conclude the customer has nothing to link to.
  const [contractLines, setContractLines] = useState<
    ContractLineOption[] | null
  >(null);
  const [linkBusy, setLinkBusy] = useState(false);
  // Treatment 1 — this renders inside `.pw-money`, never as a toast.
  const [linkError, setLinkError] = useState("");

  // NO new endpoint: `GET /api/contracts/?customer=<id>` already carries
  // the contract number and the ACTIVE revision's lines in `projects`.
  // Paged exhaustively client-side (the Sprint 120 pattern) rather than by
  // loosening a shared list's pagination — Sprint 134/135's lesson.
  async function loadContractLines(customerId: number) {
    const rows: ContractLineOption[] = [];
    let page = 1;
    for (let i = 0; i < 100; i++) {
      const response = await listContracts({
        customer: customerId,
        page,
        page_size: 200,
      });
      for (const contract of response.results) {
        for (const line of contract.projects) {
          rows.push({
            id: line.id,
            lineName: line.name,
            contractNo: contract.contract_no,
            contractId: contract.id,
          });
        }
      }
      if (!response.next) break;
      page += 1;
    }
    return rows;
  }

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

  // THE MONEY's option list, once the job tells us which customer it is
  // for. Kept unloaded on failure rather than collapsed to an empty list:
  // an empty list would read as "this customer has no contract lines",
  // which is a claim a failed request cannot support.
  useEffect(() => {
    const customerId = job?.customer;
    if (customerId === undefined) return;
    let cancelled = false;
    loadContractLines(customerId)
      .then((rows) => {
        if (!cancelled) setContractLines(rows);
      })
      .catch(() => {
        if (!cancelled) setContractLines(null);
      });
    return () => {
      cancelled = true;
    };
  }, [job?.customer]);

  async function handleLinkContractLine(value: string) {
    if (!job) return;
    setLinkError("");
    setLinkBusy(true);
    try {
      const payload: ContractLineLinkWrite = {
        contract_line: value === "" ? null : Number(value),
      };
      const updated = await updateRecurringJob(
        job.id,
        payload as unknown as Partial<RecurringJobWritePayload>,
      );
      setJob(updated);
      push({
        variant: "success",
        title: value === "" ? t("money.toast_unlinked") : t("money.toast_linked"),
      });
    } catch (err) {
      // Treatment 1 — the failure belongs BESIDE the picker that fired
      // it. A toast for this was wrong twice over: it leaves the money
      // line looking untouched, and it is gone before the operator has
      // finished reading the row it was about.
      setLinkError(getApiError(err));
    } finally {
      setLinkBusy(false);
    }
  }

  function replaceOccurrence(updated: PlannedOccurrence) {
    setOccurrences((prev) =>
      prev.map((o) => (o.id === updated.id ? updated : o)),
    );
  }

  async function handleArchive() {
    if (!job) return;
    setArchiveError("");
    setActionBusy(true);
    try {
      const updated = await archiveRecurringJob(job.id);
      setJob(updated);
      archiveRef.current?.close();
      push({ variant: "success", title: t("archive.toast_archived") });
    } catch (err) {
      // Treatment 1 — stays open, reports in place.
      setArchiveError(getApiError(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleUnarchive() {
    if (!job) return;
    setUnarchiveError("");
    setActionBusy(true);
    try {
      const updated = await unarchiveRecurringJob(job.id);
      setJob(updated);
      push({ variant: "success", title: t("archive.toast_unarchived") });
    } catch (err) {
      // Treatment 1 — the only action here with no modal to fall back
      // on, so its failure renders in the header's actions node, beside
      // the button that fired it.
      setUnarchiveError(getApiError(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleGenerate() {
    if (!job) return;
    const trimmed = daysAhead.trim();
    const value = trimmed === "" ? undefined : Number(trimmed);
    setGenerateError("");
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
      // Treatment 1 — the dialog STAYS OPEN and carries its own failure.
      // Closing it and firing a toast threw away the one surface the
      // operator was looking at, along with the days-ahead value they
      // had just typed; they could not retry without re-entering it.
      setGenerateError(getApiError(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleReasonConfirm(reason: string) {
    if (!reasonDialog) return;
    const { mode, occ } = reasonDialog;
    // Treatment 1 — the dialog is NOT dismissed before the write is
    // known to have landed. It used to close on the first line of this
    // function, so a rejected skip took the operator's typed reason with
    // it and answered from a toast on a page that looked unchanged.
    setReasonError("");
    try {
      const updated =
        mode === "skip"
          ? await skipOccurrence(occ.id, reason)
          : await cancelOccurrence(occ.id, reason);
      replaceOccurrence(updated);
      setReasonDialog(null);
      push({
        variant: "success",
        title:
          mode === "skip" ? t("skip.toast_title") : t("cancel.toast_title"),
      });
    } catch (err) {
      // `RejectReasonDialog` is shared and has no error slot of its own,
      // so the failure rides its `description` — which IS the open
      // modal, where Treatment 1 wants it. A real slot on that component
      // belongs to whoever owns it.
      setReasonError(getApiError(err));
    }
  }

  // THE VISITS — the occurrences the calendar hands to its date panel,
  // keyed by the date they fall on. Several windows on one date means
  // several rows on one key, which is why the value is a list.
  const occurrencesByDate = useMemo(() => {
    const map = new Map<string, PlannedOccurrence[]>();
    for (const occ of occurrences) {
      const list = map.get(occ.planned_date);
      if (list) list.push(occ);
      else map.set(occ.planned_date, [occ]);
    }
    return map;
  }, [occurrences]);

  // THE VISITS — "next up". The calendar opens on the CURRENT month, so a
  // job whose next visit falls later shows an empty grid and says nothing
  // about when it next happens. Five dates and their state answer that
  // without making the operator page through months, which is the whole
  // reason this strip earns the space it takes.
  const nextUp = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return occurrences
      .filter((o) => o.planned_date >= today && o.status !== "CANCELLED")
      .sort((a, b) => a.planned_date.localeCompare(b.planned_date))
      .slice(0, 5);
  }, [occurrences]);

  // THE AGREEMENT — the pattern as a sentence fragment an operator reads
  // rather than a row labelled "Frequency". Weekly and biweekly jobs name
  // their weekdays; the others have none to name.
  const patternInWords = useMemo(() => {
    if (!job) return "";
    const freq = t(`frequency.${job.frequency}`);
    const named = job.frequency === "WEEKLY" || job.frequency === "BIWEEKLY";
    if (!named || job.weekdays.length === 0) return freq;
    const days = [...job.weekdays]
      .sort((a, b) => a - b)
      .map((d) => t(`weekday_short.${d}`))
      .join(", ");
    return `${days} · ${freq}`;
  }, [job, t]);

  const periodText = useMemo(() => {
    if (!job) return "";
    return job.end_date
      ? t("detail.period_value", {
          start: formatDate(job.start_date),
          end: formatDate(job.end_date),
        })
      : t("detail.period_open", { start: formatDate(job.start_date) });
  }, [job, t]);

  // THE MONEY — the stored link, resolved against the fetched options so
  // the row can offer the way through to the contract. A line the active
  // revision no longer carries still renders (from the job's own
  // `contract_line_name`), just without a link: the stored fact is real
  // even when the option list has moved on.
  const linkedLine = useMemo(() => {
    if (!job) return null;
    const link = job as unknown as ContractLineLinkRead;
    if (link.contract_line == null) return null;
    const match = (contractLines ?? []).find(
      (line) => line.id === link.contract_line,
    );
    if (match) {
      return {
        label: match.contractNo
          ? `${match.lineName} — ${match.contractNo}`
          : match.lineName,
        contractId: match.contractId as number | null,
      };
    }
    return {
      label: link.contract_line_name ?? String(link.contract_line),
      contractId: null,
    };
  }, [job, contractLines]);

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
                  onClick={() => {
                    setArchiveError("");
                    archiveRef.current?.open();
                  }}
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
                  onClick={() => {
                    setGenerateError("");
                    generateRef.current?.open();
                  }}
                  disabled={actionBusy}
                  data-testid="recurring-job-generate"
                >
                  {t("detail.generate")}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={handleUnarchive}
                  disabled={actionBusy}
                  data-testid="recurring-job-unarchive"
                >
                  {t("detail.unarchive")}
                </button>
                {unarchiveError && (
                  <span
                    className="alert-error pw-action-error"
                    role="alert"
                    data-testid="recurring-job-unarchive-error"
                  >
                    {unarchiveError}
                  </span>
                )}
              </>
            )}
          </>
        }
      />

      {/* ---- 1. THE AGREEMENT ------------------------------------------
          ONE header card, two parts. The top line is the agreement
          sentence — what was agreed, how often, for whom. Under it the
          job's facts as a label-over-value grid.

          Until now those facts sat behind an "All details" disclosure
          pinned to the card's right edge by `margin-left: auto`. That
          left a 892-953px hole across the middle of the top line at
          1920, and opening it produced a 472px card whose ink covered
          3.8% of its own area — a void with a narrow list floating in
          it. A grid fills the card it is given instead of hanging off
          one corner of it.

          Facts that are NOT set are ABSENT, not rendered as a dash or a
          "No description." placeholder: an empty row still costs a line
          of reading and says nothing. Company, the windows and the
          counts are always true of a job, so they always show. */}
      <div className="pw-agreement" data-testid="recurring-job-agreement">
        <p className="pw-agreement-line">
          <span
            className="pw-agreement-pattern"
            data-testid="pw-agreement-pattern"
          >
            {patternInWords}
          </span>
          <span className="pw-agreement-sep" aria-hidden="true">
            ·
          </span>
          <span className="pw-agreement-window" data-testid="pw-agreement-window">
            {periodText}
          </span>
          <span className="pw-agreement-sep" aria-hidden="true">
            ·
          </span>
          <span className="pw-agreement-where">
            {job.building_name} · {job.customer_name}
          </span>
        </p>

        <dl className="pw-facts" data-testid="recurring-job-facts">
          <Fact label={t("detail.field_company")} value={job.company_name} />
          <Fact
            label={t("detail.field_department")}
            value={customerLabelName(job.department_name, t)}
          />
          <Fact
            label={t("detail.field_work_type")}
            value={customerLabelName(job.work_type_name, t)}
          />
          <Fact
            label={t("detail.field_category")}
            value={job.service_category_name ?? job.price_folder_name}
          />
          <Fact
            label={t("detail.field_windows")}
            value={
              job.windows.map((w) => formatWindow(w)).filter(Boolean).join(" · ") ||
              t("detail.no_window")
            }
          />
          <Fact
            label={t("detail.field_default_staff")}
            value={String(job.default_staff_ids.length)}
          />
          <Fact
            label={t("detail.field_default_managers")}
            value={String(job.default_manager_ids.length)}
          />
          <Fact
            label={t("detail.field_occurrences_count")}
            value={String(job.occurrences_count)}
          />
          {/* Who made it and when, as ONE fact. Two made seven facts on
              a three-column grid, so the last row carried a single item
              and ~1000px of nothing beside it at 1920. Six fills two
              rows exactly, and nine (a job that uses all three
              classifiers) fills three. */}
          <Fact
            label={t("detail.field_created")}
            value={`${job.created_by_email} · ${formatDateTime(job.created_at)}`}
          />
          {/* The description is prose, so it gets the grid's whole width
              rather than one narrow column — and only when there is one.
              Written out rather than passed as a `wide` prop so both
              class names are STRING LITERALS: `check-css-classes.mjs`
              skips a computed className, and a class the gate cannot
              read is a class it cannot tell you is undefined. */}
          {job.description?.trim() ? (
            <div className="pw-fact pw-fact-wide">
              <dt className="pw-fact-label">
                {t("detail.field_description")}
              </dt>
              <dd className="pw-fact-value">{job.description.trim()}</dd>
            </div>
          ) : null}
        </dl>
      </div>

      {/* ---- 2. THE VISITS ---------------------------------------------
          The calendar is the page's primary surface. Keyed by job id so it
          remounts + re-seeds on a job change (no resync effect). Read-only
          when the job is archived. */}
      <RecurringJobCalendar
        key={job.id}
        jobId={job.id}
        canManage={job.is_active}
        occurrencesByDate={occurrencesByDate}
        onOverride={(occ) => setOverrideTarget(occ)}
        onCancelVisit={(occ) => setReasonDialog({ mode: "cancel", occ })}
        onChanged={() => {
          void loadOccurrences(job.id);
        }}
      />

      {nextUp.length > 0 && (
        <div className="pw-nextup" data-testid="recurring-job-next-up">
          <span className="pw-money-label">{t("detail.next_up")}</span>
          {nextUp.map((occ) => (
            <span
              key={occ.id}
              className="pw-nextup-item"
              data-testid="recurring-job-next-up-item"
            >
              {formatDate(occ.planned_date)}
              <OccurrenceStatusBadge status={occ.status} />
            </span>
          ))}
          {occCount > occurrences.length && (
            <span className="muted small">
              {t("detail.occurrences_truncated", {
                count: occurrences.length,
              })}
            </span>
          )}
        </div>
      )}

      {/* ---- 3. THE MONEY ----------------------------------------------
          One line. Linked: the line's name, and the way to the contract's
          Planning tab where this job's weeks are the grid. Unlinked: the
          picker that links one, inline, because "no link" is a thing to
          fix rather than a thing to read. */}
      <div className="pw-money" data-testid="recurring-job-money">
        {linkedLine ? (
          <>
            <span className="pw-money-label">{t("money.billed_via")}</span>
            {linkedLine.contractId != null ? (
              // The contract's route is `/admin/contracts/:contractId`,
              // and its Planning tab is component state, not a URL
              // segment — there is no deep link to the tab itself, and
              // ContractDetailPage is not this wave's to change. So the
              // link reaches the contract and Planning is one click
              // away; a `?tab=planning` that silently did nothing would
              // be worse than a link that admits where it lands.
              <Link
                to={`/admin/contracts/${linkedLine.contractId}`}
                data-testid="recurring-job-money-link"
              >
                {linkedLine.label}
              </Link>
            ) : (
              <strong data-testid="recurring-job-money-link">
                {linkedLine.label}
              </strong>
            )}
            {job.is_active && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={linkBusy}
                onClick={() => void handleLinkContractLine("")}
                data-testid="recurring-job-money-unlink"
              >
                {t("money.unlink")}
              </button>
            )}
          </>
        ) : (
          <>
            <label className="pw-money-label" htmlFor="pw-contract-line">
              {t("money.not_linked")}
            </label>
            {/* A customer with NO contract at all cannot be helped by a
                picker — the answer is a contract, not a choice. It says
                so, and points at Contracts only for a viewer who may
                open it: `ContractsRoute` bounces everyone else to "/",
                and a link that silently lands you on the dashboard is a
                door painted on a wall. `contractLines === null` is NOT
                LOADED, which is a different fact from loaded-and-empty
                — only the second may conclude anything. */}
            {contractLines !== null && contractLines.length === 0 ? (
              <span
                className="pw-money-empty"
                data-testid="recurring-job-money-none"
              >
                {t("money.none_available")}
                {canAccessContracts(me?.role ?? null) && (
                  <>
                    {/* T5b — a real separator, not a word space. The
                        sentence ends in a word and the link starts with
                        one, so at 13.5px a single space read as the two
                        touching. The middot is the same divider the
                        agreement line above already uses, and it is
                        aria-hidden because it is punctuation, not a
                        word a screen reader should announce. */}
                    <span className="pw-agreement-sep" aria-hidden="true">
                      {" · "}
                    </span>
                    <Link to="/admin/contracts">
                      {t("money.none_available_link")}
                    </Link>
                  </>
                )}
              </span>
            ) : (
              <select
                id="pw-contract-line"
                className="field-select"
                disabled={linkBusy || !job.is_active || contractLines === null}
                value=""
                onChange={(event) =>
                  void handleLinkContractLine(event.target.value)
                }
                data-testid="recurring-job-money-picker"
              >
                <option value="">
                  {contractLines === null
                    ? t("money.loading")
                    : t("money.pick")}
                </option>
                {(contractLines ?? []).map((line) => (
                  <option key={line.id} value={String(line.id)}>
                    {line.contractNo
                      ? `${line.lineName} — ${line.contractNo}`
                      : line.lineName}
                  </option>
                ))}
              </select>
            )}
          </>
        )}
        {linkError && (
          <div
            className="alert-error pw-money-error"
            role="alert"
            data-testid="recurring-job-money-error"
          >
            {linkError}
          </div>
        )}
      </div>
      {/* Plan-further-ahead dialog */}
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
            {generateError && (
              <div className="alert-error" role="alert" data-testid="rj-generate-error">
                {generateError}
              </div>
            )}
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
        body={
          <>
            {t("archive.dialog_body")}
            {archiveError && (
              <div
                className="alert-error"
                role="alert"
                data-testid="rj-archive-error"
              >
                {archiveError}
              </div>
            )}
          </>
        }
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
          reasonError ||
          (reasonDialog?.mode === "cancel"
            ? t("cancel.dialog_desc")
            : t("skip.dialog_desc"))
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
        onCancel={() => {
          setReasonError("");
          setReasonDialog(null);
        }}
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

/** One fact in the agreement card's grid: the plain word above, the
 *  value below. A fact with nothing to say RENDERS NOTHING — an empty
 *  row still costs a line of reading, and a dash is not an answer. The
 *  description is the one fact this does not render; it is prose and
 *  spans the grid, so it is written out at the call site. */
function Fact({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  if (!value) return null;
  return (
    <div className="pw-fact">
      <dt className="pw-fact-label">{label}</dt>
      <dd className="pw-fact-value">{value}</dd>
    </div>
  );
}
