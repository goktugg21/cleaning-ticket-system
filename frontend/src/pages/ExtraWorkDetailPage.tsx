// Sprint 26C — Extra Work detail page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n
// namespace; renders the cart `line_items` array and the
// `routing_decision` badge. The pricing-proposal panel, workflow
// transitions, and provider override block were functionally
// unchanged.
// Sprint 28 Batch 15.4 — two-column rebuild. The page now uses
// `<PageHeader>` with a `meta` slot for status/route/category/urgency,
// a 60/40 grid on desktop (left = read-only data, right = sticky
// action stack), `formatMoney`/`formatDate` from `lib/intl`, the new
// `<RejectReasonDialog>` for customer rejection (the backend now
// requires `customer_reject_reason` on CUSTOMER_USER -> CUSTOMER_REJECTED),
// and a proposal PDF download button when an active proposal exists.
// All locked testids from prior sprints (extra-work-detail-page,
// extra-work-detail-routing-decision, extra-work-customer-contacts-*,
// extra-work-detail-line-items*, extra-work-detail-line-item-row)
// MUST keep resolving.
//
// Role-aware view:
//   * CUSTOMER_USER: details, pricing line items (without
//     internal_cost_note), totals, customer approve/reject CTAs when
//     status === PRICING_PROPOSED and backend allows the transition.
//     Reject opens RejectReasonDialog which threads the typed reason
//     as `customer_reject_reason` on the transition payload.
//   * Provider operators (SUPER_ADMIN / COMPANY_ADMIN /
//     BUILDING_MANAGER): all of the above PLUS the pricing-line-item
//     create form, transition CTAs (UNDER_REVIEW, PRICING_PROPOSED,
//     CANCELLED), the customer-override block with mandatory reason,
//     and (when applicable) the proposal-PDF download button.
//
// The backend computes pricing totals and gates all transitions.
// The frontend is defense-in-depth only — it renders only what the
// backend's allowed_next_statuses field says.
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CalendarClock,
  Check,
  FileSearch,
  FileText,
  Pencil,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import axios from "axios";

import { listCustomerContacts } from "../api/admin";
import { getApiError } from "../api/client";
import { labelErrorCode, listLabels } from "../api/customerLabels";
import { markThreadRead, notifyInboxUnreadChanged } from "../api/inbox";
import {
  createEwMessage,
  createProposal,
  directPublishProposal,
  fetchProposalPdf,
  getEwMessageRecipients,
  getProposalDetail,
  getExtraWork,
  listEwMessages,
  listProposalsForEw,
  listExtraWorkAssignments,
  listSpawnedTickets,
  planExtraWork,
  relabelExtraWork,
  updateExtraWorkDates,
  retrySpawnTicketsForExtraWork,
  submitActualHours,
  transitionExtraWork,
  updateExtraWorkBilling,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import { ExtraWorkAssignmentCard } from "../components/extra-work/ExtraWorkAssignmentCard";
import { ExtraWorkHoursPanel } from "../components/extra-work/ExtraWorkHoursPanel";
import { PlanSummary } from "../components/extra-work/PlanSummary";
import { PlanWorkDialog } from "../components/extra-work/PlanWorkDialog";
import { isCustomerUser, isProviderManagementRole } from "../auth/permissions";
import type {
  Contact,
  CustomerLabel,
  EwMessage,
  EwMessageRecipient,
  EwMessageType,
  ExtraWorkAssignment,
  ExtraWorkCategory,
  ExtraWorkPlanPayload,
  ExtraWorkRequestDetail,
  ExtraWorkStatus,
  ExtraWorkUrgency,
  Proposal,
  ProposalDetail,
  Role,
  TicketList,
  TicketStatus,
} from "../api/types";
import { CollapsibleCard } from "../components/CollapsibleCard";
import { ConfirmDialog, type ConfirmDialogHandle } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { Toggle } from "../components/Toggle";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { PageHeader } from "../components/PageHeader";
import { ProposalBuilder } from "../components/ProposalBuilder";
import { customerLabelName } from "../lib/customerLabelName";
import { RejectReasonDialog } from "../components/RejectReasonDialog";
import { RouteBadge } from "../components/RouteBadge";
import { StatusBadge } from "../components/StatusBadge";
import { SpawnedTicketLinks } from "../components/extra-work/SpawnedTicketLinks";
import { useToast } from "../components/ToastProvider";
import { rowAmounts } from "../lib/billing";
import { extraWorkStatusLabelKey, ticketStatusLabelKey } from "../lib/enumLabels";
import { formatDate, formatDateTime, formatMoney, formatRelative, useLocaleCode } from "../lib/intl";
import { formatPlannedWindow } from "../lib/plannedWindow";
import { extraWorkCategoryName } from "../lib/extraWorkCategoryLabel";
import { Avatar } from "../components/Avatar";

// Sprint 29 Batch 29.8 — terminal ticket statuses. A spawned ticket in
// any of these is considered "done" for the cancel-warning gate; only
// non-terminal spawned tickets trigger the dialog warning panel.
const TERMINAL_TICKET_STATUSES: ReadonlySet<TicketStatus> = new Set<TicketStatus>([
  "APPROVED",
  "CLOSED",
  "REJECTED",
]);


// Sprint 182 §2 — this page's private status-label map is gone, for the
// reason the list's was: it read `extra_work:status.*` ("Customer
// approved") while the badge in this page's own header rendered
// `common:extra_work_status.*` ("Price approved"). The workflow button
// therefore offered to move a request to a status spelled differently
// from the one the header would show once it got there.
//
// `extraWorkStatusLabelKey` is the one source. It lives in `common`, so
// every call passes `{ ns: "common" }` — this page's default namespace
// is `extra_work`.
const tStatusLabel = (
  t: (key: string, options?: Record<string, unknown>) => string,
  status: ExtraWorkStatus,
) => t(extraWorkStatusLabelKey(status), { ns: "common" });

// Sprint 31 — meaningful provider action labels per transition so the
// EW workflow reads as a guided flow (Start review -> Propose price ->
// Start work / decide) instead of generic "Move to <status>" buttons.
// Keyed `${from}->${to}`; unmapped transitions fall back to the generic
// label. CANCELLED has its own label (it routes through the dialog).
const PROVIDER_ACTION_I18N: Record<string, string> = {
  "REQUESTED->UNDER_REVIEW": "detail.action_start_review",
  "UNDER_REVIEW->PRICING_PROPOSED": "detail.action_propose_price",
  "PRICING_PROPOSED->UNDER_REVIEW": "detail.action_revise_pricing",
  "CUSTOMER_REJECTED->UNDER_REVIEW": "detail.action_revise_after_reject",
  "CUSTOMER_APPROVED->IN_PROGRESS": "detail.action_mark_in_progress",
  "IN_PROGRESS->COMPLETED": "detail.action_mark_completed",
  "COMPLETED->IN_PROGRESS": "detail.action_reopen",
};

// W2-B fix 4 — WHICH provider workflow button is the forward action.
//
// Every status button on this card rendered `.btn-secondary`: an
// outlined box, identical for "Start review" and for "Cancel request",
// which sit one under the other at REQUESTED. Nothing on the card said
// which one moves the job on and which one throws it away.
//
// This map is the same idiom `TicketDetailPage`'s `PRIMARY_TRANSITIONS`
// uses, and it is a map rather than a rule for the same reason: "the
// forward action" is not derivable from the status pair. Two of the
// legal moves below go BACKWARD on purpose and must not be dressed as
// progress —
//
//   PRICING_PROPOSED -> UNDER_REVIEW  ("Revise pricing")  is a retreat
//     to fix a quote already shown to the customer;
//   COMPLETED -> IN_PROGRESS          ("Reopen")          is a
//     correction of work already declared finished, and it costs an
//     override reason.
//
// — while CUSTOMER_REJECTED -> UNDER_REVIEW ("Revise after rejection")
// IS the way forward from a rejection: it is how a rejected request
// becomes a live one again, and it is the only move that state offers.
//
// Entries whose target never reaches this button (PRICING_PROPOSED is
// filtered out in favour of the Proposal builder; the two customer
// decisions route through the decision/override block) are recorded
// anyway, because the record is the point: a `Record<ExtraWorkStatus,
// ...>` is exhaustive, so adding a status to the enum fails the build
// here until somebody states what its forward action is.
const PRIMARY_FORWARD_TRANSITIONS: Record<
  ExtraWorkStatus,
  ExtraWorkStatus[]
> = {
  REQUESTED: ["UNDER_REVIEW"],
  UNDER_REVIEW: ["PRICING_PROPOSED"],
  PRICING_PROPOSED: ["CUSTOMER_APPROVED"],
  CUSTOMER_APPROVED: ["IN_PROGRESS"],
  IN_PROGRESS: ["COMPLETED"],
  // Reopen is a correction, not a next step. No forward action here.
  COMPLETED: [],
  CUSTOMER_REJECTED: ["UNDER_REVIEW"],
  // Terminal.
  CANCELLED: [],
};

// The hard floor, checked SECOND and independently of the map above.
//
// The map says what IS forward; this says what can never be dressed as
// forward however the map is edited later. A cancel or a rejection
// rendered in the approving colour is a worse outcome than every button
// staying grey — the operator's hand is already moving toward the green
// one — so the guard is a separate test rather than an assumption that
// nobody will ever add "CANCELLED" to a primary list by accident.
const NEVER_PRIMARY_TARGETS: ReadonlySet<ExtraWorkStatus> = new Set<
  ExtraWorkStatus
>(["CANCELLED", "CUSTOMER_REJECTED"]);

function isForwardTarget(
  from: ExtraWorkStatus,
  target: ExtraWorkStatus,
): boolean {
  if (NEVER_PRIMARY_TARGETS.has(target)) return false;
  return (PRIMARY_FORWARD_TRANSITIONS[from] ?? []).includes(target);
}

function workflowButtonClass(
  from: ExtraWorkStatus,
  target: ExtraWorkStatus,
  { hasRepair }: { hasRepair: boolean },
): string {
  // Destructive first. `.btn-danger` is the existing soft-red token
  // pair (--red-soft / --red / --red-border); nothing new is invented
  // and nothing is hardcoded.
  if (NEVER_PRIMARY_TARGETS.has(target)) {
    return "btn btn-danger btn-sm";
  }
  // `hasRepair` is the retry-spawn case: a CUSTOMER_APPROVED request
  // with ZERO spawned operational tickets is broken data, and the
  // button that fixes it is already filled. Measured at 1440px before
  // this guard existed, CUSTOMER_APPROVED rendered "Mark in progress"
  // and "Retry scheduling work" as TWO green buttons — which says
  // "either of these" about a state where only one of them helps.
  // Advancing an Extra Work that never got its tickets only buries the
  // fault deeper, so the repair keeps the emphasis and the workflow
  // move waits its turn.
  if (hasRepair) {
    return "btn btn-secondary btn-sm";
  }
  return isForwardTarget(from, target)
    ? "btn btn-primary btn-sm"
    : "btn btn-secondary btn-sm";
}

// Forward first, cancel LAST, everything else in between.
//
// The backend hands `allowed_next_statuses` in enum order, and at
// REQUESTED that put "Cancel request" ABOVE "Start review" — measured,
// not assumed. Colour alone does not fix a running order that offers
// the destructive option first. Same reasoning as
// `TicketDetailPage.partitionTransitions`, which reorders for exactly
// this ("Approve renders above Reject on every customer-decision step,
// regardless of how the backend orders allowed_next_statuses").
function orderWorkflowTargets(
  from: ExtraWorkStatus,
  targets: ExtraWorkStatus[],
): ExtraWorkStatus[] {
  const rank = (t: ExtraWorkStatus) =>
    NEVER_PRIMARY_TARGETS.has(t) ? 2 : isForwardTarget(from, t) ? 0 : 1;
  // A stable sort, so two targets of equal rank keep the backend's
  // order rather than acquiring an arbitrary one of ours.
  return targets
    .map((t, i) => ({ t, i, r: rank(t) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((e) => e.t);
}

// Sprint 31 — one-line "what to do at this step" hint for providers,
// shown above the workflow buttons for the early steps users found
// confusing. Other statuses rely on the buttons + the dedicated
// auto-start / override hints.
const PROVIDER_STEP_HINT_I18N: Partial<Record<ExtraWorkStatus, string>> = {
  REQUESTED: "detail.step_hint_requested",
  UNDER_REVIEW: "detail.step_hint_under_review",
};

const CATEGORY_I18N_KEY: Record<ExtraWorkCategory, string> = {
  DEEP_CLEANING: "category.deep_cleaning",
  WINDOW_CLEANING: "category.window_cleaning",
  FLOOR_MAINTENANCE: "category.floor_maintenance",
  SANITARY_SERVICE: "category.sanitary_service",
  WASTE_REMOVAL: "category.waste_removal",
  FURNITURE_MOVING: "category.furniture_moving",
  EVENT_CLEANING: "category.event_cleaning",
  EMERGENCY_CLEANING: "category.emergency_cleaning",
  OTHER: "category.other",
};

const URGENCY_I18N_KEY: Record<ExtraWorkUrgency, string> = {
  NORMAL: "urgency.normal",
  HIGH: "urgency.high",
  URGENT: "urgency.urgent",
};

const PROVIDER_ROLES: Set<Role> = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
]);

// Sprint 30 Batch 30.1 — roles allowed to call POST /extra-work/<id>/spawn/.
// The backend gate is intentionally narrower than the broader provider set
// (BUILDING_MANAGER is excluded — this is a corrective admin action). The
// UI must mirror that gate exactly so the button never renders for a role
// the API will refuse anyway.
const RETRY_SPAWN_ROLES: Set<Role> = new Set(["SUPER_ADMIN", "COMPANY_ADMIN"]);

// Sprint 30 Batch 30.1 — map the backend's stable `code` field on the
// retry-spawn endpoint to a localized toast title. Any other / missing
// code falls back to the generic message.
type RetrySpawnErrorCode =
  | "spawn_wrong_status"
  | "spawn_already_done"
  | "spawn_forbidden_role"
  | "spawn_forbidden_scope"
  | "spawn_generic";

const RETRY_SPAWN_ERROR_I18N_KEY: Record<RetrySpawnErrorCode, string> = {
  spawn_wrong_status: "detail.retry_spawn_error_wrong_status",
  spawn_already_done: "detail.retry_spawn_error_already_done",
  spawn_forbidden_role: "detail.retry_spawn_error_forbidden",
  spawn_forbidden_scope: "detail.retry_spawn_error_forbidden",
  spawn_generic: "detail.retry_spawn_error_generic",
};

function retrySpawnErrorCode(err: unknown): RetrySpawnErrorCode {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data;
    if (data && typeof data === "object") {
      const code = (data as Record<string, unknown>).code;
      if (typeof code === "string") {
        switch (code) {
          case "spawn_wrong_status":
          case "spawn_already_done":
          case "spawn_forbidden_role":
          case "spawn_forbidden_scope":
            return code;
        }
      }
    }
  }
  return "spawn_generic";
}

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
// by `ew.updated_at`, so a successful save (which bumps updated_at on the
// refreshed detail) remounts the panel and re-seeds the inputs from the
// fresh `actual_hours` — no prop-derived resync effect.
// Sprint 8A-fix — normalized hourly line shape the panel renders. Both
// cart line items (label = service_name) and approved-proposal lines
// (label = service_name ?? description) map into this; `id` is the
// line_id the actual-hours endpoint accepts for whichever active set.
type ActualHoursLine = {
  id: number;
  label: string;
  actual_hours: string | null;
};

function ActualHoursPanel({
  ewId,
  hourlyLines,
  finalTotalAmount,
  locked,
  onUpdated,
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
      pushToast({
        variant: "success",
        title: t("detail.actual_hours_saved"),
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
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("detail.actual_hours_helper")}
        </p>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("detail.actual_hours_scope_note")}
        </p>
        {locked && (
          <div
            className="alert-warning"
            style={{ marginBottom: 12 }}
            data-testid="extra-work-actual-hours-locked"
          >
            {t("detail.actual_hours_error_locked")}
          </div>
        )}
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("detail.actual_hours_col_line")}</th>
              <th style={{ width: 160 }}>
                {t("detail.actual_hours_col_hours")}
              </th>
            </tr>
          </thead>
          <tbody>
            {hourlyLines.map((line) => (
              <tr key={line.id} data-testid="extra-work-actual-hours-row">
                <td>{line.label}</td>
                <td>
                  <input
                    type="number"
                    min="0"
                    step="0.25"
                    inputMode="decimal"
                    className="form-control"
                    aria-label={t("detail.actual_hours_input_aria", {
                      line: line.label,
                    })}
                    value={draft[line.id] ?? ""}
                    disabled={locked}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        [line.id]: event.target.value,
                      }))
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            marginTop: 12,
          }}
        >
          <span className="muted small">
            {t("detail.actual_hours_final_total")}{" "}
            <strong data-testid="extra-work-actual-hours-final-total">
              {finalTotalAmount ?? "—"}
            </strong>
          </span>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="extra-work-actual-hours-save"
            onClick={handleSave}
            disabled={saving || locked}
          >
            {saving
              ? t("detail.actual_hours_saving")
              : t("detail.actual_hours_save")}
          </button>
        </div>
      </div>
    </div>
  );
}

