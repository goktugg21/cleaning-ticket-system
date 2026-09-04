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
import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Link,
  Navigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  CalendarClock,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  FileSearch,
  FileText,
  Pencil,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import axios from "axios";

import { listCustomerContacts } from "../api/admin";
import { api, getApiError } from "../api/client";
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
  getExtraWorkTimeline,
  listEwMessages,
  listProposalsForEw,
  listExtraWorkAssignments,
  listExtraWorkAssignmentCandidates,
  bulkAssignExtraWork,
  listSpawnedTickets,
  planExtraWork,
  relabelExtraWork,
  updateExtraWorkDates,
  retrySpawnTicketsForExtraWork,
  transitionExtraWork,
  updateExtraWorkBilling,
  type ExtraWorkTimelineEntry,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import { useOriginBackLink } from "../hooks/useBackLink";
import { MoneyStory } from "../components/extra-work/MoneyStory";
import {
  pointAtMissingPiece,
  useMissingPieceAnchor,
} from "../lib/missingPiece";
import { CoverageNotice } from "../components/extra-work/CoverageNotice";
import {
  deriveActiveHourlyLines,
  selectApprovedProposal,
  type ActualHoursLine,
} from "../components/extra-work/activeHourlyLines";
import { ExtraWorkAssignmentCard } from "../components/extra-work/ExtraWorkAssignmentCard";
import { PlanSummary } from "../components/extra-work/PlanSummary";
import { ExtraWorkContextHeader } from "../components/extra-work/ExtraWorkContextHeader";
import { MeerwerkTimeline } from "../components/extra-work/MeerwerkTimeline";
import { PhaseBanner } from "../components/customer/PhaseBadge";
import { DoneBanner } from "../components/guide/DoneBanner";
import { useDoneBanner } from "../components/guide/useDoneBanner";
import {
  announceDone,
  safeSessionStorage,
  takeDone,
} from "../components/guide/doneBannerStore";
import { DueChipCore } from "../components/workplan/WorkPlanCard";
import { resolveNextStep } from "../components/extra-work/nextStep";
import { HOURS_PANEL_MODE } from "../components/extra-work/hoursPanelMode";
import { PlanWorkDialog } from "../components/extra-work/PlanWorkDialog";
import type { PlanFocus } from "../components/extra-work/PlanWorkDialog";
import { billingMonthWords, monthName } from "../lib/billingSentence";
import {
  canSeeExtraWorkStaffing,
  isCustomerUser,
  isProviderAdmin,
  isProviderManagementRole,
} from "../auth/permissions";
import type {
  AssignmentCandidate,
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
  PaginatedResponse,
  Proposal,
  ProposalDetail,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketStatus,
} from "../api/types";
import { ConfirmDialog, type ConfirmDialogHandle } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { Toggle } from "../components/Toggle";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { PageHeader } from "../components/PageHeader";
import { PdfPreviewDialog } from "../components/PdfPreviewDialog";
import type { PdfPreviewDialogHandle } from "../components/PdfPreviewDialog";
import { ProposalBuilder } from "../components/ProposalBuilder";
import { billedToKey } from "../lib/billedTo";
import { customerLabelName } from "../lib/customerLabelName";
import { RejectReasonDialog } from "../components/RejectReasonDialog";
import { describeExtraWorkRefusal } from "../lib/extraWorkRefusal";
import type { ExtraWorkRefusal } from "../lib/extraWorkRefusal";
import {
  compareCoverage,
  coverageConfirmLabel,
  type CoverageLine,
} from "../lib/extraWorkCoverage";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { extraWorkStatusLabelKey, ticketStatusLabelKey } from "../lib/enumLabels";
import { formatDate, formatDateTime, formatRelative, useLocaleCode } from "../lib/intl";
import { unitSuffix } from "../lib/unitLabel";
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

/** FE-3 — the intent, behind Geavanceerd, in the create form's own
 *  words (one label per intent, one owner). */
const INTENT_I18N_KEY: Record<string, string> = {
  DIRECT_AGREED_PRICE_ORDER: "create.intent.direct.label",
  AUTO_START_AFTER_PRICING: "create.intent.auto_start.label",
  REQUEST_QUOTE: "create.intent.request_quote.label",
};

const URGENCY_I18N_KEY: Record<ExtraWorkUrgency, string> = {
  NORMAL: "urgency.normal",
  HIGH: "urgency.high",
  URGENT: "urgency.urgent",
};

/* Reads as a rule rather than as an omission on the entries that have
 * no restriction. */
const everyone = () => true;

// Sprint 30 Batch 30.1 — roles allowed to call POST /extra-work/<id>/spawn/.
// The backend gate is intentionally narrower than the broader provider set
// (BUILDING_MANAGER is excluded — this is a corrective admin action). The
// UI must mirror that gate exactly so the button never renders for a role
// the API will refuse anyway.
// W-G §1 — `isProviderAdmin` is that pair, already named once in
// `auth/permissions`. A local Set spelling out the same two roles was a
// second place the same fact was written.

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

/** P-9 C5 — when the "hours to bill" panel shows, per phase. Hours
 *  worked exist once the work has started: before that the Money tab
 *  says so in one sentence; after the invoice the saved hours are read
 *  only. Exhaustive over the phase enum — a new phase fails to
 *  compile here rather than rendering the panel by accident. */

/** P-9 C4 — the request's lines in the shape the coverage check reads. */
function cartCoverageLines(
  items: ExtraWorkRequestDetail["line_items"],
  t: TFunction,
): CoverageLine[] {
  return items.map((item) => ({
    id: item.id,
    service: item.service,
    label:
      (item.service_name || item.custom_description || "").trim() || `#${item.id}`,
    quantity: item.quantity,
    unit: unitSuffix({ type: item.unit_type, label: "" }, t),
  }));
}

// W17 — ActualHoursPanel and its active-set derivation moved to
// components/extra-work/ActualHoursPanel.tsx so the operational
// ticket's Extra work card group mounts the SAME panel. One component,
// two mounts.


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
interface DatesDraft {
  deadline: string;
  plannedEnd: string;
}

interface LabelsDraft {
  deptId: string;
  wtId: string;
}