// M1 B6 — Extra Work message-thread tier vocabulary (three tiers, NO staff).
// Keys live under the `extra_work` i18n namespace (`messages.*`).
const EW_TIER_LABEL_KEY: Record<EwMessageType, string> = {
  PUBLIC_REPLY: "messages.composer_public",
  INTERNAL_NOTE: "messages.composer_internal",
  CUSTOMER_INTERNAL: "messages.composer_customer_internal",
};
const EW_TIER_PLACEHOLDER_KEY: Record<EwMessageType, string> = {
  PUBLIC_REPLY: "messages.composer_public_placeholder",
  INTERNAL_NOTE: "messages.composer_internal_placeholder",
  CUSTOMER_INTERNAL: "messages.composer_customer_internal_placeholder",
};
const EW_TIER_WHO_SEES_KEY: Record<EwMessageType, string> = {
  PUBLIC_REPLY: "messages.composer_public_who_sees",
  INTERNAL_NOTE: "messages.composer_internal_who_sees",
  CUSTOMER_INTERNAL: "messages.composer_customer_internal_who_sees",
};
const EW_TIER_BADGE_KEY: Record<EwMessageType, string> = {
  PUBLIC_REPLY: "messages.tag_public",
  INTERNAL_NOTE: "messages.tag_internal",
  CUSTOMER_INTERNAL: "messages.tag_customer_internal",
};
const EW_TIER_TONE_CLASS: Record<EwMessageType, string> = {
  PUBLIC_REPLY: "",
  INTERNAL_NOTE: "internal",
  CUSTOMER_INTERNAL: "internal",
};

// Sprint 128 — coded relabel errors → localized keys (fallback getApiError).
const LABELS_ERROR_I18N_KEY: Record<string, string> = {
  labels_locked_by_invoice: "detail.labels_error_locked",
  department_customer_mismatch: "detail.labels_error_mismatch",
  work_type_customer_mismatch: "detail.labels_error_mismatch",
  relabel_forbidden: "detail.labels_error_forbidden",
};

// Provider relabel card. When the EW is on an ISSUED invoice
// (`ew.labels_locked`) the labels are read-only text + a reason naming the
// invoice; otherwise two dropdowns + Save calling PATCH .../labels/. Options
// always include the CURRENT value so an archived label still shows.
/** Sprint 176 §3 — the deadline and the planned end, editable after the
 *  request exists.
 *
 *  Until now both were write-once on the create form. That is the wrong
 *  shape for a deadline in particular: a deadline is exactly the kind of
 *  thing agreed after the fact, once someone has looked at the job.
 *
 *  Behind an explicit Edit affordance rather than always-live inputs, so
 *  the Details card stays a card you READ and a date cannot be changed by
 *  a stray click on a page an operator opened to check something else.
 *
 *  Provider-only at the call site. The customer's `preferred_date` is
 *  shown right above and is NOT editable here — the customer states a
 *  wish, the provider answers it with a commitment.
 *
 *  Sprint 177 §2 — this component is now ONLY the open form. The trigger
 *  moved up into the deadline cell so it sits beside the date it edits,
 *  and the parent owns the open/closed state. The component is therefore
 *  mounted only while open, which is also why the drafts below can seed
 *  straight from the row in `useState` rather than needing a reset on
 *  open: a fresh mount IS the reset. */
function DatesEditor({
  ew,
  onUpdated,
  onClose,
}: {
  ew: ExtraWorkRequestDetail;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const [deadline, setDeadline] = useState(ew.deadline ?? "");
  const [plannedEnd, setPlannedEnd] = useState(ew.planned_end_date ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      // Both keys are sent deliberately: this editor SHOWS both fields, so
      // an operator who emptied one meant to clear it. The absent-key
      // "leave unchanged" path belongs to the bulk dialog, where the
      // operator is not looking at the current values.
      const updated = await updateExtraWorkDates(ew.id, {
        deadline: deadline || null,
        planned_end_date: plannedEnd || null,
      });
      onUpdated(updated);
      pushToast({ variant: "success", title: t("detail.dates_saved") });
      onClose();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="form-section" data-testid="extra-work-dates-editor">
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          gap: 8,
          marginTop: 4,
        }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="muted small">
            {t("detail.field_planned_end_date")}
          </span>
          <input
            type="date"
            className="field-input"
            value={plannedEnd}
            onChange={(e) => setPlannedEnd(e.target.value)}
            data-testid="extra-work-dates-planned-end"
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="muted small">{t("detail.deadline")}</span>
          <input
            type="date"
            className="field-input"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            data-testid="extra-work-dates-deadline"
          />
        </label>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={save}
          disabled={saving}
          data-testid="extra-work-dates-save"
        >
          {saving ? t("detail.dates_saving") : t("common:save")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onClose}
          disabled={saving}
        >
          {t("common:cancel")}
        </button>
      </div>
      {/* The customer's wish, restated beside the field that answers it —
          §3 asks for it prominently wherever a deadline is set. */}
      <div className="muted small" style={{ marginTop: 6 }}>
        {t("detail.dates_preferred_hint", {
          date: ew.preferred_date
            ? formatDate(ew.preferred_date)
            : t("detail.empty_dash"),
        })}
      </div>
      {error && (
        <div className="alert-error" style={{ marginTop: 6 }}>
          {error}
        </div>
      )}
    </div>
  );
}

/*  Sprint 189 §1 — Department and Work Type left the right-hand aside and
 *  moved INTO the Details card, in the grid cell that sat empty under
 *  Preferred Date. Two labels are not a card; they are two fields, and
 *  the Details grid is where the other fields already are.
 *
 *  So what used to be `LabelsCard` is now the editor FORM only. The two
 *  values are rendered by the parent, in the cell, with an Edit trigger
 *  beside them.
 *
 *  W2-B fix 1 moved the form into that cell. It was still a FORM: two
 *  full-width dropdowns and a button row that appeared underneath and
 *  pushed Description, the billing month, the override and routing down
 *  the page every time somebody pressed Edit.
 *
 *  W3-F — there is no form. This component renders the SAME row the
 *  read state renders, with the two values swapped for selects in the
 *  slots they already occupy and Save / Cancel standing where the Edit
 *  button stood. Nothing is added, so nothing below can move.
 *
 *  The zero-movement property is not a nice finish, it is the
 *  acceptance test, and it is held by three things together:
 *
 *    * the outer markup is identical — `.ew-labels-inline` with two
 *      label/value stacks and one action slot, in both states;
 *    * `.ew-label-value` and `.ew-label-inline-select` are pinned to the
 *      SAME fixed height in CSS, so the stacks measure the same open or
 *      closed (`box-sizing: border-box` is global, so the select's
 *      border costs nothing);
 *    * a save error goes to a TOAST, never to an inline `.alert-error`.
 *      An error banner in this cell would push the page down at the
 *      worst possible moment — while the operator is reading why their
 *      change did not land.
 *
 *  Measured both ways at 1440px; the numbers are in the sprint report.
 *
 *  Mounted only while open AND only while the labels are unlocked: a
 *  work frozen by an issued invoice has nothing to edit, and the parent
 *  cell states the lock and the way out instead. A fresh mount is the
 *  reset, which is why the drafts below seed straight from the row. */