function DatesEditor({
  ew,
  draft,
  onDraftChange,
  onUpdated,
  onClose,
}: {
  ew: ExtraWorkRequestDetail;
  /** W-FIX1 C4 — the draft is the PAGE's, so it survives a tab switch. */
  draft: DatesDraft;
  onDraftChange: (next: DatesDraft) => void;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const deadline = draft.deadline;
  const plannedEnd = draft.plannedEnd;
  const setDeadline = (value: string) => onDraftChange({ ...draft, deadline: value });
  const setPlannedEnd = (value: string) =>
    onDraftChange({ ...draft, plannedEnd: value });
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
    /* W12 FIX 2 — this editor edits OUR dates, and only ours.
       It used to carry a third date: the customer's preferred date,
       read-only, inside a box for editing. Three dates in one small box,
       one of them not editable and not ours, and no label saying whose
       any of them were. The customer's date is theirs, it is already in
       the Dates block directly above this, and one fact has one place.
       What is left is the two commitments we make, wearing the SAME
       labels the values above them wear -- the same keys, so the field
       you edit cannot come to be called something else than the value
       you just read. */
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
            {t("detail.date_planned_end")}
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
          <span className="muted small">{t("detail.date_deadline")}</span>
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
  draft,
  onDraftChange,
  onUpdated,
  onRefresh,
  onClose,
}: {
  ew: ExtraWorkRequestDetail;
  /** W-FIX1 C4 — the draft is the PAGE's, so it survives a tab switch. */
  draft: LabelsDraft;
  onDraftChange: (next: LabelsDraft) => void;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const [departments, setDepartments] = useState<CustomerLabel[]>([]);
  const [workTypes, setWorkTypes] = useState<CustomerLabel[]>([]);
  const deptId = draft.deptId;
  const wtId = draft.wtId;
  const setDeptId = (value: string) => onDraftChange({ ...draft, deptId: value });
  const setWtId = (value: string) => onDraftChange({ ...draft, wtId: value });
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


/*  W5 fix 1 — Customer contacts is a FIELD, not a panel.
 *
 *  Four attempts to place this. It was a collapsed card in the far-right
 *  rail (W2-B), then a half-width column beside the description (W2-B
 *  fix 2 / W3-F), then a full-height third column top-aligned with the
 *  card (W4-N). The owner spelled the answer out: it is the NEXT FIELD
 *  in the right-hand column of the Details grid, directly under
 *  Department / Work type, with the same label styling as "Customer",
 *  "Ticket" and "Preferred date", the count beside the label, and one
 *  readable line per contact.
 *
 *  So there is no border, no fill, no shadow and no wrapper that reads
 *  as a panel — the `muted small` label and the plain lines under it
 *  are the entire treatment, which is exactly what every other field in
 *  that column wears. It is placed by normal grid flow (`grid-column: 2`
 *  puts it in the next free row of the column it belongs to), never by
 *  positioning.
 *
 *  THE BOUND IS THE ONE THING KEPT. A customer can have dozens of
 *  contacts and this sits in the card that governs the top of the page,
 *  so the list scrolls inside itself (`.ew-contacts-field-list`,
 *  max-height in CSS) rather than making the card enormous — CLAUDE.md's
 *  "no unbounded server list" rule.
 *
 *  Every testid is verbatim from the card it replaced
 *  (`extra-work-customer-contacts-panel` / `-empty` / `-contact-row`),
 *  because `sprint28_batch15_4_detail_rebuild.spec.ts` asserts on all
 *  three and a restyled field is not a renamed one. */
function CustomerContactsPanel({ contacts }: { contacts: Contact[] }) {
  const { t } = useTranslation(["extra_work", "common"]);
  return (
    <div
      className="ew-contacts-field"
      data-testid="extra-work-customer-contacts-panel"
    >
      {/* `muted small` — the same class "Customer", "Ticket", "Preferred
          date" and "Department" wear, so this label shares their size,
          weight, colour and left edge. The count rides with it. */}
      <div className="muted small">
        {t("customer_contacts.panel_title", { ns: "common" })}{" "}
        <span className="ew-contacts-field-count">{contacts.length}</span>
      </div>
      {contacts.length === 0 ? (
        <div
          className="muted small"
          data-testid="extra-work-customer-contacts-empty"
        >
          {t("customer_contacts.panel_empty", { ns: "common" })}
        </div>
      ) : (
        <ul className="ew-contacts-field-list">
          {contacts.map((contact) => (
            <li
              key={contact.id}
              className="ew-contacts-field-row"
              data-testid="extra-work-customer-contact-row"
            >
              {/* One line per person: name, role, e-mail, phone. It
                  wraps inside the column rather than widening it. */}
              <span className="ew-contacts-field-name">
                {contact.full_name}
              </span>
              {/* P-5 S6.5 — the free-text role label ("A") is not
                  rendered on read-only lines; see TicketDetailPage. */}
              {contact.email && (
                <span className="muted small">{contact.email}</span>
              )}
              {contact.phone && (
                <span className="muted small">{contact.phone}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** W7-D — the six-screen shape the owner approved.
 *
 *  ONE constant, iterated by the tab bar. Module-scoped rather than
 *  exported: this file has exactly one consumer, and exporting a
 *  non-component from a component file breaks fast refresh
 *  (react-refresh/only-export-components). CLAUDE.md's rule is that
 *  every consumer iterates ONE list, not that the list is exported. CLAUDE.md records
 *  what a second, independently maintained render list costs: Sprint
 *  126's `documents` permission group rendered a headerless column and
 *  was invisible for three sprints because two lists had to be kept in
 *  step by hand.
 *
 *  FILES IS ABSENT AND THAT IS DELIBERATE — see the report. There is no
 *  Extra Work attachment surface anywhere in this product: no model, no
 *  endpoint, no client. A Files tab would be a new feature (and a
 *  backend one), which this sprint forbids. An empty tab that promises
 *  a feature that does not exist is worse than no tab. */
/* W-G §1 — A TAB DECLARES WHO IT IS FOR.
 *
 * The owner opened an Extra Work on a customer account and found the
 * Hours and People tabs rendering a blank page: "is it always like this
 * or only for this specific extra work? Either way a completely empty
 * page is not nice."
 *
 * Always, and for every customer. Both tabs are provider-management
 * surfaces down to the last element -- the hours panel returns null for
 * anyone else and the People tab is one provider-gated card -- so a
 * customer was offered two buttons that could never draw anything.
 *
 * `visibleTo` is on the entry rather than in a second list, so the tab
 * bar and the bodies below cannot disagree about who gets what, and a
 * sixth tab cannot be added without answering the question. The
 * predicate itself lives in `auth/permissions`, which is where every
 * other "which role sees this" answer lives. */
const EW_TABS = [
  { key: "overview", labelKey: "detail.tab_overview", visibleTo: everyone },
  { key: "money", labelKey: "detail.tab_money", visibleTo: everyone },
  { key: "people", labelKey: "detail.tab_people", visibleTo: canSeeExtraWorkStaffing },
  { key: "messages", labelKey: "detail.tab_messages", visibleTo: everyone },
] as const;

type EwTab = (typeof EW_TABS)[number]["key"];

export function ExtraWorkDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();
  const messageLocale = useLocaleCode();
  // FE-4 (Addendum D §D.12 item 1) — back goes where the reader came
  // from; the meerwerk list when there is no in-app origin.
  // P-11 B3 — where "add a line" lands: the Money tab's line-items
  // card. The anchor mounts with the tab, so the door is never dead.
  const pricingLinesAnchor = useMissingPieceAnchor<HTMLDivElement>("pricing-lines");
  const originBack = useOriginBackLink(me?.role, {
    fallbackTo: "/extra-work",
    fallbackLabelKey: "back_to.extra_work",
  });

  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  // Sprint 177 §2 — the dates editor is opened from a trigger that sits
  // beside the deadline, so the open state lives here rather than inside
  // the editor it opens.
  const [datesOpen, setDatesOpen] = useState(false);
  /* W-FIX1 C4 (audit F11) — the editors' DRAFTS live on the page, so a
     pill-tab switch (which unmounts the Overview) brings the editor back
     with what was typed rather than an open editor with emptied fields. */
  const [datesDraft, setDatesDraft] = useState<DatesDraft | null>(null);
  const [labelsDraft, setLabelsDraft] = useState<LabelsDraft | null>(null);
  /* W-FIX1 C2 — bumped by the People tab's assignment card. */
  const [assignmentsNonce, setAssignmentsNonce] = useState(0);
  // Sprint 189 §1 — same shape for the labels editor, which now opens in
  // the same place from a trigger in the same grid.
  const [labelsOpen, setLabelsOpen] = useState(false);
  // W3-F — the plan modal. The assignment list is fetched WHEN THE
  // DIALOG OPENS rather than with the page: the backend refuses hours
  // for anybody not currently assigned, so the crew the dialog offers
  // has to be the crew as of the moment somebody plans, not as of the
  // last page load.
  const [planOpen, setPlanOpen] = useState(false);
  // P-5 S2.4 — which part of the plan the modal opens on (see openPlan).
  const [planFocus, setPlanFocus] = useState<PlanFocus | null>(null);
  /* W-PLAN — the pricing entry point states the plan, so the page has
     to KNOW the plan before the dialog is ever opened. Loaded for
     provider viewers on mount and re-read when the status moves (a
     plan write moves nothing, but the dialog's own save path refreshes
     `ew`, and the assign path below re-reads explicitly). */
  const [managerCandidates, setManagerCandidates] = useState<
    AssignmentCandidate[]
  >([]);
  const [managerBusy, setManagerBusy] = useState(false);
  const [planAssignments, setPlanAssignments] = useState<
    ExtraWorkAssignment[]
  >([]);
  const [planAssignmentsLoading, setPlanAssignmentsLoading] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  /* P-4 (Part B) — the refusal itself, so the dialog can put each
     message at its field. */
  const [planRawError, setPlanRawError] = useState<unknown>(null);
  // W-UX1 §2 — the plan area's assign surface.
  const [planCandidates, setPlanCandidates] = useState<AssignmentCandidate[]>([]);
  const [planCandidatesLoading, setPlanCandidatesLoading] = useState(false);
  const [planAssignBusy, setPlanAssignBusy] = useState(false);
  /** P-7 S2.1 — the X in the plan modal: one unassign in flight. */
  const [planRemoveBusy, setPlanRemoveBusy] = useState(false);
  const [planAssignError, setPlanAssignError] = useState("");

  const [loading, setLoading] = useState(true);
  // W14 §3 — TWO ERROR CHANNELS, AND THE REASON THERE ARE TWO.
  //
  // The owner completed an extra work and the page answered "Extra
  // Work not found". The record was never missing. Every action
  // handler on this page wrote its failure into the SAME `error` the
  // initial fetch uses, and the render guard below was
  // `if (error || !ew)` -> the not-found empty state. So one refused
  // transition threw the whole loaded record off the screen, and the
  // operator was left unable to see what he had just done.
  //
  // `error` now means ONE thing: the record could not be loaded. That
  // is the only condition under which "not found" is a true sentence,
  // and it is caught by `!ew` anyway.
  const [error, setError] = useState("");
  // A failed ACTION on a record that is right here. Renders as an
  // alert above the content; the record stays on screen.
  const [actionError, setActionError] = useState("");
  const ewDone = useDoneBanner(`ew-${id}`);
  // P-8R A3 — the refusal's KIND and where it was pressed, so the
  // sentence renders AT the acting control, with its door (complete the
  // plan / give a reason), and scrolls into view.
  const [actionRefusal, setActionRefusal] = useState<{
    refusal: ExtraWorkRefusal;
    target: ExtraWorkStatus | null;
    at: "banner" | "actions";
  } | null>(null);
  const actionErrorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (actionError) {
      actionErrorRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [actionError]);
  // P-8R A4 — "Start the work" asks once, naming the plan.
  const startDialogRef = useRef<ConfirmDialogHandle>(null);
  const [startAt, setStartAt] = useState<"banner" | "actions">("banner");
  // P-8R A4 — the on-behalf decision's reason is a warning modal (the
  // drawer's pattern); `overrideDecision` remembers WHICH decision so a
  // refusal can land under that button after the modal closes.
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);

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
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideError, setOverrideError] = useState("");

  // M4 (3d) — per-EW billing-month override. billingDraft=null means
  // "show ew's current value"; the input is derived at render (never synced
  // via an effect, to avoid a setState-in-effect violation).
  /* W15 §3 — THE TAB IS PART OF THE ADDRESS.
   *
   * The owner's rule for this sprint is "one record, one page, two ways
   * in". A tab kept in component state cannot satisfy it: a link can
   * only ever reach the default tab, a refresh throws away which tab you
   * were reading, and Back walks out of the page instead of back one
   * tab. Two people looking at "the same screen" were not, and neither
   * could send the other to it.
   *
   * The reference system already does this and it is where the owner
   * pointed: its detail deep link is `/extra-works/{id}?tab=info`
   * (01-extra-work.md, `updateStatus` FCM payload). Same mechanism, same
   * query key.
   *
   * `replace: true` because a tab is a VIEW of one record, not a
   * separate destination: without it, reading four tabs would put four
   * entries in the history and Back would crawl through them. It also
   * keeps this page out of the double-history trap the ticket table hit
   * in W14 §3.
   */
  /* W17 §1 — the W15 `chargeableFrom` reader moved to TicketDetailPage.
   * A chargeable row opens the TICKET now (one work, one page), so the
   * page that has to know the way back to that list is the ticket, not
   * this one. Arriving here from the ticket's origin pill, the Extra
   * Work list is once again the only list "back" can mean. */

  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const requestedTab: EwTab = EW_TABS.some((entry) => entry.key === tabParam)
    ? (tabParam as EwTab)
    : "overview";
  const setTab = (next: EwTab) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        // The default tab is the ABSENCE of the parameter, so the plain
        // `/extra-work/<id>` that every existing link uses stays the
        // canonical address of the page rather than becoming a second
        // spelling of `?tab=overview`.
        if (next === "overview") params.delete("tab");
        else params.set("tab", next);
        return params;
      },
      { replace: true },
    );
  };
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
  /** W-HOURS4 Task 4 — the proposal card's in-app preview of the same
   *  PDF its Download button fetches. Native `<dialog>`, rendered
   *  unconditionally beside the confirm dialogs, driven by the ref. */
  const proposalPreviewRef = useRef<PdfPreviewDialogHandle>(null);
  // W14 §4 — completing asks first, and what it asks is not "are you
  // sure": it is the one fact the owner could not get off this screen.
  const completeDialogRef = useRef<ConfirmDialogHandle>(null);
  // W14 §2 — the secondary moves start closed.
  const [otherActionsOpen, setOtherActionsOpen] = useState(false);
  // FE-3 (Addendum D §D.6 rule 3) — the Geavanceerd fold: corrections,
  // overrides, the billing-month override, the raw values. Closed.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // FE-3 (§D.4) — the folded timeline, rendered for the provider too.
  const [timeline, setTimeline] = useState<ExtraWorkTimelineEntry[]>([]);
  const [cancelBusy, setCancelBusy] = useState(false);
  // P-16 (P-14 S4) — the cancel carries its why: the server refuses a
  // CANCELLED transition without a written reason (cancel_note_required).
  const [cancelReason, setCancelReason] = useState("");

  // M1 B6 — Extra Work message thread + composer state.
  const [ewMessages, setEwMessages] = useState<EwMessage[]>([]);
  // TU — ONE LIVE CONVERSATION PER JOB, the customer's half.
  //
  // A provider who opens a spawned request is redirected to the job
  // (see the Navigate below) so they never see this thread again. The
  // CUSTOMER is deliberately never redirected -- their surface stays
  // the request -- which left them writing into a thread nobody on the
  // provider side would ever read. The backend now refuses those posts
  // (409 `thread_frozen`); this is the other half: their composer
  // writes to the JOB instead, and their list shows both halves of the
  // conversation in one chronological run.
  //
  // Nothing here is a new read path. The ticket thread is fetched from
  // the SAME `/tickets/<id>/messages/` endpoint the job page uses, so
  // the per-tier visibility chokepoint decides what a customer sees,
  // server-side, exactly as it already does. A customer whose scope
  // does not reach this ticket simply gets nothing back (their ticket
  // scope is the intersection of customer membership and per-building
  // access), and then no composer is rendered at all.
  const [jobMessages, setJobMessages] = useState<TicketMessage[]>([]);
  const [jobTicket, setJobTicket] = useState<TicketDetail | null>(null);
  const [jobSending, setJobSending] = useState(false);
  const [jobError, setJobError] = useState("");

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

  /* W-G §1 — one owner. This page kept its own `PROVIDER_ROLES` set
   * naming the same three roles `isProviderManagementRole` already
   * names, so "who is a provider" was written twice and could drift.
   * The local copy is gone. */
  const isProvider = useMemo(
    () => isProviderManagementRole(me?.role),
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
  /* W-PLAN — the gate's facts, loaded whenever a provider looks at
     the record. Same state the plan dialog uses, so the entry point's
     summary and the dialog can never disagree about who is on the
     plan. ABOVE the loading/error returns — hooks must run on every
     render. */
  useEffect(() => {
    if (!isProvider || ewId === null) return;
    let cancelled = false;
    listExtraWorkAssignments(ewId)
      .then((rows) => {
        if (!cancelled) setPlanAssignments(rows);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isProvider, ewId, ew?.status, assignmentsNonce]);

  /* The one plan fact the dialog cannot fix (its picker is WORKER-only
     by design): the responsible manager. Offered inline at the pricing
     entry point, from the same server eligibility helper the write
     validates against. */
  useEffect(() => {
    if (!isProvider || ewId === null) return;
    let cancelled = false;
    listExtraWorkAssignmentCandidates(ewId, "MANAGER")
      .then((rows) => {
        if (!cancelled) setManagerCandidates(rows);
      })
      .catch(() => setManagerCandidates([]));
    return () => {
      cancelled = true;
    };
  }, [isProvider, ewId]);

  const approvedProposal = useMemo(
    () => selectApprovedProposal(proposals),
    [proposals],
  );
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
  const activeHourlyLines = useMemo<ActualHoursLine[]>(
    () => deriveActiveHourlyLines(ew, approvedProposal, approvedProposalDetail),
    [ew, approvedProposal, approvedProposalDetail],
  );

  /* The tabs this viewer actually has. DERIVED, never stored: a stored
   * copy would need an effect to correct itself when `me` lands, and a
   * synchronous setState in an effect body is the house rule this file
   * already follows.
   *
   * hours2 1a — the Hours tab exists only while it has something to
   * show. The timesheet panel ("Hours on this extra work") left this
   * page: hours live on the job now (the ticket's Plan tab), and a
   * provider is redirected there the moment work is spawned (W21
   * below), so nothing on THIS page could ever have had hours. What
   * remains under Hours is the pricing-line actual-hours entry, which
   * exists only for hourly-priced lines — and a tab that opens on an
   * empty page is the W8 §4 defect this file already names. Computed
   * AFTER `activeHourlyLines` because that is the fact it depends on. */
  const visibleTabs = useMemo(
    () =>
      EW_TABS.filter((entry) => entry.visibleTo(me?.role)),
    [me],
  );

  /* Falling back rather than correcting state: a customer who somehow
   * holds "hours" (a stale render, a future deep link) reads the first
   * tab they do have instead of a blank page. */
  const tab: EwTab = visibleTabs.some((entry) => entry.key === requestedTab)
    ? requestedTab
    : (visibleTabs[0]?.key ?? "overview");

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
  // The job this request became, if it became one. SAME sort as the
  // provider redirect below (earliest scheduled day, undated last, id
  // as tiebreak) so both halves of the app agree on which ticket "the
  // job" is when a request spawned a series.
  const jobTicketId = useMemo(() => {
    const spawned = ew?.spawned_tickets ?? [];
    if (spawned.length === 0) return null;
    return [...spawned].sort((a, b) => {
      const ad = a.scheduled_start_at ?? "9999-12-31T23:59:59Z";
      const bd = b.scheduled_start_at ?? "9999-12-31T23:59:59Z";
      if (ad !== bd) return ad < bd ? -1 : 1;
      return a.id - b.id;
    })[0].id;
  }, [ew?.spawned_tickets]);

  const threadIsFrozen = jobTicketId !== null;

  const reloadJobThread = useCallback(() => {
    if (jobTicketId === null) return;
    // Both reads are the job page's own endpoints. A customer outside
    // this ticket's scope gets 404/403 and we keep `jobTicket` null,
    // which is what removes the composer entirely.
    void api
      .get<PaginatedResponse<TicketMessage>>(
        `/tickets/${jobTicketId}/messages/`,
      )
      .then((response) => setJobMessages(response.data.results))
      .catch(() => setJobMessages([]));
    void api
      .get<TicketDetail>(`/tickets/${jobTicketId}/`)
      .then((response) => setJobTicket(response.data))
      .catch(() => setJobTicket(null));
  }, [jobTicketId]);

  useEffect(() => {
    // Providers are redirected to the job before this matters; only the
    // customer's surface needs the merge.
    if (isProvider || jobTicketId === null) return;
    reloadJobThread();
  }, [isProvider, jobTicketId, reloadJobThread]);

  // THE MERGED CONVERSATION, chronological: what the job's thread lets
  // this customer read, plus the frozen request history. Both sides are
  // already server-filtered; this only interleaves them.
  const mergedMessages = useMemo(() => {
    const fromRequest = ewMessages.map((m) => ({
      key: `ew-${m.id}`,
      created_at: m.created_at,
      body: m.message,
      author: m.author_email,
      onJob: false,
    }));
    const fromJob = jobMessages.map((m) => ({
      key: `job-${m.id}`,
      created_at: m.created_at,
      body: m.message,
      author: m.author_email,
      onJob: true,
    }));
    return [...fromRequest, ...fromJob].sort((a, b) =>
      a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0,
    );
  }, [ewMessages, jobMessages]);

  // ABSENT, not disabled. The composer exists only when the server says
  // this viewer may post a customer-visible reply on the job
  // (`actions.can_post_public_reply`, the same flag the job page's own
  // composer reads). Unreachable ticket -> `jobTicket` is null -> no
  // composer, and the history still reads.
  const canWriteOnJob =
    !isProvider &&
    threadIsFrozen &&
    jobTicket?.actions?.can_post_public_reply === true;

  async function submitJobMessage(event: FormEvent) {
    event.preventDefault();
    if (jobTicketId === null || !ewMessageText.trim()) return;
    setJobSending(true);
    setJobError("");
    try {
      // The EXISTING ticket-message chokepoint, in the customer-visible
      // mode. PUBLIC_REPLY + NORMAL is the only pair a customer may
      // write that the provider reads on the job; nothing here widens
      // what a customer can post or see.
      await api.post(`/tickets/${jobTicketId}/messages/`, {
        message: ewMessageText.trim(),
        message_type: "PUBLIC_REPLY",
        visibility_mode: "NORMAL",
        directed_to: [],
      });
      setEwMessageText("");
      reloadJobThread();
      pushToast({ variant: "success", title: t("messages.posted") });
    } catch (err) {
      setJobError(getApiError(err));
    } finally {
      setJobSending(false);
    }
  }

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

  // FE-3 — the same folded timeline the customer tracker reads
  // (`GET /extra-work/<id>/timeline/`, scope-walled by `get_object`).
  // Re-read on every status move so a transition made on this page
  // shows up in the story without a reload. State is set only in the
  // async callbacks; a failed read leaves the card saying "no events".
  const ewStatusForTimeline = ew?.status ?? null;
  useEffect(() => {
    if (ewId === null) return;
    let cancelled = false;
    getExtraWorkTimeline(ewId)
      .then((data) => {
        if (!cancelled) setTimeline(data.entries);
      })
      .catch(() => {
        if (!cancelled) setTimeline([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId, ewStatusForTimeline]);

  if (loading) {
    return (
      <div>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      </div>
    );
  }

  // W14 §3 — "not found" now means NOT FOUND. `ew` is null only when the
  // fetch never produced a record; a failed action leaves it right where
  // it was and renders `actionError` above the content instead.
  if (!ew) {
    return (
      <div>
        <PageHeader
          backLink={{ to: originBack.to, label: originBack.label }}
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

  // W21 — THE AUTOMATIC LANDING, without the escape. For a provider,
  // a request that has spawned work IS that work: any spawned ticket
  // (series included) redirects to the job page, landing on the
  // EARLIEST day (scheduled date, undated last, id as tiebreak — the
  // same order the Agreement card lists the days in). W18's `?full=1`
  // back door is deleted with the links that carried it; the Agreement
  // card on the job page holds what this page was reopened for.
  // Customers are never redirected — their surfaces stay the request.
  if (isProvider && ew.spawned_tickets.length >= 1) {
    const bd_of = (row: { scheduled_start_at: string | null }) =>
      row.scheduled_start_at ?? "9999-12-31T23:59:59Z";
    const earliest = [...ew.spawned_tickets].sort((a, b) => {
      const ad = bd_of(a);
      const bd = bd_of(b);
      if (ad !== bd) return ad < bd ? -1 : 1;
      return a.id - b.id;
    })[0];
    // P-12 F2 — a Done banner announced on THIS request (price-and-
    // start, start-the-work) would never be seen here: the page
    // redirects. Relay it to the ticket the person lands on.
    const pending = takeDone(safeSessionStorage(), `ew-${ew.id}`);
    if (pending) {
      announceDone(safeSessionStorage(), `ticket-${earliest.id}`, pending);
    }
    // P-13 J — a `?tab=` deep link (the Money tab, typically) keeps
    // its tab through the redirect: the ticket page reads the same
    // param.
    const deepTab = searchParams.get("tab");
    return (
      <Navigate
        replace
        to={`/tickets/${earliest.id}${deepTab ? `?tab=${deepTab}` : ""}`}
      />
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

  // W14 §2 — ONE PRIMARY ACTION, AND THE REST BEHIND A DOOR.
  //
  // The owner counted the card's row: Plan work | Revise pricing |
  // Cancel request | Approve pricing | Reject pricing. Five, side by
  // side, no sequence. His diagnosis was that there is no order to
  // derive one from; the transition table says otherwise, and
  // `PRIMARY_FORWARD_TRANSITIONS` has encoded which move is FORWARD
  // since W2-B. What was missing was not the knowledge — it was
  // acting on it. So the forward move is the only status button on the
  // card, and everything else the server currently allows waits behind
  // a closed disclosure, the same shape `TicketDetailPage` uses for its
  // secondary moves (W11 §1).
  //
  // Collapsed, the list does not exist in the document — it is not
  // hidden with CSS — so a stray tab never lands on a cancel.
  const forwardTarget =
    providerWorkflowTargets.find((target) =>
      isForwardTarget(ew.status, target),
    ) ?? null;
  const otherWorkflowTargets = providerWorkflowTargets.filter(
    (target) => target !== forwardTarget,
  );

  // Sprint 31 — an AUTO_START request is pre-authorized by the customer,
  // so the workflow must NOT frame the pricing step as "propose to
  // customer". The labels/hints below switch accordingly.
  const isAutoStart =
    ew.request_intent === "AUTO_START_AFTER_PRICING";

  // W-UX1 §3 — THE PRIMARY ACTION SPEAKS ITS ROUTE.
  //
  // The intake route is `request_intent` (`ExtraWorkRequest
  // .request_intent`, `backend/extra_work/models.py:791`), one of
  // DIRECT_AGREED_PRICE_ORDER / AUTO_START_AFTER_PRICING /
  // REQUEST_QUOTE. Only the last is a quote.
  //
  // FINDING, reported rather than engineered around: a direct order
  // still travels the PRICING_PROPOSED status mechanically — the
  // lifecycle has one pricing step and every route passes through it.
  // The mechanics are untouched. What changes is every LABEL on that
  // step, because "Propose price to customer" is a lie on a route where
  // the customer already agreed the price and authorised the work.
  const isDirectOrder =
    ew.request_intent === "DIRECT_AGREED_PRICE_ORDER";

  /** W-FIX4 — THE DECIDING FACT IS WHETHER A CUSTOMER APPROVAL STEP
   *  EXISTS, not which of the three intents this is.
   *
   *  DIRECT_AGREED_PRICE_ORDER (the customer already agreed the price)
   *  and AUTO_START_AFTER_PRICING (the customer pre-authorised starting
   *  once priced) both END at the provider: entering prices starts the
   *  work. Only REQUEST_QUOTE puts the customer in the loop, and only
   *  it may say "proposal" or "send to customer".
   *
   *  The pricing MECHANICS are untouched on every route — the lifecycle
   *  has one pricing step and all three pass through PRICING_PROPOSED.
   *  What changes is every word around it. */
  const noCustomerApproval = isDirectOrder || isAutoStart;

  /* W-PLAN — THE LAW: planning gates pricing. The same four facts the
     server's gate reads (`planning.plan_requirements`), derived from
     the rows the page already holds so the entry point can SAY the
     plan (complete: the one-line summary; incomplete: only the missing
     pieces). The server stays the authority — these lines predict its
     answer, the 400 code `plan_requirements_unmet` is still handled. */
  const planWorkerCount = planAssignments.filter(
    (a) => a.role === "WORKER",
  ).length;
  const planManagerCount = planAssignments.filter(
    (a) => a.role === "MANAGER",
  ).length;
  const planHoursValue = (() => {
    const budget = Number.parseFloat(ew.budget_hours ?? "");
    if (Number.isFinite(budget) && budget > 0) return budget;
    const distributed = Number.parseFloat(ew.planned_hours_total ?? "");
    return Number.isFinite(distributed) && distributed > 0
      ? distributed
      : 0;
  })();
  const planGateMissing: string[] = [
    ...(planWorkerCount === 0 ? ["plan_staff"] : []),
    ...(planManagerCount === 0 ? ["plan_manager"] : []),
    ...(ew.provider_planned_date ? [] : ["plan_start_date"]),
    ...(planHoursValue > 0 ? [] : ["plan_hours"]),
  ];
  const planGateComplete = planGateMissing.length === 0;
  const planGateSummary = planGateComplete
    ? [
        t("plan_gate.summary_people", { count: planWorkerCount }),
        t("plan_gate.summary_managers", { count: planManagerCount }),
        ew.provider_planned_end_date &&
        ew.provider_planned_end_date !== ew.provider_planned_date
          ? `${formatDate(ew.provider_planned_date ?? "")} \u2013 ${formatDate(
              ew.provider_planned_end_date,
            )}`
          : formatDate(ew.provider_planned_date ?? ""),
        t("plan_gate.summary_hours", {
          hours: planHoursValue.toFixed(planHoursValue % 1 === 0 ? 0 : 2),
        }),
      ].join(" \u00b7 ")
    : "";

  // Sprint 31 — meaningful, step-aware label for each provider workflow
  // button (falls back to the generic "Move to <status>").
  const providerActionLabel = (target: ExtraWorkStatus): string => {
    if (target === "CANCELLED") return t("detail.action_cancel");
    // W-UX1 §3 — the one step whose name depends on the route.
    if (ew.status === "UNDER_REVIEW" && target === "PRICING_PROPOSED") {
      return noCustomerApproval
        ? t("detail.action_start_the_work")
        : t("detail.action_send_proposal_for_review");
    }
    const key = PROVIDER_ACTION_I18N[`${ew.status}->${target}`];
    // W-FIX4 §2 — "Revise & re-propose" names a proposal; on a
    // no-approval route the same move is just revising the price, and
    // the neutral label for that already exists.
    const gatedKey =
      noCustomerApproval && key === "detail.action_revise_after_reject"
        ? "detail.action_revise_pricing"
        : key;
    return gatedKey
      ? t(gatedKey)
      : t("detail.workflow_move_to", { label: tStatusLabel(t, target) });
  };

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

  /* P-9 C4 — starting the work: does the approved price cover what the
     customer asked for? Only a quote can differ from the cart; on the
     agreed-price route the cart IS the price (no comparison, calm
     confirm). While the approved quote's lines are still loading there
     is nothing to compare yet. */
  const startCoverage = approvedProposalDetail
    ? compareCoverage(
        cartCoverageLines(ew.line_items, t),
        approvedProposalDetail.lines.map((line) => ({
          id: line.id,
          service: line.service,
          label: (line.service_name || line.description || "").trim(),
          quantity: line.quantity,
        })),
      )
    : null;
  /* P-9 C5 — which hours surface the Money tab shows in this phase. */
  const hoursPanelMode = HOURS_PANEL_MODE[ew.display_phase];

  // Sprint 30 Batch 30.1 — retry-spawn button is the recovery path
  // for EWs that landed in CUSTOMER_APPROVED with zero spawned
  // tickets (legacy data from before the auto-spawn fix shipped). The
  // backend gate matches: SUPER_ADMIN / COMPANY_ADMIN only, status
  // must be CUSTOMER_APPROVED, no tickets yet.
  const canRetrySpawn =
    isProviderAdmin(me?.role) &&
    ew.status === "CUSTOMER_APPROVED" &&
    spawnedTickets.length === 0;

  // P-1 §5 — the Details card has two possible tenants; with neither it
  // does not render (a bare "Details" header is furniture, not a fact).
  // `PlanSummary` returns null without a plan, so the same test decides
  // both the section and the card.
  const showPlanSummary =
    isProvider &&
    Boolean(
      ew.budget_hours ||
        (ew.planned_hours ?? []).length > 0 ||
        ew.provider_planned_date ||
        ew.provider_planned_end_date ||
        ew.file_upload_required === true ||
        ew.completion_notes_required === true,
    );
  const showContacts = canSeeCustomerContacts && customerContacts.length > 0;

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
      setActionError(getApiError(err));
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
      // W-PLAN — the server said the plan is not complete. The missing
      // pieces are already ON the card (the inline requirement lines),
      // so the error says where to look instead of repeating them in
      // backend English.
      const code = (err as { response?: { data?: { code?: string } } })
        ?.response?.data?.code;
      setProposalError(
        code === "plan_requirements_unmet"
          ? t("plan_gate.blocked")
          : getApiError(err),
      );
    } finally {
      setProposalBusy(false);
    }
  }

  // P-12 F2 — the request's Done banner slot (§D.24 rule 4).
  // Announced by the pricing ceremonies and the transitions below;
  // the spawned-redirect branch above relays it to the ticket.
  async function handleTransition(
    target: ExtraWorkStatus,
    at: "banner" | "actions" = "banner",
  ) {
    if (!id) return;
    setActionError("");
    setActionRefusal(null);
    setTransitionBusy(target);
    try {
      const updated = await transitionExtraWork(id, { to_status: target });
      setEw(updated);
      // Reaching CUSTOMER_APPROVED (incl. the AUTO_START "Start work")
      // spawns operational tickets — refresh the panel so they appear
      // without a page reload.
      void reloadSpawnedTickets();
      // W14 §4 — the action answers, in a sentence, saying what changed.
      // The owner's words after completing one: "what did I complete?"
      // The answer names the record and states what it did NOT touch,
      // because that was the other half of his question.
      if (target === "COMPLETED") {
        pushToast({
          variant: "success",
          title: t("detail.complete_toast", { title: updated.title }),
        });
      }
      // P-12 F2 — starting the work answers with the banner (on this
      // page, or relayed onto the spawned ticket by the redirect).
      if (target === "IN_PROGRESS" || target === "CUSTOMER_APPROVED") {
        announceDone(safeSessionStorage(), `ew-${updated.id}`, {
          title: t(
            target === "IN_PROGRESS"
              ? "detail.banner_started_title"
              : "detail.banner_approved_title",
          ),
          body: t(
            target === "IN_PROGRESS"
              ? "detail.banner_started_body"
              : "detail.banner_approved_body",
          ),
        });
      }
    } catch (err) {
      // P-8R A3 — the server's reason, in the reader's words, at the
      // control that was pressed, with the door it points to.
      const refusal = describeExtraWorkRefusal(err, t);
      setActionError(refusal.sentence);
      setActionRefusal({ refusal, target, at });
    } finally {
      setTransitionBusy(null);
    }
  }


  async function handleCustomerDecision(
    target: "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED",
    rejectReason?: string,
  ) {
    if (!id) return;
    setActionError("");
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
      const refusal = describeExtraWorkRefusal(err, t);
      setActionError(refusal.sentence);
      setActionRefusal({ refusal, target, at: "banner" });
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
  /* W-TABS Task 3b — the manager write, driven from the plan modal's
     picker (the page's inline select is gone; one owner per fact).
     Same endpoint as before: the bulk-assign body's `managers` group
     (`views_assignments.py` — both-roles shape). The candidate list is
     re-read too so the picker stops offering who was just added. */
  async function addPlanManagers(userIds: number[]) {
    if (userIds.length === 0 || ewId === null) return;
    setManagerBusy(true);
    try {
      // W-FIX1 D10 (audit F35) — the bulk body takes the whole list.
      await bulkAssignExtraWork({
        requests: [ewId],
        managers: userIds,
        mode: "assign",
      });
      setPlanAssignments(await listExtraWorkAssignments(ewId));
      setManagerCandidates(
        await listExtraWorkAssignmentCandidates(ewId, "MANAGER"),
      );
    } catch (err) {
      setPlanError(getApiError(err));
    } finally {
      setManagerBusy(false);
    }
  }

  // P-5 S2.4 — the missing-piece pointer: "X is missing" opens the
  // plan ON X, highlighted, saying what it needs.
  const GATE_FOCUS: Record<string, PlanFocus> = {
    plan_staff: "people",
    plan_manager: "manager",
    plan_start_date: "start",
    plan_hours: "hours",
  };
  async function openPlan(focus: PlanFocus | null = null) {
    setPlanFocus(focus);
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
    void loadPlanCandidates();
  }

  /** W-UX1 §2 — who may still be added to this request, from the
   *  SERVER's eligibility helper rather than "the company's employees".
   *  Sprint 158 §1's argument stands: eligibility comes from the
   *  request's BUILDING and differs per role, and a picker that does not
   *  call the same helper the write validator uses will offer options
   *  that always fail. WORKER only — the plan area distributes hours,
   *  and hours belong to the people doing the work. */
  async function loadPlanCandidates() {
    setPlanCandidatesLoading(true);
    setPlanAssignError("");
    try {
      setPlanCandidates(
        await listExtraWorkAssignmentCandidates(Number(id), "WORKER"),
      );
    } catch {
      setPlanCandidates([]);
    } finally {
      setPlanCandidatesLoading(false);
    }
  }

  /** P-7 S2.1 — the X on a person in the plan modal. ROOT CAUSE of
   *  "cannot remove after Add": this page passed the dialog no remove
   *  handler at all, so the dialog (which renders its X only when one
   *  exists) never showed one here — the ticket page did. The EXISTING
   *  unassign door, `bulk-assign` with `mode: "unassign"`, which now
   *  also clears the person's open plan (the ticket-side ruling).
   *  Both lists re-read from the server, as `assignPlanCrew` does. */
  async function removePlanPerson(userId: number, role: "WORKER" | "MANAGER") {
    if (ewId === null) return;
    setPlanRemoveBusy(true);
    setPlanAssignError("");
    try {
      await bulkAssignExtraWork({
        requests: [ewId],
        ...(role === "MANAGER" ? { managers: [userId] } : { workers: [userId] }),
        mode: "unassign",
      });
      setPlanAssignments(await listExtraWorkAssignments(ewId));
      if (role === "MANAGER") {
        setManagerCandidates(
          await listExtraWorkAssignmentCandidates(ewId, "MANAGER"),
        );
      } else {
        await loadPlanCandidates();
      }
    } catch (err) {
      setPlanAssignError(getApiError(err));
    } finally {
      setPlanRemoveBusy(false);
    }
  }

  /** One bulk call through the EXISTING endpoint, then both lists are
   *  re-read from the server rather than patched locally — the write is
   *  all-or-nothing server-side, so the only honest picture of what
   *  happened is the one it returns. */
  async function assignPlanCrew(userIds: number[]) {
    if (userIds.length === 0) return;
    setPlanAssignBusy(true);
    setPlanAssignError("");
    try {
      await bulkAssignExtraWork({
        requests: [Number(id)],
        workers: userIds,
        mode: "assign",
      });
      const rows = await listExtraWorkAssignments(Number(id));
      setPlanAssignments(rows);
      await loadPlanCandidates();
    } catch (err) {
      setPlanAssignError(getApiError(err));
    } finally {
      setPlanAssignBusy(false);
    }
  }

  /** Plan — and only plan. P-8R A2: the plan door no longer starts the
   *  work on an absent `start`; this page says `start: false` out loud,
   *  and starting is the banner's own "Start the work" step with its
   *  confirm. The response IS the refreshed detail (with a `plan` block
   *  attached), so the page does not re-fetch.
   *
   *  `plan.warnings` carries the overrun. It is surfaced as a toast and
   *  it is NOT an error: the save has already happened by the time the
   *  warning exists, and `planned_hours_overrun` on the refreshed detail
   *  keeps it on the page afterwards. */
  async function submitPlan(payload: ExtraWorkPlanPayload) {
    setPlanBusy(true);
    setPlanError("");
    setPlanRawError(null);
    try {
      const updated = await planExtraWork(Number(id), {
        ...payload,
        start: false,
      });
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
      if (
        updated.plan &&
        !updated.plan.started &&
        updated.plan.start_skipped !== null &&
        updated.plan.start_skipped !== "start_not_requested"
      ) {
        pushToast({ variant: "info", title: t("plan.not_started_notice") });
      }
    } catch (err) {
      setPlanError(describeExtraWorkRefusal(err, t).sentence);
      setPlanRawError(err);
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

  /** P-8R A4 — the decision on the customer's behalf, confirmed in the
   *  amber reason modal. A refusal closes the modal and lands under the
   *  button that was pressed (the decision stays remembered for that). */
  async function submitOverride(reason: string) {
    if (!id || !overrideDecision) return;
    setOverrideError("");
    setOverrideBusy(true);
    try {
      const updated = await transitionExtraWork(id, {
        to_status: overrideDecision,
        is_override: true,
        override_reason: reason,
      });
      setEw(updated);
      setOverrideDecision(null);
      setOverrideDialogOpen(false);
      // Override-approve reaches CUSTOMER_APPROVED → tickets spawn.
      void reloadSpawnedTickets();
    } catch (err) {
      setOverrideDialogOpen(false);
      setOverrideError(describeExtraWorkRefusal(err, t).sentence);
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
      setDirectPublishError(describeExtraWorkRefusal(err, t).sentence);
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
    const reason = cancelReason.trim();
    if (reason === "") return;
    setCancelBusy(true);
    try {
      // `override_reason` satisfies the late-stage override gate (the
      // server coerces is_override there); `note` lands the same words
      // on the history row for the pre-spawn statuses — the reason is
      // recorded whichever pair this is (the TicketExtraWorkCards
      // pattern).
      const updated = await transitionExtraWork(id, {
        to_status: "CANCELLED",
        note: reason,
        override_reason: reason,
      });
      setEw(updated);
      setCancelReason("");
      cancelDialogRef.current?.close();
    } catch (err) {
      const refusal = describeExtraWorkRefusal(err, t);
      setActionError(refusal.sentence);
      setActionRefusal({ refusal, target: "CANCELLED", at: "actions" });
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
      setActionError(getApiError(err));
    } finally {
      setPdfBusy(false);
    }
  }

  /** W-HOURS4 Task 4 — Preview beside Download on the proposal card.
   *  The dialog fetches the SAME route `fetchProposalPdf`
   *  (`api/extraWork.ts`) downloads, as an authenticated blob, and
   *  keeps its own Download button: proposals are preview + download;
   *  only credentials are preview-only. */
  function openProposalPreview() {
    if (!ew || !activeProposal) return;
    proposalPreviewRef.current?.open({
      url: `/extra-work/${ew.id}/proposals/${activeProposal.id}/pdf/`,
      filename: `proposal-${activeProposal.id}.pdf`,
    });
  }

  // W7-D — the billing month, stated ONCE. The old block said the
  // month, whether it was overridden, and separately that no invoice
  // exists yet; the last two are not facts a reader needs beside the
  // first. An absent invoice_date means the month follows completion,
  // which the label says in words rather than by the absence of a
  // badge.
  // P-7 S4.1 — a billing month is WORDS ("oktober 2026"), never
  // "2026-10": the same `monthName` the consequence sentence uses.
  const billingMonthLabel = ew?.invoice_date
    ? monthName(ew.invoice_date)
    : t("detail.billing_follows_completion");

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
      /* W8 §6 — say that it saved. The only feedback was the Save
         button re-disabling itself, which is indistinguishable from a
         button that did nothing, and the owner was not sure the save
         reached the server at all. The month it confirms is the one the
         SERVER echoed back, not the one that was typed, so a server
         that stored something else cannot be reported as success. */
      pushToast({
        variant: "success",
        title: t("detail.billing_saved", {
          month: updated.invoice_date
            ? updated.invoice_date.slice(0, 7)
            : month,
        }),
      });
    } catch (err) {
      const message = getApiError(err);
      setBillingError(message);
      /* A failure has to be as loud as a success, or the quiet case
         reads as the good case. */
      pushToast({ variant: "error", title: t("detail.billing_save_failed") });
    } finally {
      setBillingSaving(false);
    }
  }
  /* W8 §2 — the one move this record is waiting for, and the one
     handler that performs it. Derived from the status by a pure
     resolver so the sentence and the button can never describe
     different moves. */
  const resolvedNextStep = resolveNextStep({
    status: ew.status,
    isProvider,
    hasSpawnedTickets: ew.spawned_tickets.length > 0,
    isInvoiced: ew.is_invoiced,
    // W12 §3 — the two facts the customer sentence needs, from the rows
    // that already own them: the operational status (same resolution the
    // header badge uses) and the day the crew is due.
    ticketStatus: ew.spawned_tickets[0]?.status ?? null,
    plannedDate: ew.provider_planned_date ?? null,
    // W14 §2 — the server's own list of legal moves. Without it this
    // resolver offered "Mark complete" on a request whose ticket owns
    // that decision, and the press 400'd. See `withheldIfServerRefuses`.
    allowedNextStatuses: allowed,
    ticketNo: ew.spawned_tickets[0]?.ticket_no ?? null,
  });
  /* W-FIX4 §2 — the resolver stays route-unaware (it reasons from the
     status, and keeping the route out of it is what keeps it a pure
     status map); the PAGE owns `noCustomerApproval`, so the page swaps
     the proposal-worded keys for their `_start` variants. Only the
     WORDS change: `action` passes through untouched, so the button
     does exactly what it did. */
  const NEXT_STEP_START_KEYS: Record<string, string> = {
    "next.under_review": "next.under_review_start",
    // P-11 A4 — the instant route says the SAME words the list row
    // says: "Price and start". (The quote route's button now reads
    // "Price and send" everywhere — the price's destination is on the
    // button.)
    "next.button.prepare_proposal": "next.button.price_and_start",
    "next.pricing_proposed": "next.pricing_proposed_start",
    "next.customer.pricing_proposed": "next.customer.pricing_proposed_start",
    "next.button.open_proposal": "next.button.open_proposal_start",
    "next.rejected": "next.rejected_start",
    "next.customer.rejected": "next.customer.rejected_start",
  };
  const wordedNextStep = noCustomerApproval
    ? {
        ...resolvedNextStep,
        sentenceKey:
          NEXT_STEP_START_KEYS[resolvedNextStep.sentenceKey] ??
          resolvedNextStep.sentenceKey,
        buttonKey: resolvedNextStep.buttonKey
          ? (NEXT_STEP_START_KEYS[resolvedNextStep.buttonKey] ??
            resolvedNextStep.buttonKey)
          : null,
      }
    : resolvedNextStep;
  /* W-TABS Task 2 — WHAT NEXT tells the truth STEPWISE. While the plan
     is incomplete, pricing is not the next move — the GATE will refuse
     it — so the header says "Plan the work first" and its button opens
     the plan modal directly. The moment the plan completes, the worded
     step above takes over unchanged. Provider-side only (the customer
     never plans), and only on the two statuses whose next move IS
     pricing — every later status keeps its own sentence. */
  const nextStep =
    isProvider &&
    !planGateComplete &&
    (ew.status === "REQUESTED" || ew.status === "UNDER_REVIEW")
      ? {
          sentenceKey: "plan_gate.next_sentence",
          buttonKey: "plan_gate.open_plan",
          action: { kind: "plan" as const },
          waiting: false,
        }
      : wordedNextStep;
  const nextStepBusy =
    proposalBusy ||
    retrySpawnBusy ||
    (nextStep.action.kind === "transition" &&
      transitionBusy === nextStep.action.to);

  // ONE renderer for a workflow status button, used by the primary slot
  // AND by the disclosure. CLAUDE.md records what a second,
  // independently maintained render list costs: the two would drift and
  // only one of them would get the next fix.
  // A const arrow, not a `function` declaration: declarations hoist, so
  // TypeScript analyses their body WITHOUT the `if (!ew)` narrowing
  // above and `ew.status` reads as possibly-null. `providerActionLabel`
  // next door is a const arrow for the same reason.
  const renderWorkflowButton = (target: ExtraWorkStatus) => {
    return (
      <button
        key={target}
        type="button"
        /* W2-B fix 4 — filled green for the forward move, soft red for
           cancel, outlined for everything else. See
           `workflowButtonClass`. */
        className={workflowButtonClass(ew.status, target, {
          hasRepair: canRetrySpawn,
        })}
        disabled={transitionBusy !== null}
        onClick={() => {
          // Sprint 29 Batch 29.8 — CANCELLED still routes through the
          // confirmation dialog so the spawned-tickets warning renders
          // before the destructive transition fires.
          if (target === "CANCELLED") {
            cancelDialogRef.current?.open();
            return;
          }
          // W14 §4 — one door onto completing, wherever the press
          // comes from. The ref is opened INLINE rather than through a
          // helper: `react-hooks/refs` forbids handing a ref-reading
          // function to a callback defined in render scope, and the
          // cancel dialog two lines up is opened the same way.
          if (target === "COMPLETED") {
            setActionError("");
            completeDialogRef.current?.open();
            return;
          }
          // P-8R A4 — starting asks once, naming the plan.
          if (target === "IN_PROGRESS") {
            setActionError("");
            setStartAt("actions");
            startDialogRef.current?.open();
            return;
          }
          void handleTransition(target, "actions");
        }}
        data-testid={
          target === "CANCELLED" ? "extra-work-cancel-button" : undefined
        }
      >
        {transitionBusy === target
          ? t("detail.workflow_working")
          : providerActionLabel(target)}
      </button>
    );
  };

  /** P-8R A3 — the refusal, rendered where it was pressed: under the
   *  banner for the primary action, in the Acties card for the rest.
   *  A `plan_gap` carries the door onto the plan (at its first gap); a
   *  `reason_required` carries the door onto the amber reason modal. */
  const renderActionError = (at: "banner" | "actions") =>
    actionError && (actionRefusal?.at ?? "banner") === at ? (
      <div
        ref={actionErrorRef}
        className="alert-error"
        role="alert"
        style={{ marginBottom: 16 }}
        data-testid="extra-work-action-error"
        data-refusal-kind={actionRefusal?.refusal.kind ?? "generic"}
      >
        <div>{actionError}</div>
        {actionRefusal?.refusal.kind === "plan_gap" && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 8 }}
            onClick={() =>
              void openPlan(
                GATE_FOCUS[actionRefusal.refusal.unmet[0] ?? ""] ?? null,
              )
            }
            data-testid="extra-work-refusal-complete-plan"
          >
            {t("refused.complete_plan")}
          </button>
        )}
        {actionRefusal?.refusal.kind === "reason_required" &&
          (actionRefusal.target === "CUSTOMER_APPROVED" ||
            actionRefusal.target === "CUSTOMER_REJECTED") && (
            <button
              type="button"
              className="btn btn-warning btn-sm"
              style={{ marginTop: 8 }}
              onClick={() => {
                const decision = actionRefusal.target as
                  | "CUSTOMER_APPROVED"
                  | "CUSTOMER_REJECTED";
                setAdvancedOpen(true);
                setOverrideDecision(decision);
                setOverrideError("");
                setOverrideDialogOpen(true);
              }}
              data-testid="extra-work-refusal-give-reason"
            >
              {t("refused.give_reason")}
            </button>
          )}
      </div>
    ) : null;

  const renderPlanButton = () => (
    <button
      type="button"
      className="btn btn-secondary btn-sm"
      onClick={() => void openPlan()}
      data-testid="extra-work-plan-button"
    >
      <CalendarClock size={14} strokeWidth={2.2} aria-hidden="true" />
      {t("plan.open_button")}
    </button>
  );

  function runNextStep() {
    const action = nextStep.action;
    switch (action.kind) {
      case "transition":
        // W14 §4 — the one transition that has something to say for
        // itself asks first. Everything else moves on the press.
        if (action.to === "COMPLETED") {
          setActionError("");
          completeDialogRef.current?.open();
          return;
        }
        if (action.to === "IN_PROGRESS") {
          setActionError("");
          setStartAt("banner");
          startDialogRef.current?.open();
          return;
        }
        void handleTransition(action.to, "banner");
        return;
      case "tab":
        // FE-3 — the billing-month override moved behind Geavanceerd;
        // the one button that leads there opens the fold instead of a
        // tab that no longer holds it.
        if (nextStep.buttonKey === "next.button.set_billing_month") {
          setTab("overview");
          setAdvancedOpen(true);
          return;
        }
        setTab(action.tab);
        return;
      case "plan":
        void openPlan();
        return;
      case "retrySpawn":
        void handleRetrySpawn();
        return;
      case "none":
        return;
    }
  }

  /* FE-3 (Addendum D §D.6 rule 3) — ONE PRIMARY ACTION, in the banner.

     The resolver (`nextStep`) has decided the one move since W8 §2;
     what changes is that nothing else competes with it. The auto-start
     "Werk starten" (the customer pre-authorised it) is the one move
     when it exists; the customer's own approve / reject pair renders
     if this page is ever read by a customer (it is not — §D.3.1 routes
     them to the tracker); "Plan het werk opnieuw" is a repair, so it
     waits behind Geavanceerd even when the resolver names it. */
  const primaryActionNode: ReactNode = canAutoStart ? (
    <button
      type="button"
      className="btn btn-primary"
      disabled={transitionBusy !== null}
      onClick={() => handleTransition("CUSTOMER_APPROVED")}
      data-testid="extra-work-auto-start-button"
      title={t("detail.auto_start_hint")}
    >
      {transitionBusy === "CUSTOMER_APPROVED"
        ? t("detail.auto_start_busy")
        : t("detail.auto_start_button")}
    </button>
  ) : canApproveAsCustomer || canRejectAsCustomer ? (
    <>
      {canApproveAsCustomer && (
        <button
          type="button"
          className="btn btn-primary"
          disabled={transitionBusy !== null}
          onClick={() => handleCustomerDecision("CUSTOMER_APPROVED")}
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
          className="btn btn-danger"
          disabled={transitionBusy !== null}
          onClick={() => setRejectDialogOpen(true)}
          data-testid="extra-work-customer-reject"
        >
          {transitionBusy === "CUSTOMER_REJECTED"
            ? t("detail.workflow_rejecting")
            : t("detail.workflow_reject_button")}
        </button>
      )}
    </>
  ) : nextStep.action.kind === "retrySpawn" ? (
    // P-1 §5 — "accepted but no work was created yet" with no button
    // was a dead end; the repair IS the one move, so the banner carries
    // it (the Geavanceerd copy below keeps its hint).
    canRetrySpawn ? (
      <button
        type="button"
        className="btn btn-primary"
        disabled={retrySpawnBusy}
        onClick={() => {
          void handleRetrySpawn();
        }}
        data-testid="extra-work-retry-spawn-primary"
      >
        {retrySpawnBusy ? t("detail.retry_spawn_busy") : t("next.button.retry_scheduling")}
      </button>
    ) : null
  ) : nextStep.buttonKey ? (
    <>
      <button
        type="button"
        className="btn btn-primary"
        onClick={runNextStep}
        disabled={nextStepBusy}
        data-testid="extra-work-next-button"
      >
        {t(nextStep.buttonKey)}
      </button>
      {/* P-16 (P-14 S4) — the "Price and send" pre-read lives HERE,
          where the pressing happens: the list row only navigates, so
          the sentence that says what the press actually does belongs
          on the detail, under the button that does it. */}
      {(nextStep.buttonKey === "next.button.prepare_proposal" ||
        nextStep.buttonKey === "next.button.price_and_start") && (
        <p
          className="muted small"
          style={{ margin: "6px 0 0" }}
          data-testid="extra-work-next-preread"
        >
          {t(
            nextStep.buttonKey === "next.button.price_and_start"
              ? "next.price_and_start_preread"
              : "next.prepare_proposal_preread",
          )}
        </p>
      )}
    </>
  ) : null;

  // "Andere stappen": the other legal forward moves (never the one the
  // banner already offers, never cancel — that is Geavanceerd), the
  // plan door when planning is not the primary, and the quote PDF.
  const bannerOffersTransition = (target: ExtraWorkStatus): boolean =>
    (nextStep.action.kind === "transition" && nextStep.action.to === target) ||
    (canAutoStart && target === "CUSTOMER_APPROVED");
  const otherStepNodes: ReactNode[] = [
    ...(isProvider && forwardTarget && !bannerOffersTransition(forwardTarget)
      ? [renderWorkflowButton(forwardTarget)]
      : []),
    ...(isProvider && nextStep.action.kind !== "plan" ? [renderPlanButton()] : []),
    ...otherWorkflowTargets
      .filter((target) => target !== "CANCELLED" && !bannerOffersTransition(target))
      .map(renderWorkflowButton),
    // P-8R A4 — the pair appears ONCE per page: the lines card on the
    // Money tab is its home (W-PLANTRUTH §4a), so this fold only offers
    // it while another tab is showing.
    ...(hasActiveProposal && canViewProposalPdf && tab !== "money"
      ? [
          <button
            key="pdf-preview"
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={openProposalPreview}
            data-testid="extra-work-detail-pdf-preview"
          >
            <Eye size={14} strokeWidth={2.2} aria-hidden="true" />
            {t("detail.pdf_preview_button")}
          </button>,
          <button
            key="pdf-download"
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => {
              void handleDownloadPdf();
            }}
            disabled={pdfBusy}
            data-testid="extra-work-detail-pdf-download"
          >
            <FileText size={14} strokeWidth={2.2} aria-hidden="true" />
            {pdfBusy
              ? t("detail.pdf_download_busy")
              : t(
                  noCustomerApproval
                    ? "detail.pdf_download_button_start"
                    : "detail.pdf_download_button",
                )}
          </button>,
        ]
      : []),
  ];

  return (
    <div data-testid="extra-work-detail-page">
      <PageHeader
        backLink={{ to: originBack.to, label: originBack.label }}
        title={ew.title}
      />

      {error && !actionError && (
        <div
          className="alert-error"
          role="alert"
          style={{ marginBottom: 16 }}
          data-testid="extra-work-page-error"
        >
          {error}
        </div>
      )}

      {/* FE-3 (Addendum D §D.0 / §D.4) — THE PAGE OPENS ON THREE ANSWERS.
          The phase banner: the server's `display_phase` (provider
          variant), the one sentence about what happens next (W8 §2's
          resolver, unchanged), and the ONE primary action. The badge soup
          that stood in the context header — request status, ticket
          status, urgency, labels at equal weight — is gone; the raw
          values live behind Geavanceerd. */}
      {ewDone.done && (
        <DoneBanner
          done={ewDone.done}
          onDismiss={ewDone.dismiss}
          testId="extra-work-done"
        />
      )}
      <PhaseBanner
        kind="ew"
        phase={ew.display_phase}
        testId="extra-work-phase-banner"
        sub={
          <span data-testid="extra-work-next-sentence">
            {t(nextStep.sentenceKey, nextStep.sentenceVars)}
          </span>
        }
        action={primaryActionNode}
      />
      {renderActionError("banner")}
      {/* Sprint 187 §2d — say where the decision went when the customer
          is deciding on the quote itself. Purely additive: nothing new
          can be pressed from here. */}
      {ew.status === "PRICING_PROPOSED" && hasOpenProposal && (
        <p
          className="muted small"
          style={{ margin: "-8px 0 14px" }}
          data-testid="extra-work-workflow-decision-on-proposal"
        >
          {t(
            noCustomerApproval
              ? "detail.workflow_decision_on_proposal_start"
              : "detail.workflow_decision_on_proposal",
          )}
        </p>
      )}

      {/* W8 §1 / FE-3 — the four fact blocks, above the tabs and outside
          them, so they are on screen whatever tab is open. The two
          provider editors open right under the block they edit. */}
      <ExtraWorkContextHeader
        ew={ew}
        proposedTotal={
          ew.status === "PRICING_PROPOSED"
            ? (proposals.find((p) => p.status === "SENT")?.total_amount ?? null)
            : null
        }
        urgencyLabel={t(URGENCY_I18N_KEY[ew.urgency] ?? ew.urgency)}
        categoryLabel={
          extraWorkCategoryName(ew) ??
          `${t(CATEGORY_I18N_KEY[ew.category] ?? ew.category)}${
            ew.category === "OTHER" && ew.category_other_text
              ? ` \u2014 ${ew.category_other_text}`
              : ""
          }`
        }
        departmentLabel={
          ew.department_name ? customerLabelName(ew.department_name, t) : null
        }
        workTypeLabel={
          ew.work_type_name ? customerLabelName(ew.work_type_name, t) : null
        }
        billedToLabel={t(billedToKey(ew.billed_to))}
        dueChip={
          ew.days_until_due !== null && ew.days_until_due !== undefined ? (
            <DueChipCore days={ew.days_until_due} hasDeadline />
          ) : undefined
        }
        whatAction={
          isProvider && !ew.labels_locked && !labelsOpen ? (
            <button
              type="button"
              className="facts-edit"
              onClick={() => setLabelsOpen(true)}
              data-testid="extra-work-labels-edit"
            >
              <Pencil size={12} strokeWidth={2} aria-hidden="true" />
              {t("detail.labels_edit_both")}
            </button>
          ) : undefined
        }
        whenAction={
          isProvider && !datesOpen ? (
            <button
              type="button"
              className="facts-edit"
              onClick={() => setDatesOpen(true)}
              data-testid="extra-work-dates-edit"
            >
              <Pencil size={12} strokeWidth={2} aria-hidden="true" />
              {t("detail.dates_edit")}
            </button>
          ) : undefined
        }
      />
      {isProvider && ew.labels_locked && (
        <p className="muted small" data-testid="extra-work-labels-locked" style={{ margin: "-8px 0 14px" }}>
          {ew.labels_locked_invoice
            ? t("detail.labels_locked_by", { number: ew.labels_locked_invoice })
            : t("detail.labels_locked_by_unsent")}{" "}
          {t("detail.labels_locked_howto")}
        </p>
      )}
      {isProvider && (datesOpen || (labelsOpen && !ew.labels_locked)) && (
        <div className="card" data-testid="extra-work-fact-editors">
          <div className="form-section">
            {datesOpen && (
              <DatesEditor
                ew={ew}
                draft={
                  datesDraft ?? {
                    deadline: ew.deadline ?? "",
                    plannedEnd: ew.planned_end_date ?? "",
                  }
                }
                onDraftChange={setDatesDraft}
                onUpdated={(detail) => setEw(detail)}
                onClose={() => {
                  setDatesOpen(false);
                  setDatesDraft(null);
                }}
              />
            )}
            {labelsOpen && !ew.labels_locked && (
              <LabelsEditor
                key={`labels-${ew.id}-${ew.department ?? ""}-${ew.work_type ?? ""}`}
                ew={ew}
                draft={
                  labelsDraft ?? {
                    deptId: ew.department ? String(ew.department) : "",
                    wtId: ew.work_type ? String(ew.work_type) : "",
                  }
                }
                onDraftChange={setLabelsDraft}
                onUpdated={(detail) => setEw(detail)}
                onRefresh={() => void refresh()}
                onClose={() => {
                  setLabelsOpen(false);
                  setLabelsDraft(null);
                }}
              />
            )}
          </div>
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
          {/* W7-D — the page is six screens, not one 4,500px scroll.
              Iterating the exported EW_TABS constant rather than
              repeating buttons: CLAUDE.md records what a second,
              independently maintained render list costs. */}
          <div
            className="composer-toggle ew-detail-tabs"
            role="tablist"
            aria-label={t("detail.tabs_aria")}
          >
            {visibleTabs.map((entry) => (
              <button
                key={entry.key}
                type="button"
                role="tab"
                aria-selected={tab === entry.key}
                className={`composer-toggle-btn ${tab === entry.key ? "active" : ""}`}
                onClick={() => setTab(entry.key)}
                data-testid={`extra-work-tab-${entry.key}`}
              >
                {t(entry.labelKey)}
              </button>
            ))}
          </div>

          {tab === "overview" && (
            <>
          {/* W9 §5 — DESCRIPTION FIRST.

              The owner: "move Description to the very top, above
              Details. Description is important and should be one of the
              first things the user sees."

              It was the LAST group inside the Details card, under dates,
              classification and contacts — so the sentence saying what
              the job actually is arrived after everything filed about
              it. Its own card, above Details, and the notes that are the
              same kind of thing (customer-visible, pricing, manager,
              internal cost) come with it rather than being split from
              the text they annotate. */}
          <div className="card" data-testid="extra-work-description-card">
            <div className="form-section">
              <div className="form-section-title">
                {t("detail.group_description")}
              </div>
              <div data-testid="ew-facts-description">
                <div className="ew-fact-prose">{ew.description}</div>
                {ew.customer_visible_note && (
                  <div className="ew-fact-note">
                    <div className="ew-fact-label">{t("detail.field_customer_visible_note")}</div>
                    <div className="ew-fact-prose">{ew.customer_visible_note}</div>
                  </div>
                )}
                {ew.pricing_note && (
                  <div className="ew-fact-note">
                    <div className="ew-fact-label">{t("detail.field_pricing_note")}</div>
                    <div className="ew-fact-prose">{ew.pricing_note}</div>
                  </div>
                )}
                {isProvider && ew.manager_note && (
                  <div className="ew-fact-note">
                    <div className="ew-fact-label">{t("detail.field_manager_note")}</div>
                    <div className="ew-fact-prose">{ew.manager_note}</div>
                  </div>
                )}
                {isProvider && ew.internal_cost_note && (
                  <div className="ew-fact-note">
                    <div className="ew-fact-label">{t("detail.field_internal_cost_note")}</div>
                    <div className="ew-fact-prose">{ew.internal_cost_note}</div>
                  </div>
                )}
                {isProvider && ew.override_at && (
                  <div className="alert-warning" style={{ marginTop: 12 }}>
                    <strong>{t("detail.override_applied")}</strong>
                    {ew.override_reason && (
                      <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{ew.override_reason}</div>
                    )}
                    <div className="muted small" style={{ marginTop: 4 }}>
                      {formatDateTime(ew.override_at)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
            {/* P-1 §5 — no furniture: the card renders only when it has
                a fact to show (a plan, or contacts that exist). */}
            {(showPlanSummary || showContacts) && (
            <div className="card">
              <div className="form-section">
                <div className="form-section-title">
                  {t("detail.details_section_title")}
                </div>
              {/* W8 §3 — the Details card, grouped by the QUESTION each
                  fact answers, in the order a person reads.

                  It was one flat two-column grid holding Building,
                  Customer, Billed to, Ticket, Requested at, Planned end,
                  Preferred date, Deadline, Department, Work type,
                  Contacts, Routing, Description and the plan block, in
                  none of those orders. The owner: "everything is mixed
                  together and placed in random-looking locations."

                  Customer, building, status and the ticket number are
                  GONE from here. They are in the persistent header now,
                  and printing them twice was part of the clutter. */}
              <div className="ew-facts">
                {/* FE-3 — the dates and the classification read in the fact
                    block above (one owner per fact); what stays here is the
                    PLAN we committed to, and the contacts. */}
                {showPlanSummary && (
                  <section className="ew-facts-group" data-testid="ew-facts-dates">
                    <PlanSummary ew={ew} onEdit={() => void openPlan()} />
                    {ew.started_before_plan && (
                      <p className="muted small" data-testid="ew-header-started-early" style={{ margin: "8px 0 0" }}>
                        {t("list.startedEarlyWhy")}
                      </p>
                    )}
                  </section>
                )}

                {/* CONTACTS — only when there are any (P-1 §5). */}
                {showContacts && (
                  <section className="ew-facts-group" data-testid="ew-facts-contacts">
                    <h4 className="ew-facts-group-title">{t("detail.group_contacts")}</h4>
                    <CustomerContactsPanel contacts={customerContacts} />
                  </section>
                )}
                </div>
            </div>
          </div>
            )}
          {/* FE-3 (Addendum D §D.6 rule 3) — THE ACTIES CARD: everything
              that is NOT the one primary action, behind two folds.
              "Andere stappen" holds the other legal forward moves, the
              plan door and the quote PDF; "Geavanceerd" holds every
              correction and override with its EXISTING warning + audit
              surface (the decision on the customer's behalf with its
              reason form, direct publish with its dialog, the billing-
              month override, cancel with its confirm dialog, "Plan het
              werk opnieuw" only when it is actionable) and the raw
              values the banner replaced. Every button still comes from
              `allowed_next_statuses` / `actions.can_*`. */}
          <div
            className="card ew-workflow-card"
            data-testid="extra-work-detail-actions"
            aria-label={t("detail.actions_aria_label")}
          >
            <div className="form-section">
              <div className="ew-detail-actions-section-title">
                {t("detail.actions_card_title")}
              </div>
              {renderActionError("actions")}
              {otherStepNodes.length > 0 && (
                <div className="ew-workflow-other" style={{ marginTop: 0 }}>
                  <button
                    type="button"
                    className="workflow-corrections-toggle"
                    aria-expanded={otherActionsOpen}
                    onClick={() => setOtherActionsOpen((open) => !open)}
                    data-testid="extra-work-other-actions-toggle"
                  >
                    {otherActionsOpen ? (
                      <ChevronDown size={13} strokeWidth={2.6} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={13} strokeWidth={2.6} aria-hidden="true" />
                    )}
                    {t("detail.other_actions", { count: otherStepNodes.length })}
                  </button>
                  {otherActionsOpen && (
                    <div
                      className="ew-workflow-other-list"
                      data-testid="extra-work-other-actions-list"
                    >
                      {otherStepNodes}
                    </div>
                  )}
                </div>
              )}
              {isProvider && (
                <div className="action-fold">
                  <button
                    type="button"
                    className="workflow-corrections-toggle"
                    aria-expanded={advancedOpen}
                    onClick={() => {
                      // Closing the fold takes a half-typed override
                      // reason with it.
                      if (advancedOpen) {
                        setOverrideDecision(null);
                                      setOverrideError("");
                      }
                      setAdvancedOpen((open) => !open);
                    }}
                    data-testid="extra-work-advanced-toggle"
                  >
                    {advancedOpen ? (
                      <ChevronDown size={13} strokeWidth={2.6} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={13} strokeWidth={2.6} aria-hidden="true" />
                    )}
                    {advancedOpen ? t("detail.advanced_hide") : t("detail.advanced")}
                  </button>
                  {advancedOpen && (
                    <div data-testid="extra-work-advanced">
                      {providerOverrideAvailable && (
                        <div className="action-fold-heading">
                          {t("detail.advanced_override_heading")}
                        </div>
                      )}
                      <div className="ew-workflow-actions">
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
                            /* P-7 S3.1 — approving on the customer's
                               behalf is AMBER here too: the one
                               exceptional-act colour, the same as the
                               agenda's button. */
                            className={
                              target === "CUSTOMER_APPROVED"
                                ? "btn btn-warning btn-sm"
                                : "btn btn-danger btn-sm"
                            }
                            onClick={() => {
                              setOverrideDecision(target);
                              setOverrideError("");
                              setOverrideDialogOpen(true);
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
                          {isArmed && overrideError && (
                            <div
                              className="alert-error"
                              role="alert"
                              data-testid="extra-work-override-error"
                              style={{ marginTop: 6 }}
                            >
                              {overrideError}
                            </div>
                          )}
                        </div>
                      );
                    })}
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
                      </div>
                      {canRetrySpawn && (
                        <div data-testid="extra-work-retry-spawn-block" style={{ marginTop: 10 }}>
                          <p className="muted small" style={{ margin: "0 0 6px" }}>
                            {t("detail.retry_spawn_advanced_hint")}
                          </p>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
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
                        </div>
                      )}
                      {/* W7-D — the billing month, stated ONCE, with the
                          control that changes it beside it. Moved here
                          from the Money tab: overriding the month is a
                          correction of the Addendum B completion-month
                          rule, not a routine step. */}
                      {isProvider && (
                        <div className="field ew-billing-line" data-testid="extra-work-billing-override">
                          <div className="muted small">
                            {t("detail.billing_section_title")}
                          </div>
                          <div className="ew-billing-row">
                            <strong data-testid="extra-work-billing-month">
                              {billingMonthLabel}
                            </strong>
                            <input
                              type="month"
                              className="field-input ew-billing-input"
                              value={billingDraft ?? (ew.invoice_date ? ew.invoice_date.slice(0, 7) : "")}
                              onChange={(e) => setBillingDraft(e.target.value)}
                              aria-label={t("detail.billing_month_input_label")}
                              data-testid="extra-work-billing-month-input"
                            />
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              disabled={
                                billingSaving ||
                                (billingDraft ?? (ew.invoice_date ? ew.invoice_date.slice(0, 7) : "")) ===
                                  (ew.invoice_date ? ew.invoice_date.slice(0, 7) : "")
                              }
                              onClick={() => void saveBillingMonth()}
                              data-testid="extra-work-billing-save"
                            >
                              {t("detail.billing_save")}
                            </button>
                          </div>
                          {/* P-4 (Part C) — the consequence, in one sentence:
                              which month, whose invoice, where to find it,
                              and that nothing is sent by itself. Addendum B
                              unchanged. */}
                          <p className="muted small" style={{ margin: "6px 0 0" }} data-testid="extra-work-billing-consequence">
                            {t(
                              ew.invoice_date
                                ? "billing.consequence_month"
                                : "billing.consequence_completion",
                              {
                                month: billingMonthWords(ew, t),
                                customer: ew.customer_name,
                              },
                            )}
                          {ew.customer_invoice_day != null && (
                              <span data-testid="extra-work-invoice-day">
                                {" "}
                                {t("billing.customer_invoice_day", {
                                  customer: ew.customer_name,
                                  day:
                                    ew.customer_invoice_day === "LAST_OF_MONTH"
                                      ? t("common:facturatie.day_last")
                                      : t("common:facturatie.day_of_month", {
                                          day: ew.customer_invoice_day,
                                        }),
                                })}
                              </span>
                            )}
                          </p>
                          {billingError && (
                            <div className="alert-error" style={{ marginTop: 8 }}>
                              {billingError}
                            </div>
                          )}
                        </div>
                      )}
                      {allowed.includes("CANCELLED") && (
                        <>
                          <div className="action-fold-heading">
                            {t("detail.advanced_danger_heading")}
                          </div>
                          <div className="ew-workflow-actions">
                            {renderWorkflowButton("CANCELLED")}
                          </div>
                        </>
                      )}
                      <div className="action-fold-heading">
                        {t("detail.advanced_raw_title")}
                      </div>
                      <dl className="action-fold-raw" data-testid="extra-work-raw-values">
                        <dt>{t("detail.raw_status")}</dt>
                        <dd>
                          <StatusBadge
                            status={{ kind: "extra-work", value: ew.status }}
                            testId="extra-work-header-status"
                          />{" "}
                          <code>{ew.status}</code>
                        </dd>
                        <dt>{t("detail.raw_intent")}</dt>
                        <dd data-testid="extra-work-raw-intent">
                          {ew.request_intent && INTENT_I18N_KEY[ew.request_intent]
                            ? t(INTENT_I18N_KEY[ew.request_intent])
                            : t("detail.raw_intent_none")}{" "}
                          <code>{ew.request_intent ?? "—"}</code>
                        </dd>
                        <dt>{t("detail.routing_decision_label")}</dt>
                        <dd data-testid="extra-work-detail-routing-decision">
                          {ew.routing_decision === "INSTANT"
                            ? t("detail.routing_decision_instant")
                            : t(noCustomerApproval ? "detail.routing_decision_start" : "detail.routing_decision_proposal")}{" "}
                          <code>{ew.routing_decision}</code>
                        </dd>
                      </dl>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* FE-3 (§D.4) — the folded timeline, the provider's reading of
              the same story the customer tracker tells. */}
          <section className="card" data-testid="extra-work-timeline-card">
            <div className="form-section">
              <div className="form-section-title">{t("detail.timeline_title")}</div>
              {timeline.length === 0 ? (
                <p className="muted small" style={{ margin: 0 }}>
                  {t("detail.timeline_empty")}
                </p>
              ) : (
                <MeerwerkTimeline
                  entries={timeline}
                  ariaLabel={t("detail.timeline_title")}
                  testIdPrefix="extra-work-timeline"
                />
              )}
            </div>
          </section>
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
                      {/* W17 §3 — once the work exists, opening it IS
                          the next step, so the row's one door is a
                          button that says so. The title is a name, not
                          a second door to the same place (the owner's
                          rule 3; W14 §3 measured what duplicate doors
                          do to Back). Key lives in ticket_detail (this
                          sprint's bundle). */}
                      {/* Not `.ew-spawned-ticket-link`: that class
                          hover-underlines, which promises a click this
                          span no longer answers. */}
                      <span style={{ fontSize: 14, fontWeight: 500 }}>
                        #{ticket.id} {ticket.title}
                      </span>
                      <StatusBadge
                        status={{ kind: "ticket", value: ticket.status }}
                        variant="cell"
                      />
                      <Link
                        to={`/tickets/${ticket.id}`}
                        className="btn btn-primary btn-sm"
                        data-testid={`extra-work-open-ticket-${ticket.id}`}
                      >
                        {t("ticket_detail:ew_open_work")}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}
            </>
          )}
          {tab === "money" && (
            <>
          {/* ----- Cart line items (Sprint 28 Batch 6; RF-14 collapsible:
              open while the request is still pre-decision, collapsed once
              it moved on — the header keeps count + final total visible.
              Keyed by EW id so navigating between EWs re-derives the
              default state instead of carrying the previous card's.) ----- */}
          {/* W8 §4 — open. It collapsed itself once the request moved
              past PRICING_PROPOSED, so on a job in progress the Money
              tab opened with its priced lines hidden. The count and
              total that justified the collapsed header are the table's
              own first and last figures. */}
          <div
            className="card"
            data-testid="extra-work-detail-line-items"
            ref={pricingLinesAnchor}
          >
            <div className="form-section">
              <div className="form-section-title">
                {t("detail.line_items_section_title")}
              </div>
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
            </div>
          </div>
          {/* W-PLANTRUTH §4a — NO PREVIEW CARD. This was a card of its
              own, carrying a heading that said "Preview" and a sentence
              that said "Fetches the proposal PDF" — over two buttons
              that already say Preview and Download. Three ways of
              saying one thing, in a box, above the document it is
              about. The card is gone; the PAIR is the one home, at the
              bottom of the lines it belongs to, which is where the
              ticket's Money tab already keeps the same pair. */}
          {hasActiveProposal && canViewProposalPdf && (
            <div
              className="ew-pdf-actions"
              data-testid="extra-work-preview-actions"
            >
              {/* W-HOURS5 Task 9 — an eye before Preview, a download
                  glyph before the download. */}
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={openProposalPreview}
                data-testid="extra-work-preview-open"
              >
                <Eye size={14} strokeWidth={2.2} aria-hidden="true" />
                {t("detail.pdf_preview_button")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void handleDownloadPdf()}
                disabled={pdfBusy}
                data-testid="extra-work-preview-pdf"
              >
                <Download size={14} strokeWidth={2.2} aria-hidden="true" />
                {pdfBusy
                  ? t("detail.proposal_pdf_busy")
                  : t(noCustomerApproval ? "detail.proposal_pdf_start" : "detail.proposal_pdf")}
              </button>
            </div>
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
                noCustomerApproval={noCustomerApproval}
                customerName={ew.customer_name}
                onOpenPlan={(unmet) =>
                  void openPlan(GATE_FOCUS[unmet[0] ?? ""] ?? null)
                }
                requestLines={ew.line_items.map((item) => ({
                  id: item.id,
                  label:
                    (item.service_name || item.custom_description || "").trim() ||
                    `#${item.id}`,
                  quantity: String(item.quantity),
                  unit_type: item.unit_type,
                  service: item.service,
                  note: item.customer_note?.trim() || undefined,
                }))}
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
                    {t(noCustomerApproval ? "detail.proposal_builder_title_start" : "detail.proposal_builder_title")}
                  </div>
                  {/* W-PLAN — the pricing entry point states the
                      plan. Complete: one line ("3 people · 1 manager ·
                      Aug 29\u201331 · 12h"). Incomplete: ONLY the
                      missing pieces (R2 — never re-ask for what the
                      record already has), each with its nearest fix —
                      the manager inline (the one fact the plan dialog
                      cannot set), everything else through "Plan the
                      work". */}
                  {planGateComplete ? (
                    <p
                      className="muted small"
                      style={{ marginTop: 0 }}
                      data-testid="extra-work-plan-gate-summary"
                    >
                      {planGateSummary}
                    </p>
                  ) : (
                    <div
                      className="ew-plan-gate"
                      data-testid="extra-work-plan-gate-missing"
                    >
                      <div className="muted small" style={{ fontWeight: 600 }}>
                        {t("plan_gate.title")}
                      </div>
                      <ul className="muted small" style={{ margin: "4px 0 8px", paddingLeft: 18 }}>
                        {planGateMissing.map((key) => (
                          <li key={key} data-testid={`plan-gate-${key}`}>
                            {/* P-5 S2.4 — each missing piece is a door
                                onto exactly that part of the plan. */}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => void openPlan(GATE_FOCUS[key] ?? null)}
                              title={t("plan_gate.point_at")}
                              data-testid={`plan-gate-open-${key}`}
                            >
                              {t(`plan_gate.missing_${key.replace("plan_", "")}`)}
                            </button>
                          </li>
                        ))}
                      </ul>
                      {/* W-TABS Task 3b — the manager is assigned IN
                          the plan modal now (one owner); the line above
                          says it is missing, the button below opens the
                          place that fixes it. */}
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() =>
                          void openPlan(GATE_FOCUS[planGateMissing[0]] ?? null)
                        }
                        data-testid="extra-work-plan-gate-open-plan"
                      >
                        {t("plan_gate.open_plan")}
                      </button>
                    </div>
                  )}
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
                      ? t(noCustomerApproval ? "detail.proposal_preparing_start" : "detail.proposal_preparing")
                      : t(noCustomerApproval ? "detail.proposal_prepare_start" : "detail.proposal_prepare")}
                  </button>
                </div>
              </div>
            )}

              {/* W7-D — ONE LINE, ONE CONTROL.
                  This was five elements for a single idea: a heading,
                  "Bills in 2026-03 (overridden)", "Not yet invoiced",
                  an override field with its own Save, and a "Use
                  completion month" button. Four of them are gone. The
                  month is stated once and the control that changes it
                  sits beside it; whether the month was overridden or
                  derived is not a second fact a reader needs, and
                  "not yet invoiced" is already the absence of an
                  invoice date. */}
          {/* Sprint 8A-fix — provider-only actual-hours entry for the
              active hourly line set (approved-proposal lines or INSTANT
              cart lines). Keyed by `actualHoursPanelKey` so a save
              re-seeds the inputs from refreshed data without a
              prop-derived resync effect; the proposal case also re-fetches
              the approved proposal's detail so entered hours surface. */}
          {/* P-9 C5 — hours worked exist once the work has started. Before
              that: the planned hours and one sentence; after the
              invoice: the saved hours, read only. */}
          {isProvider &&
            activeHourlyLines.length > 0 &&
            hoursPanelMode === "before" && (
              <div
                className="card"
                style={{ marginBottom: 16 }}
                data-testid="extra-work-hours-before-start"
              >
                <div className="form-section">
                  <div className="form-section-title">
                    {t("detail.actual_hours_section_title")}
                  </div>
                  {planHoursValue > 0 && (
                    <p style={{ margin: "0 0 4px" }} data-testid="extra-work-hours-planned">
                      {t("detail.hours_planned_line", {
                        hours: t("plan_gate.summary_hours", {
                          hours: planHoursValue.toFixed(planHoursValue % 1 === 0 ? 0 : 2),
                        }),
                      })}
                    </p>
                  )}
                  <p className="muted small" style={{ margin: 0 }}>
                    {t("detail.hours_before_start")}
                  </p>
                </div>
              </div>
            )}
          {/* P-13 B — the three-block Money story (Agreed → Worked →
              On the invoice), the ONE component this page shares with
              the spawned ticket's Money tab. It carries the hours
              panel (block 2) inside, so the old standalone panel mount
              is gone. */}
          {isProvider &&
            (hoursPanelMode === "edit" || hoursPanelMode === "read_only") && (
            <div
              className="card"
              style={{ marginBottom: 16 }}
              data-testid="extra-work-money-story"
            >
              <div className="form-section">
                <MoneyStory
                  ew={ew}
                  approvedProposal={approvedProposal}
                  approvedProposalDetail={approvedProposalDetail}
                  locked={finalAmountLocked}
                  onUpdated={(detail) => {
                    setEw(detail);
                    if (approvedProposalId !== null) {
                      void reloadApprovedProposalDetail();
                    }
                  }}
                  // P-11 B3 — the "no matching line" sentence's door:
                  // land on the line-items card, lit for a moment.
                  onAddLine={() => pointAtMissingPiece("pricing-lines")}
                />
              </div>
            </div>
          )}
            </>
          )}
          {tab === "people" && (
            <>
          {/* W8 §4 — NOT collapsed. The whole tab was one closed card,
              which renders as an empty page with a button on it. The
              collapse existed to fight a nine-card scroll that the tabs
              already removed.

              W8 §5 — and NOT `bare`. Bare stripped the card's title and
              its one-line purpose, which is what made this read as
              copy-pasted: a table of names with no statement of what it
              is for. The card states who is on this job, and its Assign
              control sits at the top where the action belongs. */}
          {isProvider && ew !== null && (
            <div className="card" data-testid="extra-work-assignments-card">
              <div className="form-section">
                <ExtraWorkAssignmentCard
                  extraWorkId={ew.id}
                  /* W-FIX1 C2 (audit F32) — a People-tab change re-reads
                     the gate's crew, so WHAT NEXT and the plan gate stop
                     saying "assign people first" about people just added. */
                  onChanged={() => setAssignmentsNonce((n) => n + 1)}
                />
              </div>
            </div>
          )}
            </>
          )}
          {tab === "messages" && (
            <>
          <section
            className="card ew-messages-card"
            data-testid="extra-work-messages-panel"
          >
            <div className="form-section">
              <div className="form-section-title">{t("messages.title")}</div>

              {/* RF-11 — restyled in the inbox design language: per-message
                  avatars, explicit visibility badges, tighter layout.
                  Presentation only — posting/visibility unchanged. */}
              {/* TU — the ONE state line this surface gains. Not an
                  explanation: it is where the conversation is. */}
              {!isProvider && threadIsFrozen && (
                <p
                  className="muted small"
                  data-testid="ew-thread-continues-on-job"
                >
                  {t("thread_continues_on_job")}
                </p>
              )}

              {!isProvider && threadIsFrozen ? (
                <div
                  className="ew-message-thread"
                  data-testid="ew-message-thread-merged"
                >
                  {mergedMessages.length === 0 ? (
                    <p className="muted small">{t("messages.empty")}</p>
                  ) : (
                    mergedMessages.map((m) => (
                      <div
                        key={m.key}
                        className="ew-msg"
                        data-testid="ew-merged-message"
                        data-on-job={m.onJob ? "true" : "false"}
                      >
                        <div className="ew-msg-head">
                          <span className="ew-msg-author">{m.author}</span>
                          <span className="ew-msg-time muted small">
                            {formatDateTime(m.created_at)}
                          </span>
                        </div>
                        <div className="ew-msg-body">{m.body}</div>
                      </div>
                    ))
                  )}
                </div>
              ) : (
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
              )}

              {/* TU — on a spawned request the customer writes to the
                  JOB, not to this frozen thread. One textarea, one
                  submit; the tier toggle is absent because a customer
                  has exactly one customer-visible tier on a ticket
                  (PUBLIC_REPLY) and a toggle with one option is a
                  control that decides nothing.

                  ABSENT, not disabled, when the server has not said
                  they may post: an unreachable ticket or a missing
                  `can_post_public_reply` leaves the history readable
                  and no composer at all. */}
              {!isProvider && threadIsFrozen ? (
                canWriteOnJob && (
                  <form
                    onSubmit={submitJobMessage}
                    data-testid="ew-job-message-composer"
                    style={{ marginTop: 12 }}
                  >
                    <textarea
                      className="field-textarea"
                      rows={3}
                      value={ewMessageText}
                      disabled={jobSending}
                      onChange={(event) =>
                        setEwMessageText(event.target.value)
                      }
                      data-testid="ew-job-message-input"
                    />
                    {jobError && (
                      <div
                        className="alert-error"
                        role="alert"
                        data-testid="ew-job-message-error"
                      >
                        {jobError}
                      </div>
                    )}
                    <div className="assign-actions">
                      <button
                        type="submit"
                        className="btn btn-primary btn-sm"
                        disabled={jobSending || !ewMessageText.trim()}
                        data-testid="ew-job-message-send"
                      >
                        {jobSending
                          ? t("messages.sending")
                          : t("messages.post")}
                      </button>
                    </div>
                  </form>
                )
              ) : (
              ewComposerTiers.length > 0 && (
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
              )
              )}
            </div>
          </section>
            </>
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
          initialFocus={planFocus}
          assignments={planAssignments}
          assignmentsLoading={planAssignmentsLoading}
          // R2 — the picker offers ONLY the rest. Filtered here rather
          // than in the dialog so "who is already on this" has exactly
          // one owner on this page.
          candidates={planCandidates.filter(
            (c) => !planAssignments.some((a) => a.user_id === c.id),
          )}
          candidatesLoading={planCandidatesLoading}
          assignBusy={planAssignBusy}
          assignError={planAssignError}
          onAssign={(userIds) => void assignPlanCrew(userIds)}
          onRemovePerson={(userId) => void removePlanPerson(userId, "WORKER")}
          onRemoveManager={(userId) => void removePlanPerson(userId, "MANAGER")}
          removeBusy={planRemoveBusy}
          managerCandidates={managerCandidates.filter(
            (c) =>
              !planAssignments.some(
                (a) => a.user_id === c.id && a.role === "MANAGER",
              ),
          )}
          managerBusy={managerBusy}
          onAssignManagers={(userIds) => void addPlanManagers(userIds)}
          busy={planBusy}
          error={planError}
          rawError={planRawError}
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

      {/* P-8R A4 — deciding on the customer's behalf: the amber reason
          modal (the drawer's pattern), never an inline form. */}
      <RejectReasonDialog
        open={overrideDialogOpen && overrideDecision !== null}
        tone="warning"
        title={
          overrideDecision === "CUSTOMER_APPROVED"
            ? t("detail.proposal_override_approve_title")
            : t("detail.proposal_override_reject_title")
        }
        description={t("detail.proposal_override_desc")}
        placeholder={t("detail.override_reason_placeholder")}
        confirmLabel={
          overrideDecision
            ? t("detail.override_confirm", {
                label: tStatusLabel(t, overrideDecision),
              })
            : undefined
        }
        onCancel={() => {
          setOverrideDialogOpen(false);
          setOverrideDecision(null);
          setOverrideError("");
        }}
        onConfirm={(reason) => {
          void submitOverride(reason);
        }}
      />
      {/* P-8R A4 — "Start the work" asks once and names the plan. */}
      <ConfirmDialog
        ref={startDialogRef}
        title={t("detail.start_dialog_title")}
        body={
          <div data-testid="extra-work-start-dialog">
            {planGateComplete ? (
              <p data-testid="extra-work-start-dialog-plan">
                {t("detail.start_dialog_plan", { plan: planGateSummary })}
              </p>
            ) : (
              <div data-testid="extra-work-start-dialog-no-plan">
                <p>{t("detail.start_dialog_no_plan")}</p>
                <ul style={{ margin: "4px 0 8px", paddingLeft: 18 }}>
                  {planGateMissing.map((key) => (
                    <li key={key}>
                      {t(`plan_gate.missing_${key.replace("plan_", "")}`)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {/* P-9 C4 — the same coverage block as the send confirm. */}
            <CoverageNotice coverage={startCoverage} />
            <p className="muted small">
              {t("detail.start_dialog_question", { title: ew.title })}
            </p>
          </div>
        }
        confirmLabel={coverageConfirmLabel(
          t,
          startCoverage,
          "start",
          t("detail.start_dialog_confirm"),
        )}
        busy={transitionBusy === "IN_PROGRESS"}
        busyLabel={t("detail.workflow_working")}
        onConfirm={async () => {
          await handleTransition("IN_PROGRESS", startAt);
          startDialogRef.current?.close();
        }}
      />
      {/* W-HOURS4 Task 4 — the proposal card's preview. Rendered
          UNCONDITIONALLY and driven through the ref (CLAUDE.md's rule
          for a native <dialog>); `withDownload` stays on. */}
      <PdfPreviewDialog ref={proposalPreviewRef} />
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
            {/* P-16 (P-14 S4) — the required why. The server refuses a
                cancel without one (cancel_note_required); the reason
                lands on the timeline as the history note. */}
            <label
              className="field"
              style={{ marginTop: 12, display: "block" }}
            >
              <span className="field-label">
                {t("detail.cancel_dialog_reason_label")}
              </span>
              <textarea
                rows={2}
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                placeholder={t("detail.cancel_dialog_reason_placeholder")}
                data-testid="extra-work-cancel-reason"
              />
            </label>
          </div>
        }
        confirmLabel={t("detail.cancel_dialog_confirm")}
        cancelLabel={t("detail.cancel_dialog_keep")}
        onConfirm={handleConfirmCancel}
        busy={cancelBusy}
        confirmDisabled={cancelReason.trim() === ""}
        destructive
      />

      {/* W14 §4 — WHAT COMPLETING AN EXTRA WORK MEANS FOR ITS TICKET.

          The owner completed one and noticed the ticket was untouched:
          "good that it does not touch the ticket, but also absurd --
          what did I complete?" Both halves of that are fair, and the
          rule the code already enforces answers them. It is written
          here because until now it was written nowhere a person could
          read.

          COMPLETING AN EXTRA WORK NEVER COMPLETES A TICKET. It cannot,
          because the two cases are exhaustive and neither leaves room
          for it:

            * The request HAS an operational ticket. Then the ticket is
              the authority on whether the work is done (Sprint 181 §1),
              this button is not offered at all, and the server refuses
              the move with `operational_status_follows_ticket` if
              anything asks for it anyway. The Extra Work's own status
              FOLLOWS the ticket, automatically, when the ticket
              finishes.
            * The request has NO ticket. Then there is nothing to touch,
              and completing it closes the REQUEST -- for reporting and
              for billing -- and nothing else.

          So the dialog says which of the two the operator is standing
          in, and never asks a bare "are you sure".

          Rendered unconditionally and driven by the ref (CLAUDE.md §3):
          a `{cond && <ConfirmDialog/>}` mounts an INVISIBLE dialog and
          the button that opens it looks dead. */}
      <ConfirmDialog
        ref={completeDialogRef}
        title={t("detail.complete_dialog_title")}
        body={
          <div>
            <p style={{ margin: "0 0 8px" }}>
              {ew.spawned_tickets.length > 0
                ? t("detail.complete_dialog_body_with_ticket")
                : t("detail.complete_dialog_body_no_ticket")}
            </p>
            <p className="muted small" style={{ margin: 0 }}>
              {t("detail.complete_dialog_billing")}
            </p>
          </div>
        }
        confirmLabel={t("detail.complete_dialog_confirm")}
        onConfirm={async () => {
          await handleTransition("COMPLETED");
          completeDialogRef.current?.close();
        }}
        busy={transitionBusy === "COMPLETED"}
      />
    </div>
  );
}