function LabelsEditor({
  ew,
  onUpdated,
  onRefresh,
  onClose,
}: {
  ew: ExtraWorkRequestDetail;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const [departments, setDepartments] = useState<CustomerLabel[]>([]);
  const [workTypes, setWorkTypes] = useState<CustomerLabel[]>([]);
  const [deptId, setDeptId] = useState(
    ew.department ? String(ew.department) : "",
  );
  const [wtId, setWtId] = useState(ew.work_type ? String(ew.work_type) : "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listLabels(ew.customer, "department", { is_active: true }),
      listLabels(ew.customer, "work_type", { is_active: true }),
    ])
      .then(([deps, wts]) => {
        if (!cancelled) {
          setDepartments(deps);
          setWorkTypes(wts);
        }
      })
      .catch(() => {
        // A read failure just leaves the dropdowns with the current value.
      });
    return () => {
      cancelled = true;
    };
  }, [ew.customer]);

  // Ensure the CURRENT selection is offered even if it has since been
  // archived (archived rows are absent from the is_active=true fetch).
  function withCurrent(
    rows: CustomerLabel[],
    currentId: number | null,
    currentName: string | null,
  ): CustomerLabel[] {
    if (currentId == null || rows.some((r) => r.id === currentId)) return rows;
    return [
      {
        id: currentId,
        name: currentName ?? String(currentId),
        description: "",
        is_active: false,
        created_at: "",
      },
      ...rows,
    ];
  }
  const deptOptions = withCurrent(departments, ew.department, ew.department_name);
  const wtOptions = withCurrent(workTypes, ew.work_type, ew.work_type_name);

  async function save() {
    setSaving(true);
    try {
      const updated = await relabelExtraWork(ew.id, {
        department: deptId ? Number(deptId) : null,
        work_type: wtId ? Number(wtId) : null,
      });
      onUpdated(updated);
      // Sprint 129 §2b — the save was invisible before; confirm it the way
      // the actual-hours save does.
      pushToast({ variant: "success", title: t("detail.labels_saved") });
      onClose();
    } catch (err) {
      const code = labelErrorCode(err);
      // W3-F — a TOAST, not an inline banner. The banner used to render
      // inside this cell, which means a failed save pushed the whole
      // lower half of the card down while the operator was reading why
      // it failed. This cell must not change height for any reason.
      pushToast({
        variant: "error",
        title:
          code && code in LABELS_ERROR_I18N_KEY
            ? t(LABELS_ERROR_I18N_KEY[code])
            : getApiError(err),
      });
      // Raced with an issuance in another tab — reload so the cell above
      // flips to the read-only locked state (§4).
      if (code === "labels_locked_by_invoice") onRefresh();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ew-labels-inline" data-testid="extra-work-labels-editor">
      <div>
        <div className="muted small">
          {t("detail.labels_field_department")}
        </div>
        {/* In the value's slot, at the value's height. The label above
            it is the read state's own label, unchanged. */}
        <select
          className="ew-label-inline-select"
          value={deptId}
          onChange={(e) => setDeptId(e.target.value)}
          aria-label={t("detail.labels_field_department")}
          data-testid="extra-work-labels-department"
        >
          <option value="">{t("detail.labels_none")}</option>
          {deptOptions.map((d) => (
            <option key={d.id} value={d.id}>
              {customerLabelName(d.name, t)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <div className="muted small">
          {t("detail.labels_field_work_type")}
        </div>
        <select
          className="ew-label-inline-select"
          value={wtId}
          onChange={(e) => setWtId(e.target.value)}
          aria-label={t("detail.labels_field_work_type")}
          data-testid="extra-work-labels-work-type"
        >
          <option value="">{t("detail.labels_none")}</option>
          {wtOptions.map((w) => (
            <option key={w.id} value={w.id}>
              {customerLabelName(w.name, t)}
            </option>
          ))}
        </select>
      </div>
      {/* Standing exactly where the Edit button stood. Icon-only and
          `.btn-sm`, so the slot is the same height as that button and
          NARROWER than it — two labelled buttons could wrap onto a
          second line at this cell width, and a wrap is height. */}
      <div className="ew-labels-inline-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm ew-labels-icon-btn"
          disabled={saving}
          onClick={() => void save()}
          title={t("detail.labels_save")}
          aria-label={t("detail.labels_save")}
          data-testid="extra-work-labels-save"
        >
          <Check size={14} strokeWidth={2.4} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm ew-labels-icon-btn"
          onClick={onClose}
          disabled={saving}
          title={t("common:cancel")}
          aria-label={t("common:cancel")}
          data-testid="extra-work-labels-cancel"
        >
          <X size={14} strokeWidth={2.4} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}


/*  W2-B fix 2 — Customer contacts, as a panel INSIDE the Details card.
 *
 *  It was a collapsed card in the far-right rail: three columns away
 *  from the request it belongs to, closed by default, and the first
 *  thing an operator on the phone to a customer had to go hunting for.
 *  It now sits in the Details card itself, in the right-hand column
 *  beside the description / billing / routing text, open, with the
 *  count in its own header.
 *
 *  THE BOUND IS THE POINT. A customer can have dozens of contacts, and
 *  this panel is now inside the card that governs the top of the page —
 *  so an unbounded list would drag the whole page layout with it. The
 *  list scrolls inside its own box (`.ew-contacts-panel-list`,
 *  max-height in CSS) and the panel's height is therefore capped
 *  whatever the customer's address book looks like. Same rule the
 *  collapsed card relied on, kept deliberately rather than inherited by
 *  accident, and the reason CLAUDE.md's "no unbounded server list"
 *  applies here at all.
 *
 *  Every testid is verbatim from the card it replaces
 *  (`extra-work-customer-contacts-panel` / `-empty` / `-contact-row`),
 *  because `sprint28_batch15_4_detail_rebuild.spec.ts` asserts on all
 *  three and a moved panel is not a renamed one. */
function CustomerContactsPanel({ contacts }: { contacts: Contact[] }) {
  const { t } = useTranslation(["extra_work", "common"]);
  return (
    <aside
      className="ew-contacts-panel"
      data-testid="extra-work-customer-contacts-panel"
    >
      <div className="ew-contacts-panel-head">
        {/* `muted small` is the class every other label in this half of
            the card carries. Wearing it is what makes the heading line
            up with "Description" rather than merely sit near it. */}
        <span className="muted small ew-contacts-panel-title">
          {t("customer_contacts.panel_title", { ns: "common" })}
        </span>
        <span className="muted small">
          {t("detail.card_count", { count: contacts.length })}
        </span>
      </div>
      {contacts.length === 0 ? (
        <div
          className="muted small ew-contacts-panel-empty"
          data-testid="extra-work-customer-contacts-empty"
        >
          {t("customer_contacts.panel_empty", { ns: "common" })}
        </div>
      ) : (
        <ul className="ew-contacts-panel-list">
          {contacts.map((contact) => (
            <li
              key={contact.id}
              className="ew-contacts-panel-row"
              data-testid="extra-work-customer-contact-row"
            >
              {/* Name, role and reach on their own lines. Putting name
                  and role on ONE line was tried and MEASURED here, and
                  it made rows taller, not shorter: at this column width
                  (270px of content) a full name already fills the line,
                  so the pair wrapped anyway and picked up the flex gap
                  on top. Three spans it is. */}
              <span className="ew-contacts-panel-name">
                {contact.full_name}
              </span>
              {contact.role_label && (
                <span className="muted small">{contact.role_label}</span>
              )}
              {(contact.email || contact.phone) && (
                <span className="muted small ew-contacts-panel-reach">
                  {contact.email && <span>{contact.email}</span>}
                  {contact.phone && <span>{contact.phone}</span>}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

export function ExtraWorkDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const messageLocale = useLocaleCode();

  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  // Sprint 177 §2 — the dates editor is opened from a trigger that sits
  // beside the deadline, so the open state lives here rather than inside
  // the editor it opens.
  const [datesOpen, setDatesOpen] = useState(false);
  // Sprint 189 §1 — same shape for the labels editor, which now opens in
  // the same place from a trigger in the same grid.
  const [labelsOpen, setLabelsOpen] = useState(false);
  // W3-F — the plan modal. The assignment list is fetched WHEN THE
  // DIALOG OPENS rather than with the page: the backend refuses hours
  // for anybody not currently assigned, so the crew the dialog offers
  // has to be the crew as of the moment somebody plans, not as of the
  // last page load.
  const [planOpen, setPlanOpen] = useState(false);
  const [planAssignments, setPlanAssignments] = useState<
    ExtraWorkAssignment[]
  >([]);
  const [planAssignmentsLoading, setPlanAssignmentsLoading] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Sprint 28 Batch 4 — read-only Customer Contacts panel. Backend
  // `IsSuperAdminOrCompanyAdminForCompany` gate on the contacts list
  // rejects everyone else with 403; mirror the gate here so
  // BUILDING_MANAGER / CUSTOMER_USER never emit the call.
  const canSeeCustomerContacts =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";
  const [customerContacts, setCustomerContacts] = useState<Contact[]>([]);

  // Transition buttons (any role; the backend computes
  // allowed_next_statuses per actor).
  const [transitionBusy, setTransitionBusy] = useState<ExtraWorkStatus | null>(
    null,
  );

  // Provider-override block.
  const [overrideDecision, setOverrideDecision] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideError, setOverrideError] = useState("");

  // M4 (3d) — per-EW billing-month override. billingDraft=null means
  // "show ew's current value"; the input is derived at render (never synced
  // via an effect, to avoid a setState-in-effect violation).
  const [billingDraft, setBillingDraft] = useState<string | null>(null);
  const [billingSaving, setBillingSaving] = useState(false);
  const [billingError, setBillingError] = useState("");

  // Sprint 28 Batch 15.4 — customer reject-reason dialog state.
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

  // Sprint 28 Batch 15.4 — proposals list (used only to pick the
  // active proposal for the PDF download button).
  const [proposals, setProposals] = useState<Proposal[]>([]);
  // Per-record proposal actions for the DRAFT proposal — needed to
  // gate the new direct-publish button AND the read-only proposal-
  // lines section. The list endpoint above returns the lean
  // serializer (no `actions`, no `lines`); we fetch the detail
  // separately for the draft when one exists.
  const [draftProposalDetail, setDraftProposalDetail] =
    useState<ProposalDetail | null>(null);
  // Sprint 31 — proposal builder: create CTA busy/error.
  const [proposalBusy, setProposalBusy] = useState(false);
  const [proposalError, setProposalError] = useState("");
  // Sprint 188 — set once, when the create response says the parent
  // could not be advanced. Read by the builder to explain why Send is
  // not there yet, in place of the generic line.
  const [parentAdvanceBlocked, setParentAdvanceBlocked] = useState(false);
  // Direct-publish flow state.
  const [directPublishOpen, setDirectPublishOpen] = useState(false);
  const [directPublishReason, setDirectPublishReason] = useState("");
  const [directPublishBusy, setDirectPublishBusy] = useState(false);
  const [directPublishError, setDirectPublishError] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);

  // Sprint 30 Batch 30.1 — spawned tickets fetched via the new
  // server-side `extra_work_request` filter. Drives both the
  // read-only panel (between line items and actions) and the
  // cancel-confirmation warning.
  const [spawnedTickets, setSpawnedTickets] = useState<TicketList[]>([]);
  // Sprint 30 Batch 30.1 — retry-spawn button busy flag.
  const [retrySpawnBusy, setRetrySpawnBusy] = useState(false);
  // Sprint 29 Batch 29.8 — cancel-confirmation dialog. Wraps the
  // existing CANCELLED transition path so the warning about lingering
  // spawned tickets renders before the destructive action fires.
  const cancelDialogRef = useRef<ConfirmDialogHandle>(null);
  const [cancelBusy, setCancelBusy] = useState(false);

  // M1 B6 — Extra Work message thread + composer state.
  const [ewMessages, setEwMessages] = useState<EwMessage[]>([]);
  const [ewMessageText, setEwMessageText] = useState("");
  const [ewMessageType, setEwMessageType] =
    useState<EwMessageType>("PUBLIC_REPLY");
  const [ewDirectedTo, setEwDirectedTo] = useState<number[]>([]);
  const [ewIsPrivate, setEwIsPrivate] = useState(false);
  const [ewRecipients, setEwRecipients] = useState<EwMessageRecipient[]>([]);
  const [ewSending, setEwSending] = useState(false);

  // ----- load -----
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const detail = await getExtraWork(id!);
        if (!cancelled) setEw(detail);
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

  const isProvider = useMemo(
    () => !!me?.role && PROVIDER_ROLES.has(me.role),
    [me],
  );

  // `ewId` (hoisted Sprint 8A-fix) — the EW id, or null while loading.
  // Used by the actual-hours active-set logic below and the proposals /
  // spawned-tickets fetch effects further down.
  const ewId = ew?.id ?? null;

  // Sprint 8A-fix — the active hourly line set a provider can enter
  // actual hours for, following the backend `active_priced_lines`
  // precedence exactly (approved-proposal > INSTANT-cart > legacy). The
  // approved-proposal case was the P1 dead-end: its lines DO gate the
  // operational ticket's completion (`actual_hours_required`) but the
  // old INSTANT-only guard hid the entry UI.
  //
  // Approved-proposal selection mirrors `final_amounts.active_priced_lines`:
  // the latest CUSTOMER_APPROVED proposal by customer_decided_at, then by
  // id (both descending).
  const approvedProposal = useMemo(() => {
    const approved = proposals.filter(
      (p) => p.status === "CUSTOMER_APPROVED",
    );
    if (approved.length === 0) return null;
    return [...approved].sort((a, b) => {
      const ad = a.customer_decided_at ?? "";
      const bd = b.customer_decided_at ?? "";
      if (ad !== bd) return ad < bd ? 1 : -1;
      return b.id - a.id;
    })[0];
  }, [proposals]);
  const approvedProposalId = approvedProposal?.id ?? null;

  // The approved proposal's lines (with `actual_hours`) are NOT on the EW
  // detail payload — load them the same cancelled-guarded way the open
  // (DRAFT/SENT) proposal detail is fetched above.
  const [approvedProposalDetail, setApprovedProposalDetail] =
    useState<ProposalDetail | null>(null);
  const reloadApprovedProposalDetail = useCallback(async () => {
    if (ewId === null || approvedProposalId === null) return;
    try {
      const detail = await getProposalDetail(ewId, approvedProposalId);
      setApprovedProposalDetail(detail);
    } catch {
      // Keep the prior detail; a transient refresh failure must not
      // blank the panel mid-edit.
    }
  }, [ewId, approvedProposalId]);
  useEffect(() => {
    let cancelled = false;
    if (ewId === null || approvedProposalId === null) {
      queueMicrotask(() => {
        if (!cancelled) setApprovedProposalDetail(null);
      });
      return () => {
        cancelled = true;
      };
    }
    getProposalDetail(ewId, approvedProposalId)
      .then((detail) => {
        if (!cancelled) setApprovedProposalDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setApprovedProposalDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId, approvedProposalId]);

  // Normalized active hourly line set. Approved-proposal lines win;
  // otherwise the INSTANT cart lines; otherwise none.
  const activeHourlyLines = useMemo<ActualHoursLine[]>(() => {
    if (!ew) return [];
    if (approvedProposal) {
      if (!approvedProposalDetail) return []; // detail still loading
      return approvedProposalDetail.lines
        .filter(
          (line) => line.is_approved_for_spawn && line.unit_type === "HOURS",
        )
        .map((line) => ({
          id: line.id,
          label: line.service_name ?? line.description,
          actual_hours: line.actual_hours ?? null,
        }));
    }
    if (ew.routing_decision === "INSTANT") {
      return ew.line_items
        .filter((line) => line.unit_type === "HOURS")
        .map((line) => ({
          id: line.id,
          label: line.service_name,
          actual_hours: line.actual_hours,
        }));
    }
    return [];
  }, [ew, approvedProposal, approvedProposalDetail]);

  // Remount key: changes whenever the persisted actual_hours change, so
  // the panel re-seeds its inputs after a save WITHOUT a resync effect.
  // Cart case keys off the refreshed EW's updated_at; proposal case off
  // the approved lines' (id, actual_hours) signature.
  const actualHoursPanelKey = approvedProposal
    ? `prop:${approvedProposalId ?? "load"}:${activeHourlyLines
        .map((line) => `${line.id}=${line.actual_hours ?? ""}`)
        .join(",")}`
    : `cart:${ew?.updated_at ?? "none"}`;

  // Sprint 28 Batch 4 — fetch contacts when the request loads, but
  // only for admin viewers (mirrors backend gate). Failures collapse
  // silently to the empty-state panel.
  const ewCustomerId = ew?.customer ?? null;
  useEffect(() => {
    const cancelled = { current: false };
    const customerId =
      canSeeCustomerContacts && ewCustomerId ? ewCustomerId : null;
    if (customerId === null) {
      queueMicrotask(() => {
        if (!cancelled.current) setCustomerContacts([]);
      });
    } else {
      listCustomerContacts(customerId)
        .then((list) => {
          if (!cancelled.current) setCustomerContacts(list);
        })
        .catch(() => {
          if (!cancelled.current) setCustomerContacts([]);
        });
    }
    return () => {
      cancelled.current = true;
    };
  }, [canSeeCustomerContacts, ewCustomerId]);

  // Sprint 28 Batch 15.4 — proposals fetch. Failures collapse to an
  // empty list so the PDF card simply does not render. The endpoint
  // is open to both provider operators and the EW's customer-side
  // viewers, but the backend filters out DRAFT for customers.
  // (`ewId` is hoisted above the actual-hours active-set logic.)
  useEffect(() => {
    let cancelled = false;
    if (ewId === null) {
      // Defer setState to avoid the react-hooks/set-state-in-effect
      // cascading-renders warning while still emitting the reset.
      queueMicrotask(() => {
        if (!cancelled) setProposals([]);
      });
      return () => {
        cancelled = true;
      };
    }
    listProposalsForEw(ewId)
      .then((list) => {
        if (!cancelled) setProposals(list);
      })
      .catch(() => {
        if (!cancelled) setProposals([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId]);

  // M1 B6 — message thread. Composer tiers are driven by the per-record
  // `ew.actions.can_post_ew_*` flags (so the composer never offers a tier the
  // backend would reject); falls back to a role-derived 3-tier set before the
  // detail loads. Net per role: CUST = PUBLIC_REPLY + CUSTOMER_INTERNAL;
  // MGMT/SA = PUBLIC_REPLY + INTERNAL_NOTE. STAFF have no EW scope -> none.
  const ewComposerTiers = useMemo<EwMessageType[]>(() => {
    const a = ew?.actions;
    if (a) {
      const tiers: EwMessageType[] = [];
      if (a.can_post_ew_public_reply) tiers.push("PUBLIC_REPLY");
      if (a.can_post_ew_internal_note) tiers.push("INTERNAL_NOTE");
      if (a.can_post_ew_customer_internal) tiers.push("CUSTOMER_INTERNAL");
      return tiers;
    }
    if (isProviderManagementRole(me?.role))
      return ["PUBLIC_REPLY", "INTERNAL_NOTE"];
    if (isCustomerUser(me?.role)) return ["PUBLIC_REPLY", "CUSTOMER_INTERNAL"];
    return [];
  }, [ew?.actions, me?.role]);

  const effectiveEwMessageType: EwMessageType = ewComposerTiers.includes(
    ewMessageType,
  )
    ? ewMessageType
    : ewComposerTiers[0] ?? "PUBLIC_REPLY";

  // Who may make a message RESTRICTED ("Private"): provider management / SA on
  // any tier they post; a customer-side user ONLY on CUSTOMER_INTERNAL (B5
  // parity, minus staff who have no EW surface).
  const ewCanUsePrivate =
    isProviderManagementRole(me?.role) ||
    (isCustomerUser(me?.role) &&
      effectiveEwMessageType === "CUSTOMER_INTERNAL");
  const ewEffectivePrivate =
    ewCanUsePrivate && ewIsPrivate && ewDirectedTo.length > 0;

  // Load the thread, keyed on ewId (mirror the proposals-load pattern). A POST
  // does not refire this; `reloadEwMessages` is called imperatively.
  const reloadEwMessages = useCallback(() => {
    if (ewId === null) return;
    listEwMessages(ewId)
      .then((list) => setEwMessages(list))
      .catch(() => setEwMessages([]));
  }, [ewId]);

  useEffect(() => {
    let cancelled = false;
    if (ewId === null) {
      queueMicrotask(() => {
        if (!cancelled) setEwMessages([]);
      });
      return () => {
        cancelled = true;
      };
    }
    listEwMessages(ewId)
      .then((list) => {
        if (!cancelled) setEwMessages(list);
      })
      .catch(() => {
        if (!cancelled) setEwMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId]);

  // RF-1 — opening the thread marks it read for this user (advance the
  // inbox cursor) and refreshes the sidebar badge. No setState here.
  useEffect(() => {
    if (ewId === null) return;
    void markThreadRead("extra_work", ewId)
      .then(() => notifyInboxUnreadChanged())
      .catch(() => {});
  }, [ewId]);

  // Refetch the directed-recipients picker whenever the effective tier
  // changes; prune any now-invalid selection (B5 parity). setState lives in
  // the async closure (not the effect body), so no set-state-in-effect lint.
  useEffect(() => {
    if (ewId === null) return;
    let cancelled = false;
    const loadRecipients = async () => {
      try {
        const data = await getEwMessageRecipients(ewId, effectiveEwMessageType);
        if (cancelled) return;
        setEwRecipients(data);
        const validIds = new Set(data.map((r) => r.id));
        setEwDirectedTo((prev) => prev.filter((rid) => validIds.has(rid)));
      } catch {
        if (!cancelled) {
          setEwRecipients([]);
          setEwDirectedTo([]);
          setEwIsPrivate(false);
        }
      }
    };
    loadRecipients();
    return () => {
      cancelled = true;
    };
  }, [ewId, effectiveEwMessageType]);

  const toggleEwDirected = useCallback(
    (recipientId: number) => {
      setEwDirectedTo((prev) => {
        const next = prev.includes(recipientId)
          ? prev.filter((rid) => rid !== recipientId)
          : [...prev, recipientId];
        // RESTRICTED is only meaningful with >=1 target; clearing the last
        // target drops the private intent so it does not silently re-arm.
        if (next.length === 0) setEwIsPrivate(false);
        return next;
      });
    },
    [],
  );

  async function submitEwMessage(event: FormEvent) {
    event.preventDefault();
    if (!id || !ewMessageText.trim()) return;
    setEwSending(true);
    try {
      await createEwMessage(id, {
        message: ewMessageText.trim(),
        message_type: effectiveEwMessageType,
        directed_to: ewDirectedTo,
        visibility_mode: ewEffectivePrivate ? "RESTRICTED" : "NORMAL",
      });
      setEwMessageText("");
      setEwDirectedTo([]);
      setEwIsPrivate(false);
      reloadEwMessages();
      pushToast({ variant: "success", title: t("messages.posted") });
    } catch (err) {
      pushToast({ variant: "error", title: getApiError(err) });
    } finally {
      setEwSending(false);
    }
  }

  // When a DRAFT proposal exists, fetch its detail so we have
  // `actions.can_direct_publish` for the direct-publish button. The
  // list serializer omits `actions`; the detail endpoint is the only
  // wire shape that carries it. Silently collapses to `null` on 403/
  // not-found (e.g. customer-side caller cannot see DRAFT proposals).
  const draftProposal = proposals.find((p) => p.status === "DRAFT") ?? null;
  // Sprint 31 — one open proposal at a time (DRAFT or SENT). When none
  // is open the provider sees the "Prepare proposal" CTA instead.
  const hasOpenProposal = proposals.some(
    (p) => p.status === "DRAFT" || p.status === "SENT",
  );
  // Sprint 31 — the proposal currently in play: a DRAFT being built or a
  // SENT one awaiting the customer's decision. Its detail (lines +
  // actions) drives the proposal builder (edit/send for DRAFT,
  // approve/reject for SENT). `draftProposal` (DRAFT only) stays for the
  // direct-publish button, which is DRAFT-only.
  const openProposal =
    proposals.find((p) => p.status === "DRAFT" || p.status === "SENT") ?? null;
  const openProposalId = openProposal?.id ?? null;
  useEffect(() => {
    let cancelled = false;
    if (ewId === null || openProposalId === null) {
      queueMicrotask(() => {
        if (!cancelled) setDraftProposalDetail(null);
      });
      return () => {
        cancelled = true;
      };
    }
    getProposalDetail(ewId, openProposalId)
      .then((detail) => {
        if (!cancelled) setDraftProposalDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setDraftProposalDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId, openProposalId]);

  // Sprint 30 Batch 30.1 — spawned tickets fetch using the new
  // server-side `extra_work_request` filter (walks both the cart-item
  // FK chain and the proposal-line FK chain). Replaces the Sprint 29
  // Batch 29.8 client-side N+1 walk.
  //
  // Failures collapse silently to an empty list so the panel simply
  // does not render. Scope is still enforced server-side via
  // `scope_tickets_for`.
  useEffect(() => {
    let cancelled = false;
    if (ewId === null) {
      queueMicrotask(() => {
        if (!cancelled) setSpawnedTickets([]);
      });
      return () => {
        cancelled = true;
      };
    }
    listSpawnedTickets(ewId)
      .then((list) => {
        if (!cancelled) setSpawnedTickets(list);
      })
      .catch(() => {
        if (!cancelled) setSpawnedTickets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId]);

  if (loading) {
    return (
      <div>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      </div>
    );
  }

  if (error || !ew) {
    return (
      <div>
        <PageHeader
          backLink={{ to: "/extra-work", label: t("back_to_extra_work") }}
          title={t("detail.not_found")}
        />
        <EmptyState
          icon={FileSearch}
          title={t("detail.not_found")}
          description={error || undefined}
        />
      </div>
    );
  }

  const allowed = ew.allowed_next_statuses;
  // Per-record actions drive the decision UI. `ew.actions.can_approve`
  // covers both customer-direct approve and provider-override approve
  // (the backend tightens it to PRICING_PROPOSED). We split the UI
  // surface by `!isProvider` vs `providerOverrideAvailable` so the
  // customer sees plain Approve/Reject and the provider sees the
  // override-arming flow. Absent `actions` falls through to false.
  const ewActions = ew.actions;
  // Sprint 31 — the canonical Proposal builder is the single customer-decision
  // surface (its own Approve / Reject / override live on the proposal). Once a
  // proposal is open the legacy EW-level decision + override buttons must step
  // aside, so every EW-level decision const is gated on `!hasOpenProposal`.
  const canApproveAsCustomer =
    !isProvider && ewActions?.can_approve === true && !hasOpenProposal;
  const canRejectAsCustomer =
    !isProvider && ewActions?.can_reject === true && !hasOpenProposal;
  const providerOverrideAvailable =
    ewActions?.can_override_customer_decision === true && !hasOpenProposal;
  // Sprint 31 — AUTO_START "Start work": a provider can start a
  // PRICING_PROPOSED request that the customer pre-authorized
  // (request_intent == AUTO_START_AFTER_PRICING) without approval or an
  // override reason. When present, it REPLACES the override-approve
  // button (approving an auto-start request is not an override); the
  // override-reject button stays (rejection is always reasoned).
  const canAutoStart =
    isProvider && ewActions?.can_auto_start === true && !hasOpenProposal;
  // PDF read is action-driven so a BM with the prep key revoked STILL
  // sees the proposal PDF (backend invariant). Absent `actions` (older
  // response) falls back to the prior is-provider check.
  const canViewProposalPdf = ewActions
    ? ewActions.can_view_proposal_pdf
    : isProvider;
  // Proposal-preparation entry points (line-item add/edit/remove
  // form) — BM with prep revoked must lose these. Absent `actions`
  // falls back to is-provider (pre-cherry-pick behavior).
  const canPrepareProposal = ewActions
    ? ewActions.can_prepare_extra_work_proposal
    : isProvider;

  // Provider workflow buttons exclude the override targets (routed through
  // the dedicated override block below) AND PRICING_PROPOSED: pricing is now
  // driven exclusively by the canonical Proposal builder (its Send advances
  // the request to PRICING_PROPOSED), so a raw "propose price" status button
  // would be a second, conflicting pricing surface.
  const providerWorkflowTargetsUnordered = allowed.filter((s) => {
    if (s === "CUSTOMER_APPROVED" || s === "CUSTOMER_REJECTED") return false;
    if (s === "PRICING_PROPOSED") return false;
    // With an open proposal, "Revise pricing" (PRICING_PROPOSED ->
    // UNDER_REVIEW) would desync the request from its still-SENT proposal.
    // Revision in the proposal flow runs through reject -> revise-after-
    // reject instead; keep this button only for legacy (no-proposal) EWs.
    if (
      s === "UNDER_REVIEW" &&
      ew.status === "PRICING_PROPOSED" &&
      hasOpenProposal
    ) {
      return false;
    }
    return true;
  });
  // W2-B fix 4 — forward action first, cancel last. See
  // `orderWorkflowTargets`.
  const providerWorkflowTargets = orderWorkflowTargets(
    ew.status,
    providerWorkflowTargetsUnordered,
  );

  // Sprint 31 — an AUTO_START request is pre-authorized by the customer,
  // so the workflow must NOT frame the pricing step as "propose to
  // customer". The labels/hints below switch accordingly.
  const isAutoStart =
    ew.request_intent === "AUTO_START_AFTER_PRICING";

  // Sprint 31 — meaningful, step-aware label for each provider workflow
  // button (falls back to the generic "Move to <status>").
  const providerActionLabel = (target: ExtraWorkStatus): string => {
    if (target === "CANCELLED") return t("detail.action_cancel");
    const key = PROVIDER_ACTION_I18N[`${ew.status}->${target}`];
    return key
      ? t(key)
      : t("detail.workflow_move_to", { label: tStatusLabel(t, target) });
  };
  // One-line provider guidance for the current step (early steps only).
  const stepHintKey =
    isAutoStart && ew.status === "UNDER_REVIEW"
      ? "detail.step_hint_under_review_auto_start"
      : PROVIDER_STEP_HINT_I18N[ew.status];

  // Sprint 29 Batch 29.8 — non-terminal spawned tickets that will
  // outlive a CANCELLED transition (the EW cancel does not propagate
  // to its operational tickets — see brief Phase I). Drives the
  // cancel-confirmation dialog warning panel.
  const activeSpawnedTickets = spawnedTickets.filter(
    (ticket) => !TERMINAL_TICKET_STATUSES.has(ticket.status),
  );

  // Sprint 8B mirror — the actual-hours final amount is locked once any
  // spawned operational ticket is APPROVED or CLOSED (backend gate code
  // `final_amount_locked`; a REJECTED ticket does NOT lock). Derived from the
  // spawned tickets already on the page so the panel can disable its inputs +
  // Save and show the locked notice up front, instead of only surfacing it as
  // a post-Save error.
  const finalAmountLocked = spawnedTickets.some(
    (ticket) => ticket.status === "APPROVED" || ticket.status === "CLOSED",
  );

  // Sprint 30 Batch 30.1 — retry-spawn button is the recovery path
  // for EWs that landed in CUSTOMER_APPROVED with zero spawned
  // tickets (legacy data from before the auto-spawn fix shipped). The
  // backend gate matches: SUPER_ADMIN / COMPANY_ADMIN only, status
  // must be CUSTOMER_APPROVED, no tickets yet.
  const canRetrySpawn =
    !!me?.role &&
    RETRY_SPAWN_ROLES.has(me.role) &&
    ew.status === "CUSTOMER_APPROVED" &&
    spawnedTickets.length === 0;

  // Pick the currently-active proposal for PDF download. SENT and
  // CUSTOMER_APPROVED are the two "live" states; DRAFT is provider-
  // private and not downloadable until sent, CUSTOMER_REJECTED /
  // CANCELLED proposals stay accessible via the timeline but are not
  // the headline document anyone wants to grab right now. (The
  // earlier "ACCEPTED" sentinel was a stale alias — backend emits
  // CUSTOMER_APPROVED per `extra_work.models.ProposalStatus`.)
  const activeProposal = proposals.find(
    (p) => p.status === "SENT" || p.status === "CUSTOMER_APPROVED",
  );
  const hasActiveProposal = !!activeProposal;

  async function refresh() {
    if (!id) return;
    try {
      const detail = await getExtraWork(id);
      setEw(detail);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  // Sprint 31 — refetch proposals + DRAFT detail after a builder
  // mutation. Line edits don't change the proposal id (the id-keyed
  // effect won't refire), so we refetch the detail explicitly.
  async function reloadProposals() {
    if (ewId === null) return;
    try {
      const list = await listProposalsForEw(ewId);
      setProposals(list);
      const open = list.find(
        (p) => p.status === "DRAFT" || p.status === "SENT",
      );
      if (open) {
        const detail = await getProposalDetail(ewId, open.id);
        setDraftProposalDetail(detail);
      } else {
        setDraftProposalDetail(null);
      }
      // A proposal transition (Send / Approve / Reject) can advance the
      // parent EW + spawn tickets — refresh both.
      try {
        const fresh = await getExtraWork(ewId);
        setEw(fresh);
      } catch {
        // keep current ew on transient failure
      }
      await reloadSpawnedTickets();
    } catch {
      // Soft — keep current proposal state on a transient failure.
    }
  }

  // Sprint 31 — refetch spawned tickets after a transition that may
  // have spawned them (CUSTOMER_APPROVED). The load effect is keyed on
  // ewId only, so it never refires on a status change; without this the
  // "Spawned tickets" panel stays empty until a full page reload.
  async function reloadSpawnedTickets() {
    if (ewId === null) return;
    try {
      const list = await listSpawnedTickets(ewId);
      setSpawnedTickets(list);
    } catch {
      // Soft — keep the current list on a transient failure.
    }
  }

  async function handlePrepareProposal() {
    if (ewId === null) return;
    setProposalBusy(true);
    setProposalError("");
    try {
      // Empty body — the backend auto-seeds one ProposalLine per cart
      // item, pre-filling contract prices (SoT §8.3).
      const created = await createProposal(ewId);
      // Sprint 187 §2a — creating a proposal now also starts the review
      // (REQUESTED -> UNDER_REVIEW), which is what makes Send reachable
      // whichever way the operator arrived. When the actor was not
      // permitted to move the parent, the proposal is still created and
      // the backend hands back the reason rather than failing silently.
      // `reloadProposals()` re-reads the proposal WITHOUT this field, so
      // it is captured here, at the one moment it exists.
      //
      // Sprint 188 — it used to go into `proposalError`, whose only
      // render site is the prepare-proposal card; `reloadProposals()`
      // below makes a proposal exist, the card unmounts, and the message
      // was gone in the same tick. It also arrived as raw backend
      // English. It is now a flag carried into the builder, which says
      // the actionable thing in the user's own language.
      setParentAdvanceBlocked(Boolean(created.parent_advance_blocked));
      await reloadProposals();
    } catch (err) {
      setProposalError(getApiError(err));
    } finally {
      setProposalBusy(false);
    }
  }

  async function handleTransition(target: ExtraWorkStatus) {
    if (!id) return;
    setError("");
    setTransitionBusy(target);
    try {
      const updated = await transitionExtraWork(id, { to_status: target });
      setEw(updated);
      // Reaching CUSTOMER_APPROVED (incl. the AUTO_START "Start work")
      // spawns operational tickets — refresh the panel so they appear
      // without a page reload.
      void reloadSpawnedTickets();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setTransitionBusy(null);
    }
  }

  async function handleCustomerDecision(
    target: "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED",
    rejectReason?: string,
  ) {
    if (!id) return;
    setError("");
    setTransitionBusy(target);
    try {
      const updated = await transitionExtraWork(id, {
        to_status: target,
        // Backend requires customer_reject_reason on CUSTOMER_USER ->
        // CUSTOMER_REJECTED; always thread it when set so the wire
        // shape matches the validator regardless of target.
        ...(rejectReason !== undefined
          ? { customer_reject_reason: rejectReason }
          : {}),
      });
      setEw(updated);
      void reloadSpawnedTickets();
      // Sprint 30 Batch 30.1 — customer-side approve confirmation toast.
      // The backend auto-spawns tickets on this transition (when every
      // line resolves to an agreed price); the toast tells the customer
      // the provider will schedule the work shortly so they don't sit
      // staring at a screen wondering whether their click landed.
      if (target === "CUSTOMER_APPROVED") {
        pushToast({
          variant: "success",
          title: t("detail.customer_decision_approve_success"),
        });
      }
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setTransitionBusy(null);
    }
  }

  // Sprint 30 Batch 30.1 — provider-only retry of the legacy spawn
  // helper. Renders when the EW is stuck in CUSTOMER_APPROVED with
  // zero spawned tickets (legacy data from before the auto-spawn
  // fix shipped). The backend still re-validates role + status +
  // emptiness; this handler maps the stable `code` field to a
  // localized toast on failure.
  /** W3-F — open the plan modal, reading the crew as of NOW.
   *
   *  The assignment list is the dialog's row source because the backend
   *  refuses hours for anybody not currently assigned, and refuses them
   *  with the same body it uses for an id that does not exist — so a
   *  client working from a stale list would produce a 400 nobody could
   *  explain from the screen. A read failure leaves the crew empty,
   *  which renders the "assign somebody first" state rather than a
   *  half-built grid.
   */
  async function openPlan() {
    setPlanError("");
    setPlanAssignments([]);
    setPlanAssignmentsLoading(true);
    setPlanOpen(true);
    try {
      const rows = await listExtraWorkAssignments(Number(id));
      setPlanAssignments(rows);
    } catch {
      setPlanAssignments([]);
    } finally {
      setPlanAssignmentsLoading(false);
    }
  }

  /** Plan and start. One call, and the response IS the refreshed detail
   *  (with a `plan` block attached), so the page does not re-fetch.
   *
   *  `plan.warnings` carries the overrun. It is surfaced as a toast and
   *  it is NOT an error: the save has already happened by the time the
   *  warning exists, and `planned_hours_overrun` on the refreshed detail
   *  keeps it on the page afterwards. */
  async function submitPlan(payload: ExtraWorkPlanPayload) {
    setPlanBusy(true);
    setPlanError("");
    try {
      const updated = await planExtraWork(Number(id), payload);
      setEw(updated);
      setPlanOpen(false);
      pushToast({ variant: "success", title: t("plan.saved") });
      const overrun = updated.plan?.warnings?.[0];
      if (overrun) {
        pushToast({
          variant: "warning",
          title: t("plan.overrun_title", { over: overrun.over_by }),
        });
      }
      // A start that could not happen is a NORMAL outcome once the work
      // has an operational ticket driving its status — reported, not
      // raised, and the plan landed either way. Saying so beats leaving
      // the operator to notice the status did not move.
      if (updated.plan && !updated.plan.started) {
        pushToast({ variant: "info", title: t("plan.not_started_notice") });
      }
    } catch (err) {
      setPlanError(getApiError(err));
    } finally {
      setPlanBusy(false);
    }
  }

  async function handleRetrySpawn() {
    if (!ew) return;
    setRetrySpawnBusy(true);
    try {
      const result = await retrySpawnTicketsForExtraWork(ew.id);
      // i18next plural — picks `_one` / `_other` from the `count`.
      pushToast({
        variant: "success",
        title: t("detail.retry_spawn_success", { count: result.count }),
      });
      // Refresh the EW + spawned tickets so the panel renders the
      // new rows and the retry button gates itself off.
      await refresh();
      try {
        const list = await listSpawnedTickets(ew.id);
        setSpawnedTickets(list);
      } catch {
        // Non-fatal — the panel just won't update until the user
        // refreshes the page.
      }
    } catch (err) {
      const code = retrySpawnErrorCode(err);
      const titleKey = RETRY_SPAWN_ERROR_I18N_KEY[code];
      pushToast({
        variant: "error",
        title: t(titleKey),
      });
    } finally {
      setRetrySpawnBusy(false);
    }
  }

  async function handleOverrideSubmit(event: FormEvent) {
    event.preventDefault();
    if (!id || !overrideDecision) return;
    if (!overrideReason.trim()) {
      setOverrideError(t("detail.override_reason_required"));
      return;
    }
    setOverrideError("");
    setOverrideBusy(true);
    try {
      const updated = await transitionExtraWork(id, {
        to_status: overrideDecision,
        is_override: true,
        override_reason: overrideReason.trim(),
      });
      setEw(updated);
      setOverrideDecision(null);
      setOverrideReason("");
      // Override-approve reaches CUSTOMER_APPROVED → tickets spawn.
      void reloadSpawnedTickets();
    } catch (err) {
      setOverrideError(getApiError(err));
    } finally {
      setOverrideBusy(false);
    }
  }

  // Direct-publish a DRAFT proposal. Endpoint is atomic on the backend:
  // it runs DRAFT->SENT, then SENT->CUSTOMER_APPROVED as a provider
  // override, then spawns operational tickets — all in one transaction
  // that rolls back if any step fails. Bypasses customer approval, so
  // the UI must collect a non-empty override_reason and warn the
  // operator explicitly before submitting.
  async function handleDirectPublish() {
    if (!id || !draftProposal || !draftProposal.id) return;
    const reason = directPublishReason.trim();
    if (!reason) {
      setDirectPublishError(t("detail.direct_publish_reason_required"));
      return;
    }
    setDirectPublishError("");
    setDirectPublishBusy(true);
    try {
      await directPublishProposal(id, draftProposal.id, {
        override_reason: reason,
      });
      // Reload EW + proposal list so the new CUSTOMER_APPROVED state
      // + spawned tickets reflect. Do NOT optimistically mutate
      // anything — defer to the refreshed wire response.
      await refresh();
      const refreshedProposals = await listProposalsForEw(id);
      setProposals(refreshedProposals);
      setDirectPublishOpen(false);
      setDirectPublishReason("");
      pushToast({
        variant: "success",
        title: t("detail.direct_publish_success"),
      });
    } catch (err) {
      setDirectPublishError(getApiError(err));
    } finally {
      setDirectPublishBusy(false);
    }
  }

  // Sprint 29 Batch 29.8 — cancel-confirmation handler. Fires the
  // standard CANCELLED transition once the operator confirms in the
  // dialog. The backend still gates the transition itself; this is
  // only the UI safety net (warn about spawned tickets that will
  // outlive the cancel).
  async function handleConfirmCancel() {
    if (!id) return;
    setCancelBusy(true);
    try {
      const updated = await transitionExtraWork(id, {
        to_status: "CANCELLED",
      });
      setEw(updated);
      cancelDialogRef.current?.close();
    } catch (err) {
      setError(getApiError(err));
      cancelDialogRef.current?.close();
    } finally {
      setCancelBusy(false);
    }
  }

  async function handleDownloadPdf() {
    if (!ew || !activeProposal) return;
    setPdfBusy(true);
    try {
      const blob = await fetchProposalPdf(ew.id, activeProposal.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `proposal-${activeProposal.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setPdfBusy(false);
    }
  }

  async function saveBillingMonth() {
    if (!id) return;
    const month =
      billingDraft ?? (ew?.invoice_date ? ew.invoice_date.slice(0, 7) : "");
    if (!month) return;
    setBillingSaving(true);
    setBillingError("");
    try {
      const updated = await updateExtraWorkBilling(id, {
        invoice_date: `${month}-01`,
      });
      setEw(updated);
      setBillingDraft(null);
    } catch (err) {
      setBillingError(getApiError(err));
    } finally {
      setBillingSaving(false);
    }
  }
  async function clearBillingMonth() {
    if (!id) return;
    setBillingSaving(true);
    setBillingError("");
    try {
      const updated = await updateExtraWorkBilling(id, { invoice_date: null });
      setEw(updated);
      setBillingDraft(null);
    } catch (err) {
      setBillingError(getApiError(err));
    } finally {
      setBillingSaving(false);
    }
  }

  return (
    <div data-testid="extra-work-detail-page">
      <PageHeader
        backLink={{ to: "/extra-work", label: t("back_to_extra_work") }}
        title={ew.title}
        meta={
          <div className="ew-detail-header-meta">
            {/* Sprint 183 §3 — an extra work that WENT OPERATIONAL shows
                its TICKET's status here, exactly as its row already does
                in the list (Sprint 181 §1). Same component, same
                resolver, same string, same colour.

                The owner, twice: "an extra work that went operational
                has a ticket page and an extra work page. The statuses
                must be identical — not similar, identical — and come
                from the same place."

                They did not. The list learned to read the ticket in
                Sprint 181; this page was left reading `ew.status`, so
                one screen said "Price approved" while the other said
                "Open" about the same job. The extra work's own status is
                the COMMERCIAL state and remains the truth for anything
                not yet started; once a ticket exists, the ticket is what
                is happening.

                Nothing about the extra work's status is CHANGED — this
                is a display change to this one block, which is all this
                branch may touch in this file. */}
            <StatusBadge
              status={
                ew.spawned_tickets.length > 0
                  ? { kind: "ticket", value: ew.spawned_tickets[0].status }
                  : { kind: "extra-work", value: ew.status }
              }
              testId="extra-work-header-status"
            />
            {/* Sprint 182 §3 — the money, beside the status.
                The owner: "when I open an extra work from Chargeable
                work, show me its money too — the way the row does."
                It WAS on this page, in the meta line of a collapsed
                card near the bottom, and only once a final amount
                existed — so a priced-but-not-yet-finished request
                showed an amount in the list and nothing at all here.

                `rowAmounts` is the one billing-total rule (CLAUDE.md:
                final-with-quoted-fallback), and `formatMoney` is the
                list's own formatter, so this figure is the row's figure
                — same number, same rounding, same currency. */}
            <span
              className="cell-tag cell-tag-muted"
              data-testid="extra-work-header-total"
              title={t("detail.header_total_hint")}
            >
              {t("list.column_total")}:{" "}
              {ew.is_priced === false
                ? "\u2014"
                : formatMoney(rowAmounts(ew).total)}
            </span>
            {/* Sprint 174 §3 — the deadline and started-early markers
                live in the HEADER, beside the status. A warning you
                have to open a collapsed card to find is not a warning.
                Both use the status colours this app already has: a
                second colour vocabulary for "something is wrong" is how
                two screens end up disagreeing about severity. */}
            {ew.deadline && (
              <span
                className={`cell-tag ${
                  ew.is_overdue ? "cell-tag-rejected" : "cell-tag-muted"
                }`}
                data-testid="ew-header-deadline"
              >
                {t("detail.deadline")}: {formatDate(ew.deadline)}
                {ew.is_overdue ? ` — ${t("list.overdue")}` : ""}
              </span>
            )}
            {ew.started_before_plan && (
              <span
                className="cell-tag cell-tag-open"
                title={t("list.startedEarlyWhy")}
                data-testid="ew-header-started-early"
              >
                {t("list.startedEarly")}
              </span>
            )}
            <RouteBadge value={ew.routing_decision} />
            <span className="muted small">
              {/* Sprint 144 §1 — the real classifier when the request
                  has one, the enum label for a pre-144 row. */}
              {extraWorkCategoryName(ew) ??
                `${t(CATEGORY_I18N_KEY[ew.category] ?? ew.category)}${
                  ew.category === "OTHER" && ew.category_other_text
                    ? ` — ${ew.category_other_text}`
                    : ""
                }`}
            </span>
            <span className="muted small">
              · {t(URGENCY_I18N_KEY[ew.urgency] ?? ew.urgency)}
            </span>
          </div>
        }
      />

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Main content. The top row places Details (left, larger
          share) and the WORKFLOW card (right, smaller share) side
          by side as two distinct cards that together span the full
          page-content width. The action buttons that briefly lived
          in the page header (commit 04bf53b) move back into the
          Workflow card here. The provider-override two-press flow
          renders its reason form INLINE inside the Workflow card
          next to the armed button (preserves spatial association). */}
      <div className="ew-detail-main">
          <div className="ew-detail-top-row">
            {/* ----- Core details ----- */}
            <div className="card">
              <div className="form-section">
                <div className="form-section-title">
                  {t("detail.details_section_title")}
                </div>
              {/* W4-N fix 1 - the Details card is THREE columns, and the
                  third one starts at the TOP.

                  W2-B put Customer contacts beside the DESCRIPTION and
                  W3-F kept it there, which meant the contacts heading
                  began level with "Description" - most of a card below
                  "Building". The owner asked for it beside the whole
                  card. So the split moved up: the two fact grids, the
                  dates editor and the run of prose are now one left
                  column, and contacts is a sibling column of the same
                  wrapper. The acceptance number is that the top of the
                  contacts block and the top of the "Building" label are
                  the same Y, which they are because both are the first
                  child of row one of an `align-items: start` grid.

                  `.ew-detail-cols-main` carries `.form-section`'s own
                  `flex-direction: column; gap: 16px`, so every vertical
                  distance inside the left column is the one it had when
                  these blocks were direct children of the section. */}
              <div className="ew-detail-cols">
                <div className="ew-detail-cols-main">
              <div className="form-2col">
                <div>
                  <div className="muted small">{t("detail.field_building")}</div>
                  <div>{ew.building_name}</div>
                </div>
                <div>
                  <div className="muted small">{t("detail.field_customer")}</div>
                  <div>{ew.customer_name}</div>
                </div>
                {/* Sprint 180 §3 — who pays, next to the two names it
                    chooses between. Read-only here: the value is set on
                    the create form and the Extra Work ViewSet has no
                    update action, so an editable control would be a
                    promise no endpoint keeps. */}
                <div>
                  <div className="muted small">
                    {t("detail.field_billed_to")}
                  </div>
                  <div data-testid="extra-work-billed-to">
                    {ew.billed_to === "CUSTOMER"
                      ? t("billed_to.customer")
                      : t("billed_to.building")}
                  </div>
                </div>
                {/* Sprint 180 §2 — the ticket this Extra Work became.
                    The ticket page has shown its Extra Work origin for
                    sprints; the reverse had no field at all. The panel
                    lower down lists every spawned ticket with its
                    status; this cell answers "did this become work, and
                    which one" without scrolling for it. */}
                <div>
                  <div className="muted small">{t("detail.field_ticket")}</div>
                  <div data-testid="extra-work-ticket-link">
                    {/* Sprint 181 §1b — one renderer, with a real
                        separator. `max` is higher here than in the list
                        because this is the page somebody opens to see
                        all of them. */}
                    <SpawnedTicketLinks
                      tickets={ew.spawned_tickets}
                      max={4}
                      emptyLabel={t("detail.ticket_none")}
                    />
                  </div>
                </div>
                {/* Sprint 181 §1 — the operational state, and where it
                    comes from. When a ticket exists this IS the ticket's
                    status, with the number beside it so nobody wonders
                    where the value came from, or why the workflow
                    buttons below no longer offer to move it. The Extra
                    Work's own status stays on this page (the Workflow
                    card) for an operator debugging a stuck row — the
                    LIST is where one status had to win. */}
                {ew.spawned_tickets.length > 0 && (
                  <div>
                    <div className="muted small">
                      {t("detail.operational_state")}
                    </div>
                    <div data-testid="extra-work-operational-state">
                      <StatusBadge
                        status={{
                          kind: "ticket",
                          value: ew.spawned_tickets[0].status,
                        }}
                      />
                    </div>
                    <div className="muted small" style={{ marginTop: 4 }}>
                      {t("detail.operational_state_hint", {
                        ticket:
                          ew.spawned_tickets[0].ticket_no ??
                          `#${ew.spawned_tickets[0].id}`,
                      })}
                    </div>
                  </div>
                )}
              </div>
              <div className="form-2col">
                <div>
                  <div className="muted small">
                    {t("detail.field_requested_at")}
                  </div>
                  <div>{formatDateTime(ew.requested_at)}</div>
                </div>
                <div>
                  <div className="muted small">
                    {t("detail.field_preferred_date")}
                  </div>
                  <div data-testid="extra-work-planned-window">
                    {/* Sprint 177 §1 — all FOUR cases, not two ternaries
                        that read as a range with one end missing. An end
                        without a start used to print "— – 16 Aug 2026". */}
                    {formatPlannedWindow(
                      ew.preferred_date,
                      ew.planned_end_date,
                      formatDate,
                      {
                        empty: t("detail.empty_dash"),
                        endOnly: (end) =>
                          t("detail.planned_window_until", { date: end }),
                      },
                    )}
                  </div>
                </div>
                <div>
                  <div className="muted small">{t("detail.deadline")}</div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      flexWrap: "wrap",
                    }}
                  >
                    <span>
                      {ew.deadline
                        ? formatDate(ew.deadline)
                        : t("detail.empty_dash")}
                    </span>
                    {/* Sprint 177 §2 — the trigger sits BESIDE the date it
                        edits, in the same cell, rather than floating in its
                        own row under the whole grid where the owner could
                        not find it. Sprint 176 §3's rule is unchanged:
                        provider-only, and `preferred_date` (the customer's
                        wish, one cell to the left) is not editable here. */}
                    {isProvider && !datesOpen && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setDatesOpen(true)}
                        data-testid="extra-work-dates-edit"
                      >
                        <Pencil size={13} strokeWidth={2} />
                        {t("detail.dates_edit")}
                      </button>
                    )}
                  </div>
                </div>
                {/* Sprint 189 §1 — Department and Work Type, in the cell
                    that was empty. This grid is two columns and held
                    three cells, so the fourth slot — directly under
                    Preferred Date — rendered as blank surface. The two
                    labels used to be a collapsed card in the right-hand
                    aside, two clicks and a scroll away from the card
                    that carries every other field of the same kind.

                    Provider-only, exactly as the aside card was: a
                    customer response carries no labels UI and this cell
                    does not invent one. */}
                {isProvider && (
                  <div data-testid="extra-work-labels">
                    {/* W3-F — ONE of two rows, never a row plus a form.
                        Both branches render the same `.ew-labels-inline`
                        shape: two label/value stacks and one action
                        slot. The editor swaps the values for selects of
                        the same pinned height and the Edit button for
                        Save / Cancel of the same `.btn-sm` height, so
                        the cell measures identically in both states and
                        nothing below it can move. */}
                    {labelsOpen && !ew.labels_locked ? (
                      <LabelsEditor
                        key={`labels-${ew.id}-${ew.department ?? ""}-${
                          ew.work_type ?? ""
                        }`}
                        ew={ew}
                        onUpdated={(detail) => setEw(detail)}
                        onRefresh={() => void refresh()}
                        onClose={() => setLabelsOpen(false)}
                      />
                    ) : (
                    <div className="ew-labels-inline">
                      <div>
                        <div className="muted small">
                          {t("detail.labels_field_department")}
                        </div>
                        <div
                          className="ew-label-value"
                          data-testid="extra-work-labels-department-value"
                        >
                          {ew.department_name
                            ? customerLabelName(ew.department_name, t)
                            : t("detail.empty_dash")}
                        </div>
                      </div>
                      <div>
                        <div className="muted small">
                          {t("detail.labels_field_work_type")}
                        </div>
                        <div
                          className="ew-label-value"
                          data-testid="extra-work-labels-work-type-value"
                        >
                          {ew.work_type_name
                            ? customerLabelName(ew.work_type_name, t)
                            : t("detail.empty_dash")}
                        </div>
                      </div>
                      {/* The trigger sits beside the values it edits, the
                          same idiom as the deadline cell to the left. */}
                      {!ew.labels_locked && (
                        <div className="ew-labels-inline-actions">
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm ew-labels-icon-btn"
                            onClick={() => setLabelsOpen(true)}
                            title={t("detail.labels_edit")}
                            aria-label={t("detail.labels_edit")}
                            data-testid="extra-work-labels-edit"
                          >
                            <Pencil size={13} strokeWidth={2} />
                          </button>
                        </div>
                      )}
                    </div>
                    )}
                    {/* Frozen by an issued invoice — there is nothing to
                        edit, so the reason and the way out take the
                        trigger's place rather than hiding behind a dead
                        button. Same two sentences the card showed. */}
                    {ew.labels_locked && (
                      <div
                        className="muted small"
                        data-testid="extra-work-labels-locked"
                        style={{ marginTop: 4 }}
                      >
                        <div>
                          {/* Sprint 129 §2b — the backend sends the NUMBER
                              or null; the frontend owns the wording (no
                              "CONCEPT" leak). Null = an issued-but-not-yet-
                              sent invoice, which has no number. */}
                          {ew.labels_locked_invoice
                            ? t("detail.labels_locked_by", {
                                number: ew.labels_locked_invoice,
                              })
                            : t("detail.labels_locked_by_unsent")}
                        </div>
                        <div>{t("detail.labels_locked_howto")}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
              {/* The form itself opens BELOW the grid, where it has room for
                  two date inputs, the customer's preferred date and an
                  error, without reflowing the three cells above it. */}
              {isProvider && datesOpen && (
                <DatesEditor
                  ew={ew}
                  onUpdated={(detail) => setEw(detail)}
                  onClose={() => setDatesOpen(false)}
                />
              )}
              {/* The run of text the card has always ended with
                  (description, the notes, the billing month and its
                  override, routing). It stays a flex column of its own
                  so its fields keep their 16px rhythm; what changed in
                  W4-N is only that it is no longer the thing Customer
                  contacts is aligned to. */}
                <div className="ew-detail-body-main">
                  <div className="field">
                    <div className="muted small">{t("detail.field_description")}</div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{ew.description}</div>
                  </div>
                  {ew.customer_visible_note && (
                    <div className="field">
                      <div className="muted small">
                        {t("detail.field_customer_visible_note")}
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>
                        {ew.customer_visible_note}
                      </div>
                    </div>
                  )}
                  {ew.pricing_note && (
                    <div className="field">
                      <div className="muted small">
                        {t("detail.field_pricing_note")}
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{ew.pricing_note}</div>
                    </div>
                  )}
                  {/* Provider-internal fields — never present on customer
                      responses, so the conditional check is a no-op for
                      customer users. */}
                  {isProvider && ew.manager_note && (
                    <div className="field">
                      <div className="muted small">
                        {t("detail.field_manager_note")}
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{ew.manager_note}</div>
                    </div>
                  )}
                  {isProvider && ew.internal_cost_note && (
                    <div className="field">
                      <div className="muted small">
                        {t("detail.field_internal_cost_note")}
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>
                        {ew.internal_cost_note}
                      </div>
                    </div>
                  )}
                  {isProvider && ew.override_at && (
                    <div className="alert-warning" style={{ marginTop: 12 }}>
                      <strong>{t("detail.override_applied")}</strong>
                      {ew.override_reason && (
                        <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>
                          {ew.override_reason}
                        </div>
                      )}
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {formatDateTime(ew.override_at)}
                      </div>
                    </div>
                  )}

                  {isProvider && (
                    <div
                      className="field"
                      data-testid="extra-work-billing-override"
                    >
                      <div className="muted small">
                        {t("detail.billing_section_title")}
                      </div>
                      <div>
                        {ew.invoice_date
                          ? t("detail.billing_overridden", {
                              month: ew.invoice_date.slice(0, 7),
                            })
                          : t("detail.billing_default")}
                      </div>
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {ew.is_invoiced
                          ? t("detail.billing_invoiced_on", {
                              date: ew.invoiced_at
                                ? formatDateTime(ew.invoiced_at)
                                : "—",
                            })
                          : t("detail.billing_not_invoiced")}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          alignItems: "flex-end",
                          gap: 8,
                          marginTop: 8,
                        }}
                      >
                        <label
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 4,
                          }}
                        >
                          <span className="muted small">
                            {t("detail.billing_month_input_label")}
                          </span>
                          <input
                            type="month"
                            className="field-input"
                            value={
                              billingDraft ??
                              (ew.invoice_date ? ew.invoice_date.slice(0, 7) : "")
                            }
                            onChange={(e) => setBillingDraft(e.target.value)}
                          />
                        </label>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={
                            billingSaving ||
                            !(
                              billingDraft ??
                              (ew.invoice_date ? ew.invoice_date.slice(0, 7) : "")
                            )
                          }
                          onClick={saveBillingMonth}
                        >
                          {t("detail.billing_save")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={billingSaving || !ew.invoice_date}
                          onClick={clearBillingMonth}
                        >
                          {t("detail.billing_use_completion")}
                        </button>
                      </div>
                      {billingError && (
                        <div className="alert-error" style={{ marginTop: 8 }}>
                          {billingError}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Sprint 28 Batch 6 — routing decision text+testid (the
                      badge itself is now in the page header). Kept as a
                      named field so the locked testid keeps resolving. */}
                  <div className="field">
                    <div className="muted small">
                      {t("detail.routing_decision_label")}
                    </div>
                    <div data-testid="extra-work-detail-routing-decision">
                      {ew.routing_decision === "INSTANT"
                        ? t("detail.routing_decision_instant")
                        : t("detail.routing_decision_proposal")}
                    </div>
                  </div>
                  {/* W3-F — the plan, read back. Renders nothing at all
                      until there IS a plan, so an unplanned job is not
                      given an empty block to explain. Provider-only for
                      the same reason the button is. */}
                  {isProvider && <PlanSummary ew={ew} />}
                </div>
                </div>
                {/* Customer contacts is SUPER_ADMIN / COMPANY_ADMIN only
                    (it mirrors a backend 403). When it is absent
                    `.ew-detail-cols-main:only-child` spans both columns,
                    so a building manager or a customer user gets the
                    full-width card they had rather than a narrowed one
                    with dead space beside it. */}
                {canSeeCustomerContacts && (
                  <CustomerContactsPanel contacts={customerContacts} />
                )}
              </div>
            </div>
          </div>

          {/* ----- WORKFLOW card. Holds every action button that
              previously lived on the right-hand <aside> (and then
              briefly in the page header per commit 04bf53b). Buttons
              are stacked vertically, full-width. The provider-override
              two-press flow renders its reason form INLINE underneath
              the armed Approve/Reject button so the spatial chain
              "press → reason appears next to it" is preserved.
              Carries the `extra-work-detail-actions` testid + aria-
              label so the Sprint 28 Batch 15.4 visibility spec still
              resolves. Every onClick + disabled/loading expression +
              testid is verbatim from the previous header-actions
              cluster (and from the original aside before that). */}
          <div
            className="card ew-workflow-card"
            data-testid="extra-work-detail-actions"
            aria-label={t("detail.actions_aria_label")}
          >
            <div className="form-section">
              <div className="ew-detail-actions-section-title">
                {t("detail.actions_workflow_title")}
              </div>
              {isProvider && stepHintKey && (
                <p
                  className="muted small"
                  style={{ margin: "0 0 10px" }}
                  data-testid="extra-work-workflow-step-hint"
                >
                  {t(stepHintKey)}
                </p>
              )}
              <div className="ew-workflow-actions">
                {/* W3-F — the entry point to the planning layer W2-D
                    built. Provider-only, and it rides the page's
                    existing `isProvider` check rather than inventing a
                    role rule of its own: the endpoint refuses any other
                    role at the door with `plan_provider_only`, and the
                    four planning fields are stripped from a customer's
                    response anyway. First in the list because on an
                    approved job planning IS the next thing to do. */}
                {isProvider && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => void openPlan()}
                    data-testid="extra-work-plan-button"
                  >
                    <CalendarClock size={14} strokeWidth={2.2} aria-hidden="true" />
                    {t("plan.open_button")}
                  </button>
                )}
                {canAutoStart && (
                  <div
                    className="ew-auto-start"
                    data-testid="extra-work-auto-start"
                  >
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={transitionBusy !== null}
                      onClick={() => handleTransition("CUSTOMER_APPROVED")}
                      data-testid="extra-work-auto-start-button"
                    >
                      {transitionBusy === "CUSTOMER_APPROVED"
                        ? t("detail.auto_start_busy")
                        : t("detail.auto_start_button")}
                    </button>
                    <p className="muted small" style={{ margin: "6px 0 0" }}>
                      {t("detail.auto_start_hint")}
                    </p>
                  </div>
                )}
                {canApproveAsCustomer && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={transitionBusy !== null}
                    onClick={() =>
                      handleCustomerDecision("CUSTOMER_APPROVED")
                    }
                    data-testid="extra-work-customer-approve"
                  >
                    {transitionBusy === "CUSTOMER_APPROVED"
                      ? t("detail.workflow_approving")
                      : t("detail.workflow_approve_button")}
                  </button>
                )}
                {canRejectAsCustomer && (
                  <button
                    type="button"
                    /* W2-B fix 4 — one treatment for every action that
                       says no, so none of them can be mistaken for the
                       green one next to it. */
                    className="btn btn-danger btn-sm"
                    disabled={transitionBusy !== null}
                    onClick={() => setRejectDialogOpen(true)}
                    data-testid="extra-work-customer-reject"
                  >
                    {transitionBusy === "CUSTOMER_REJECTED"
                      ? t("detail.workflow_rejecting")
                      : t("detail.workflow_reject_button")}
                  </button>
                )}
                {isProvider &&
                  providerWorkflowTargets.map((target) => (
                    <button
                      key={target}
                      type="button"
                      /* W2-B fix 4 — filled green for the forward move,
                         soft red for cancel, outlined for everything
                         else. See `workflowButtonClass`. */
                      className={workflowButtonClass(ew.status, target, {
                        hasRepair: canRetrySpawn,
                      })}
                      disabled={transitionBusy !== null}
                      onClick={() => {
                        // Sprint 29 Batch 29.8 — CANCELLED still
                        // routes through the confirmation dialog so
                        // the spawned-tickets warning renders before
                        // the destructive transition fires.
                        if (target === "CANCELLED") {
                          cancelDialogRef.current?.open();
                          return;
                        }
                        void handleTransition(target);
                      }}
                      data-testid={
                        target === "CANCELLED"
                          ? "extra-work-cancel-button"
                          : undefined
                      }
                    >
                      {transitionBusy === target
                        ? t("detail.workflow_working")
                        : providerActionLabel(target)}
                    </button>
                  ))}
                {providerOverrideAvailable &&
                  (["CUSTOMER_APPROVED", "CUSTOMER_REJECTED"] as const)
                    .filter((target) => allowed.includes(target))
                    // AUTO_START replaces the override-approve with the
                    // no-reason "Start work" button above; keep reject.
                    .filter(
                      (target) =>
                        !(canAutoStart && target === "CUSTOMER_APPROVED"),
                    )
                    .map((target) => {
                      const isArmed = overrideDecision === target;
                      return (
                        <div
                          key={target}
                          className="workflow-override-target"
                          data-testid={`extra-work-override-${target}`}
                        >
                          <button
                            type="button"
                            /* W2-B fix 4 — this pair is the sharpest
                               case on the page: two buttons, one above
                               the other, one of which approves on the
                               customer's behalf. Filled green and soft
                               red, never two outlines. */
                            className={
                              target === "CUSTOMER_APPROVED"
                                ? "btn btn-primary btn-sm"
                                : "btn btn-danger btn-sm"
                            }
                            onClick={() => {
                              setOverrideDecision(target);
                              setOverrideError("");
                            }}
                            data-testid={`extra-work-provider-${
                              target === "CUSTOMER_APPROVED"
                                ? "approve"
                                : "reject"
                            }`}
                            aria-expanded={isArmed}
                            disabled={overrideBusy}
                          >
                            {target === "CUSTOMER_APPROVED"
                              ? t("detail.workflow_approve_button")
                              : t("detail.workflow_reject_button")}
                          </button>
                          {isArmed && (
                            <div
                              className="workflow-override-inline"
                              data-testid="extra-work-override-modal"
                            >
                              <form onSubmit={handleOverrideSubmit}>
                                <div className="field">
                                  <label
                                    className="field-label"
                                    htmlFor="override-reason"
                                  >
                                    {t("detail.override_reason_label")}
                                  </label>
                                  <textarea
                                    id="override-reason"
                                    data-testid="extra-work-override-reason"
                                    className="field-textarea"
                                    rows={3}
                                    value={overrideReason}
                                    onChange={(event) =>
                                      setOverrideReason(event.target.value)
                                    }
                                    placeholder={t(
                                      "detail.override_reason_placeholder",
                                    )}
                                    required
                                  />
                                </div>
                                {overrideError && (
                                  <div
                                    className="alert-error"
                                    role="alert"
                                    data-testid="extra-work-override-error"
                                    style={{ marginTop: 6 }}
                                  >
                                    {overrideError}
                                  </div>
                                )}
                                <div className="override-card-footer card-actions-cluster">
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-sm"
                                    onClick={() => {
                                      setOverrideDecision(null);
                                      setOverrideReason("");
                                      setOverrideError("");
                                    }}
                                    disabled={overrideBusy}
                                    data-testid="extra-work-override-cancel"
                                  >
                                    {t("detail.override_cancel")}
                                  </button>
                                  <button
                                    type="submit"
                                    className="btn btn-primary btn-sm"
                                    disabled={
                                      overrideBusy || !overrideReason.trim()
                                    }
                                    data-testid="extra-work-override-submit"
                                  >
                                    {overrideBusy
                                      ? t("detail.override_submitting")
                                      : t("detail.override_confirm", {
                                          label: tStatusLabel(t, target),
                                        })}
                                  </button>
                                </div>
                              </form>
                            </div>
                          )}
                        </div>
                      );
                    })}
                {canRetrySpawn && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={retrySpawnBusy}
                    onClick={() => {
                      void handleRetrySpawn();
                    }}
                    data-testid="extra-work-retry-spawn"
                  >
                    {retrySpawnBusy
                      ? t("detail.retry_spawn_busy")
                      : t("detail.retry_spawn")}
                  </button>
                )}
                {draftProposalDetail?.actions?.can_direct_publish ===
                  true && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setDirectPublishError("");
                      setDirectPublishReason("");
                      setDirectPublishOpen(true);
                    }}
                    data-testid="extra-work-detail-direct-publish-button"
                  >
                    {t("detail.direct_publish_button")}
                  </button>
                )}
                {hasActiveProposal && canViewProposalPdf && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      void handleDownloadPdf();
                    }}
                    disabled={pdfBusy}
                    data-testid="extra-work-detail-pdf-download"
                  >
                    <FileText
                      size={14}
                      strokeWidth={2.2}
                      aria-hidden="true"
                    />
                    {pdfBusy
                      ? t("detail.pdf_download_busy")
                      : t("detail.pdf_download_button")}
                  </button>
                )}
              </div>
              {/* Sprint 187 §2d — say where the decision went.
                  At PRICING_PROPOSED with an open proposal this card
                  renders no decision buttons AT ALL, and correctly so:
                  the `!hasOpenProposal` guard above is load-bearing,
                  because the customer decision has deliberately moved
                  onto the quote and a second decision surface here would
                  be two places to approve one price. What was missing is
                  not a button, it is the sentence — the operator saw an
                  empty card and no explanation.
                  Purely additive: no guard is relaxed, nothing new can
                  be pressed from here. */}
              {ew.status === "PRICING_PROPOSED" && hasOpenProposal && (
                <p
                  className="muted small"
                  style={{ margin: "10px 0 0" }}
                  data-testid="extra-work-workflow-decision-on-proposal"
                >
                  {t("detail.workflow_decision_on_proposal")}
                </p>
              )}
            </div>
          </div>
          </div>{/* end .ew-detail-top-row */}

          {/* M1 B6 — Extra Work message thread + composer. Functional only;
              B8 polishes the visuals. The backend chokepoint filters which
              messages this viewer receives; the composer offers only the
              tiers the backend will accept. */}
          {/* W2-B fix 3 — Messages is FULL WIDTH.

              It used to be the left column of a two-column row whose
              right column held Customer contacts and, sometimes, the
              collapsed Preview card. Contacts moved into the Details
              card (fix 2), which left a 300px rail holding at most one
              46px header bar — so the rail was mostly empty surface,
              and the message thread, the one thing on this page people
              actually read and write in, was squeezed into two thirds
              of the width for it.

              Preview moved down to join the other full-width collapsed
              cards (People, Requested services), where it reads as one
              of a stack rather than the sole occupant of a column. */}
          <section
            className="card ew-messages-card"
            data-testid="extra-work-messages-panel"
          >
            <div className="form-section">
              <div className="form-section-title">{t("messages.title")}</div>

              {/* RF-11 — restyled in the inbox design language: per-message
                  avatars, explicit visibility badges, tighter layout.
                  Presentation only — posting/visibility unchanged. */}
              <div className="ew-message-thread" data-testid="ew-message-thread">
                {ewMessages.length === 0 ? (
                  <p className="muted small">{t("messages.empty")}</p>
                ) : (
                  ewMessages.map((m) => (
                    <div
                      key={m.id}
                      className={`ew-msg ${EW_TIER_TONE_CLASS[m.message_type]}`}
                      data-testid="ew-message-row"
                    >
                      <Avatar name={m.author_email} size={34} />
                      <div className="ew-msg-body">
                        <div className="ew-msg-head">
                          <span className="ew-msg-author">
                            {m.author_email}
                          </span>
                          <span
                            className={`ew-msg-tier ${EW_TIER_TONE_CLASS[m.message_type]}`}
                          >
                            {t(EW_TIER_BADGE_KEY[m.message_type])}
                          </span>
                          {m.visibility_mode === "RESTRICTED" && (
                            <span className="ew-msg-private">
                              {t("messages.private_badge")}
                            </span>
                          )}
                          <span className="ew-msg-time">
                            {formatRelative(m.created_at, messageLocale)}
                          </span>
                        </div>
                        <div className="ew-msg-text">{m.message}</div>
                        {m.directed_to_detail.length > 0 && (
                          <div className="ew-msg-directed muted small">
                            {t("messages.directed_prefix")}{" "}
                            {m.directed_to_detail
                              .map((d) => d.full_name)
                              .join(", ")}
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>

              {ewComposerTiers.length > 0 && (
                <form
                  onSubmit={submitEwMessage}
                  data-testid="ew-message-composer"
                  style={{ marginTop: 12 }}
                >
                  {ewComposerTiers.length > 1 && (
                    <div className="composer-toggle" role="tablist">
                      {ewComposerTiers.map((tier) => (
                        <button
                          key={tier}
                          type="button"
                          role="tab"
                          aria-selected={effectiveEwMessageType === tier}
                          className={`composer-toggle-btn ${
                            effectiveEwMessageType === tier
                              ? `active ${EW_TIER_TONE_CLASS[tier]}`
                              : ""
                          }`}
                          onClick={() => setEwMessageType(tier)}
                        >
                          {t(EW_TIER_LABEL_KEY[tier])}
                        </button>
                      ))}
                    </div>
                  )}
                  <textarea
                    className="field-textarea"
                    rows={3}
                    placeholder={t(
                      EW_TIER_PLACEHOLDER_KEY[effectiveEwMessageType],
                    )}
                    value={ewMessageText}
                    onChange={(e) => setEwMessageText(e.target.value)}
                    required
                  />
                  <p className="muted small">
                    {t(EW_TIER_WHO_SEES_KEY[effectiveEwMessageType])}
                  </p>

                  {ewRecipients.length > 0 && (
                    <div
                      className="composer-directed"
                      data-testid="ew-composer-directed"
                    >
                      <div className="composer-directed-label">
                        {t("messages.directed_label")}
                      </div>
                      <div className="composer-directed-chips">
                        {ewRecipients.map((recipient) => {
                          const selected = ewDirectedTo.includes(recipient.id);
                          return (
                            <button
                              key={recipient.id}
                              type="button"
                              className={`directed-chip${
                                selected ? " directed-chip-selected" : ""
                              }`}
                              aria-pressed={selected}
                              onClick={() => toggleEwDirected(recipient.id)}
                            >
                              {recipient.full_name}
                              <span className="directed-chip-side">
                                {t(`messages.side_${recipient.side}`)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                      {ewCanUsePrivate && (
                        <>
                          <label className="composer-private-toggle">
                            <Toggle
                              checked={ewEffectivePrivate}
                              disabled={ewDirectedTo.length === 0}
                              onChange={(e) => setEwIsPrivate(e.target.checked)}
                              data-testid="ew-composer-private-toggle"
                            />
                            <span>{t("messages.private_label")}</span>
                          </label>
                          <p className="muted small">
                            {ewDirectedTo.length === 0
                              ? t("messages.private_disabled_hint")
                              : ewEffectivePrivate
                                ? t("messages.private_on_hint")
                                : t("messages.private_off_hint")}
                          </p>
                        </>
                      )}
                    </div>
                  )}

                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={ewSending || !ewMessageText.trim()}
                  >
                    {ewSending ? t("messages.sending") : t("messages.post")}
                  </button>
                </form>
              )}
            </div>
          </section>

          {/* Sprint 175 §1 — Preview. The proposal PDF was a button
              inside the Workflow card, where an operator looking for
              "the document" would not think to look. Collapsed by
              default: it fetches a PDF, and the operator usually does
              not want one. */}
          {hasActiveProposal && canViewProposalPdf && (
            <CollapsibleCard
              key={`preview-${ew.id}`}
              title={t("detail.preview_card_title")}
              defaultOpen={false}
              testId="extra-work-preview-panel"
            >
              <div className="form-section">
                <p className="muted small" style={{ marginTop: 0 }}>
                  {t("detail.preview_card_hint")}
                </p>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => void handleDownloadPdf()}
                  disabled={pdfBusy}
                  data-testid="extra-work-preview-pdf"
                >
                  {pdfBusy
                    ? t("detail.proposal_pdf_busy")
                    : t("detail.proposal_pdf")}
                </button>
              </div>
            </CollapsibleCard>
          )}

          {/* Sprint 176 §2 — People on this request: FULL WIDTH,
              collapsed, directly below Messages and above Requested
              services. Rendered `bare` so its body sits inside the
              collapsible without a card inside a card. */}
          {isProvider && ew !== null && (
            <CollapsibleCard
              key={`people-${ew.id}`}
              title={t("assign.card_title")}
              defaultOpen={false}
              testId="extra-work-assignments-card"
            >
              <ExtraWorkAssignmentCard extraWorkId={ew.id} bare />
            </CollapsibleCard>
          )}

          {/* W3-H (plan §2.8) — the TIMESHEET hours booked to this job,
              with the roll-up of budget / entered / cost.

              W4-N fix 2 moved it HERE: below People on this request,
              above Requested services, where the owner asked for it. It
              used to sit near the bottom of the page under the
              actual-hours card, on the argument that the two are easy
              to confuse — but the two things a manager compares are the
              crew's booked hours and the budget that was planned for
              them, and the planning half of this page is up here. The
              distinction the old position was protecting is now carried
              by the card's own words: the actual-hours card enters
              hours onto a PRICING LINE (what the customer pays), this
              one reads the hours the crew booked in the timesheets
              module (what the job cost us), and its first line of body
              text says exactly that.

              Unconditional apart from its own role gate: the panel
              fetches nothing for a non-provider and renders nothing when
              there is nothing to say. Collapsed by default. */}
          <ExtraWorkHoursPanel extraWorkId={ew.id} />

          {/* ----- Cart line items (Sprint 28 Batch 6; RF-14 collapsible:
              open while the request is still pre-decision, collapsed once
              it moved on — the header keeps count + final total visible.
              Keyed by EW id so navigating between EWs re-derives the
              default state instead of carrying the previous card's.) ----- */}
          <CollapsibleCard
            key={`cart-${ew.id}`}
            title={t("detail.line_items_section_title")}
            meta={
              <>
                {t("detail.card_lines_count", {
                  count: ew.line_items.length,
                })}
                {ew.final_total_amount != null && (
                  <>
                    {" · "}
                    {t("detail.pricing_column_total")}:{" "}
                    {formatMoney(ew.final_total_amount)}
                  </>
                )}
              </>
            }
            defaultOpen={
              ew.status === "REQUESTED" ||
              ew.status === "UNDER_REVIEW" ||
              ew.status === "PRICING_PROPOSED"
            }
            testId="extra-work-detail-line-items"
          >
            {ew.line_items.length === 0 ? (
              <div
                className="muted small"
                data-testid="extra-work-detail-line-items-empty"
              >
                {t("detail.line_items_empty")}
              </div>
            ) : (
              <div className="ew-table-scroll">
                <table className="data-table ew-pricing-table">
                  <thead>
                    <tr>
                      {INVOICE_LINE_COLUMN_KEYS.map((key) => (
                        <th key={key}>{t(key)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ew.line_items.map((item) => (
                      <InvoiceLineRow
                        key={item.id}
                        lineKind="cart"
                        line={item}
                        editable={false}
                        rowTestId="extra-work-detail-line-item-row"
                        subLabel={
                          <>
                            <span className="muted small">
                              {formatDate(item.requested_date)}
                            </span>
                            {item.customer_note && (
                              <span className="muted small">
                                {item.customer_note}
                              </span>
                            )}
                          </>
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CollapsibleCard>

          {/* Sprint 8A-fix — provider-only actual-hours entry for the
              active hourly line set (approved-proposal lines or INSTANT
              cart lines). Keyed by `actualHoursPanelKey` so a save
              re-seeds the inputs from refreshed data without a
              prop-derived resync effect; the proposal case also re-fetches
              the approved proposal's detail so entered hours surface. */}
          {isProvider && activeHourlyLines.length > 0 && (
            <ActualHoursPanel
              key={actualHoursPanelKey}
              ewId={ew.id}
              hourlyLines={activeHourlyLines}
              finalTotalAmount={ew.final_total_amount}
              locked={finalAmountLocked}
              onUpdated={(detail) => {
                setEw(detail);
                if (approvedProposalId !== null) {
                  void reloadApprovedProposalDetail();
                }
              }}
            />
          )}

          {/* Draft proposal lines — read-only display of the DRAFT
              proposal's nested `lines` array. Gated on the per-record
              `can_view_proposal_pricing` action so a viewer who cannot
              meaningfully consume prices never sees the section. The
              direct-publish button (right aside) is the only mutation
              surface near this card; line editing / Send / Cancel /
              Approve / Reject UI is deferred. The customer-vs-admin
              `internal_note` distinction is driven by serializer
              absence: ProposalLineCustomerSerializer omits the field,
              so `"internal_note" in line` is the visibility signal,
              NOT a truthiness check on the value. */}
          {/* Sprint 31 — provider proposal builder (editable + removable
              lines, auto-seeded from the cart with contract prices) —
              replaces the old read-only draft-lines display. The builder
              itself falls back to a read-only table when the viewer can
              view pricing but not edit (e.g. a BM with prep revoked). */}
          {ewId !== null &&
            draftProposalDetail !== null &&
            draftProposalDetail.actions?.can_view_proposal_pricing ===
              true && (
              <ProposalBuilder
                key={`proposal-${draftProposalDetail.id}`}
                ewId={ewId}
                proposal={draftProposalDetail}
                onChanged={reloadProposals}
                parentAdvanceBlocked={parentAdvanceBlocked}
              />
            )}

          {/* Prepare-proposal CTA — no open proposal yet and the provider
              may prepare one. Creating it auto-seeds the cart lines with
              their contract prices; the builder above then appears. */}
          {canPrepareProposal &&
            !hasOpenProposal &&
            (ew.status === "REQUESTED" || ew.status === "UNDER_REVIEW") && (
              <div
                className="card"
                style={{ marginBottom: 16 }}
                data-testid="extra-work-prepare-proposal"
              >
                <div className="form-section">
                  <div className="form-section-title">
                    {t("detail.proposal_builder_title")}
                  </div>
                  <p className="muted small" style={{ marginTop: 0 }}>
                    {t("detail.proposal_prepare_helper")}
                  </p>
                  {proposalError && (
                    <div
                      className="alert-error"
                      role="alert"
                      style={{ marginBottom: 12 }}
                    >
                      {proposalError}
                    </div>
                  )}
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={proposalBusy}
                    onClick={handlePrepareProposal}
                    data-testid="extra-work-prepare-proposal-button"
                  >
                    {proposalBusy
                      ? t("detail.proposal_preparing")
                      : t("detail.proposal_prepare")}
                  </button>
                </div>
              </div>
            )}

          {/* Sprint 29 Batch 29.8 — spawned tickets panel. Renders
              read-only when the EW has at least one ticket spawned
              from a cart line (INSTANT route) or a proposal line
              (PROPOSAL route). The list is reachable to anyone who
              can see the EW; per-row link visibility is gated on
              the linked ticket by `scope_tickets_for` server-side. */}
          {spawnedTickets.length > 0 && (
            <section
              className="card"
              data-testid="extra-work-spawned-tickets-panel"
              style={{ marginBottom: 16 }}
            >
              <div className="form-section">
                <div className="form-section-title">
                  {t("detail.spawned_tickets_title")}
                </div>
                <p className="muted small" style={{ marginTop: 0 }}>
                  {t("detail.spawned_tickets_desc")}
                </p>
                <ul className="ew-spawned-tickets-list">
                  {spawnedTickets.map((ticket) => (
                    <li
                      key={ticket.id}
                      className="ew-spawned-ticket-row"
                      data-testid={`extra-work-spawned-ticket-row-${ticket.id}`}
                    >
                      <Link
                        to={`/tickets/${ticket.id}`}
                        className="ew-spawned-ticket-link"
                      >
                        #{ticket.id} {ticket.title}
                      </Link>
                      <StatusBadge
                        status={{ kind: "ticket", value: ticket.status }}
                        variant="cell"
                      />
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <div
            className="muted small"
            style={{ textAlign: "right", marginTop: 8 }}
          >
            {t("detail.updated_at", { date: formatDateTime(ew.updated_at) })}
          </div>
      </div>

      {/* W3-F — the plan modal. Conditionally mounted, which is correct
          HERE and would be a bug for a native `<dialog>`: this is a
          plain overlay div (the split `BulkAssignDialog` documents), so
          neither the invisible-dialog trap (Sprint 128) nor the
          frozen-page trap (Sprint 118) applies. Keyed by the work and
          its stored plan so reopening after a save seeds from what was
          saved rather than from what was on screen when it opened. */}
      {planOpen && (
        <PlanWorkDialog
          key={`plan-${ew.id}-${ew.budget_hours ?? ""}-${
            ew.planned_hours_total ?? ""
          }`}
          ew={ew}
          assignments={planAssignments}
          assignmentsLoading={planAssignmentsLoading}
          busy={planBusy}
          error={planError}
          onCancel={() => setPlanOpen(false)}
          onSubmit={(payload) => void submitPlan(payload)}
        />
      )}

      {/* Sprint 28 Batch 15.4 — customer-side reject dialog. Captures
          the mandatory `customer_reject_reason` the backend now
          requires on CUSTOMER_USER -> CUSTOMER_REJECTED transitions. */}
      <RejectReasonDialog
        open={rejectDialogOpen}
        onCancel={() => setRejectDialogOpen(false)}
        onConfirm={(reason) => {
          setRejectDialogOpen(false);
          void handleCustomerDecision("CUSTOMER_REJECTED", reason);
        }}
      />

      {/* Direct-publish confirmation. Renders a prominent warning
          ("bypasses customer approval, opens tickets immediately") plus
          a mandatory override-reason textarea. The confirm button stays
          disabled until the reason is non-empty (the backend rejects
          with stable code `override_reason_required` otherwise; this
          is the matching client-side guard). */}
      {directPublishOpen && (
        <div
          className="reject-modal-backdrop"
          data-testid="extra-work-direct-publish-dialog"
          role="dialog"
          aria-modal="true"
        >
          <div className="reject-modal">
            <h3 className="reject-modal-title">
              {t("detail.direct_publish_dialog_title")}
            </h3>
            <div
              className="alert-warning"
              style={{ marginBottom: 12 }}
              data-testid="extra-work-direct-publish-warning"
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                {t("detail.direct_publish_dialog_warning_title")}
              </div>
              <div>{t("detail.direct_publish_dialog_warning_desc")}</div>
            </div>
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontWeight: 600,
                fontSize: 13,
              }}
              htmlFor="extra-work-direct-publish-reason"
            >
              {t("detail.direct_publish_reason_label")}
            </label>
            <textarea
              id="extra-work-direct-publish-reason"
              data-testid="extra-work-direct-publish-reason-textarea"
              className="field-textarea reject-modal-textarea"
              value={directPublishReason}
              onChange={(e) => setDirectPublishReason(e.target.value)}
              placeholder={t("detail.direct_publish_reason_placeholder")}
              rows={4}
              autoFocus
              disabled={directPublishBusy}
            />
            {directPublishError && (
              <div
                className="alert-error"
                style={{ marginTop: 8 }}
                role="alert"
                data-testid="extra-work-direct-publish-error"
              >
                {directPublishError}
              </div>
            )}
            <div className="reject-modal-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setDirectPublishOpen(false);
                  setDirectPublishReason("");
                  setDirectPublishError("");
                }}
                disabled={directPublishBusy}
                data-testid="extra-work-direct-publish-cancel"
              >
                {t("detail.direct_publish_cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm reject-modal-confirm"
                onClick={() => void handleDirectPublish()}
                disabled={
                  directPublishBusy || directPublishReason.trim().length === 0
                }
                data-testid="extra-work-direct-publish-confirm"
              >
                {directPublishBusy
                  ? t("detail.direct_publish_busy")
                  : t("detail.direct_publish_confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sprint 29 Batch 29.8 — cancel-confirmation dialog. Warns when
          spawned tickets are still active so the operator is aware
          they will NOT be auto-cancelled. The transition itself is
          unchanged; this is a UI-only safety net. */}
      <ConfirmDialog
        ref={cancelDialogRef}
        title={t("detail.cancel_dialog_title")}
        body={
          <div>
            {activeSpawnedTickets.length > 0 && (
              <div
                className="alert-warning"
                data-testid="extra-work-cancel-spawned-tickets-warning"
                style={{ marginBottom: 12 }}
              >
                <div style={{ fontWeight: 600, marginBottom: 8 }}>
                  {t("detail.cancel_dialog_spawned_warning_title", {
                    count: activeSpawnedTickets.length,
                  })}
                </div>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {activeSpawnedTickets.map((ticket) => (
                    <li key={ticket.id}>
                      {/* Sprint 184 §3 — the last raw enum on a screen.
                          This printed "(WAITING_CUSTOMER_APPROVAL)"
                          while the page behind it said "Wacht op klant",
                          and it is a CONFIRMATION dialog — the worst
                          place in the app to make somebody decode a
                          machine value before answering yes. */}
                      #{ticket.id} — {ticket.title} (
                      {t(ticketStatusLabelKey(ticket.status), { ns: "common" })}
                      )
                    </li>
                  ))}
                </ul>
                <p style={{ marginTop: 8, marginBottom: 0 }}>
                  {t("detail.cancel_dialog_spawned_warning_desc")}
                </p>
              </div>
            )}
            <p style={{ margin: 0 }}>{t("detail.cancel_dialog_body")}</p>
          </div>
        }
        confirmLabel={t("detail.cancel_dialog_confirm")}
        cancelLabel={t("detail.cancel_dialog_keep")}
        onConfirm={handleConfirmCancel}
        busy={cancelBusy}
        destructive
      />
    </div>
  );
}





