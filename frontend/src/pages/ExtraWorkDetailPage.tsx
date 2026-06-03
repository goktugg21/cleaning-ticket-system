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
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, FileSearch, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";

import axios from "axios";

import { listCustomerContacts } from "../api/admin";
import { getApiError } from "../api/client";
import {
  createExtraWorkPricingItem,
  createProposal,
  deleteExtraWorkPricingItem,
  directPublishProposal,
  fetchProposalPdf,
  getProposalDetail,
  getExtraWork,
  listProposalsForEw,
  listSpawnedTickets,
  retrySpawnTicketsForExtraWork,
  transitionExtraWork,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type {
  Contact,
  ExtraWorkCategory,
  ExtraWorkRequestDetail,
  ExtraWorkStatus,
  ExtraWorkUnitType,
  ExtraWorkUrgency,
  Proposal,
  ProposalDetail,
  Role,
  ServiceUnitType,
  TicketList,
  TicketStatus,
} from "../api/types";
import { ConfirmDialog, type ConfirmDialogHandle } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import {
  InvoiceLineRow,
  InvoiceLineTotalsRow,
} from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { NoteEditorDialog } from "../components/NoteEditorDialog";
import { PageHeader } from "../components/PageHeader";
import { ProposalBuilder } from "../components/ProposalBuilder";
import { RejectReasonDialog } from "../components/RejectReasonDialog";
import { RouteBadge } from "../components/RouteBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { formatDate, formatDateTime, formatMoney } from "../lib/intl";

// Sprint 29 Batch 29.8 — terminal ticket statuses. A spawned ticket in
// any of these is considered "done" for the cancel-warning gate; only
// non-terminal spawned tickets trigger the dialog warning panel.
const TERMINAL_TICKET_STATUSES: ReadonlySet<TicketStatus> = new Set<TicketStatus>([
  "APPROVED",
  "CLOSED",
  "REJECTED",
]);


const STATUS_I18N_KEY: Record<ExtraWorkStatus, string> = {
  REQUESTED: "status.requested",
  UNDER_REVIEW: "status.under_review",
  PRICING_PROPOSED: "status.pricing_proposed",
  CUSTOMER_APPROVED: "status.customer_approved",
  // Sprint 29 Batch 29.8 — operational segment status labels.
  IN_PROGRESS: "status.in_progress",
  COMPLETED: "status.completed",
  CUSTOMER_REJECTED: "status.customer_rejected",
  CANCELLED: "status.cancelled",
};

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

// Sprint 26C ExtraWorkUnitType and Sprint 28 B5 ServiceUnitType
// share the same storage values; one i18n map covers both.
const UNIT_TYPE_I18N_KEY: Record<ExtraWorkUnitType | ServiceUnitType, string> = {
  HOURS: "unit_type.hours",
  SQUARE_METERS: "unit_type.square_meters",
  FIXED: "unit_type.fixed",
  ITEM: "unit_type.item",
  OTHER: "unit_type.other",
};

const UNIT_TYPE_VALUES: ExtraWorkUnitType[] = [
  "HOURS",
  "SQUARE_METERS",
  "FIXED",
  "ITEM",
  "OTHER",
];

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

// Sprint 5 (frontend) — DISPLAY-ONLY live line totals for the pricing
// composer. Mirrors the backend per-line computation
// (backend/extra_work/models.py::ExtraWorkPricingLineItem.save +
// _two_places): round the subtotal to 2dp FIRST, then derive VAT from
// the ROUNDED subtotal, then the total — and use the SAME rounding MODE
// the backend uses (Decimal.quantize's default = ROUND_HALF_EVEN /
// banker's rounding), so the preview equals the value the line shows
// once added, including on exact half-cent ties (e.g. 0.125 -> 0.12,
// 0.135 -> 0.14). Empty / non-numeric inputs collapse to 0, never NaN.
// Display goes through the same `formatMoney` formatter the table uses.
function round2(n: number): number {
  // Round to 2 decimals with ROUND_HALF_EVEN to match Decimal.quantize.
  // No +EPSILON nudge: that biased exact ties upward (e.g. 2.525 -> 2.53
  // where the backend yields 2.52). All inputs here are >= 0 (the
  // backend's MinValueValidator(0)), so a floor-based split is safe.
  // Operates on IEEE-754 floats, so it is not byte-identical to Decimal
  // in pathological float-representation cases, but matches for every
  // realistic money value; the backend stays authoritative on add. The
  // small tolerance absorbs binary-float error around the .5 boundary.
  const scaled = n * 100;
  const floor = Math.floor(scaled);
  const frac = scaled - floor;
  let cents: number;
  if (Math.abs(frac - 0.5) < 1e-9) {
    // Exact half — round to the even neighbour (banker's rounding).
    cents = floor % 2 === 0 ? floor : floor + 1;
  } else {
    cents = Math.round(scaled);
  }
  return cents / 100;
}

interface LineTotals {
  subtotal: number;
  vat: number;
  total: number;
}

function computeLineTotals(
  quantity: string,
  unitPrice: string,
  vatRate: string,
): LineTotals {
  const q = Number(quantity);
  const u = Number(unitPrice);
  const v = Number(vatRate);
  const qty = Number.isFinite(q) ? q : 0;
  const unit = Number.isFinite(u) ? u : 0;
  const vatPct = Number.isFinite(v) ? v : 0;
  const subtotal = round2(qty * unit);
  const vat = round2((subtotal * vatPct) / 100);
  const total = round2(subtotal + vat);
  return { subtotal, vat, total };
}


export function ExtraWorkDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();
  const { t } = useTranslation(["extra_work", "common"]);
  const { push: pushToast } = useToast();

  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Sprint 28 Batch 4 — read-only Customer Contacts panel. Backend
  // `IsSuperAdminOrCompanyAdminForCompany` gate on the contacts list
  // rejects everyone else with 403; mirror the gate here so
  // BUILDING_MANAGER / CUSTOMER_USER never emit the call.
  const canSeeCustomerContacts =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";
  const [customerContacts, setCustomerContacts] = useState<Contact[]>([]);

  // Pricing-line-item form (provider only).
  const [pricingForm, setPricingForm] = useState({
    description: "",
    unit_type: "FIXED" as ExtraWorkUnitType,
    quantity: "1.00",
    unit_price: "0.00",
    vat_rate: "21.00",
    customer_visible_note: "",
    internal_cost_note: "",
  });
  const [pricingBusy, setPricingBusy] = useState(false);
  const [pricingError, setPricingError] = useState("");
  // Sprint 5 (frontend) — which composer note is being edited in the
  // modal (the two free-text notes moved out of the inline row to make
  // space for the live SUBTOTAL / VAT / TOTAL columns). null = closed.
  const [noteModal, setNoteModal] = useState<"customer" | "internal" | null>(
    null,
  );

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
  const ewId = ew?.id ?? null;
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

  // When a DRAFT proposal exists, fetch its detail so we have
  // `actions.can_direct_publish` for the direct-publish button. The
  // list serializer omits `actions`; the detail endpoint is the only
  // wire shape that carries it. Silently collapses to `null` on 403/
  // not-found (e.g. customer-side caller cannot see DRAFT proposals).
  const draftProposal = proposals.find((p) => p.status === "DRAFT") ?? null;
  const draftProposalId = draftProposal?.id ?? null;
  // Sprint 31 — one open proposal at a time (DRAFT or SENT). When none
  // is open the provider sees the "Prepare proposal" CTA instead.
  const hasOpenProposal = proposals.some(
    (p) => p.status === "DRAFT" || p.status === "SENT",
  );
  useEffect(() => {
    let cancelled = false;
    if (ewId === null || draftProposalId === null) {
      queueMicrotask(() => {
        if (!cancelled) setDraftProposalDetail(null);
      });
      return () => {
        cancelled = true;
      };
    }
    getProposalDetail(ewId, draftProposalId)
      .then((detail) => {
        if (!cancelled) setDraftProposalDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setDraftProposalDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [ewId, draftProposalId]);

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
  const canApproveAsCustomer = !isProvider && ewActions?.can_approve === true;
  const canRejectAsCustomer = !isProvider && ewActions?.can_reject === true;
  const providerOverrideAvailable =
    ewActions?.can_override_customer_decision === true;
  // Sprint 31 — AUTO_START "Start work": a provider can start a
  // PRICING_PROPOSED request that the customer pre-authorized
  // (request_intent == AUTO_START_AFTER_PRICING) without approval or an
  // override reason. When present, it REPLACES the override-approve
  // button (approving an auto-start request is not an override); the
  // override-reject button stays (rejection is always reasoned).
  const canAutoStart = isProvider && ewActions?.can_auto_start === true;
  // Pricing visibility + PDF read are now action-driven so a customer
  // without approve rights doesn't see pricing rows AND a BM with the
  // prep key revoked STILL sees pricing + PDF (backend invariant).
  // Absent `actions` (older response) falls back to the prior
  // is-provider check so the page doesn't go blank.
  const canViewEwPricing = ewActions
    ? ewActions.can_view_pricing
    : isProvider;
  const canViewProposalPdf = ewActions
    ? ewActions.can_view_proposal_pdf
    : isProvider;
  // Proposal-preparation entry points (line-item add/edit/remove
  // form) — BM with prep revoked must lose these. Absent `actions`
  // falls back to is-provider (pre-cherry-pick behavior).
  const canPrepareProposal = ewActions
    ? ewActions.can_prepare_extra_work_proposal
    : isProvider;

  // Sprint 5 (frontend) — live, display-only line totals for the
  // composer row, recomputed each render from the numeric inputs and
  // mirroring the backend's per-line rounding (see computeLineTotals).
  const liveTotals = computeLineTotals(
    pricingForm.quantity,
    pricingForm.unit_price,
    pricingForm.vat_rate,
  );

  // Provider workflow buttons exclude the override targets — those
  // route through the dedicated override block below.
  const providerWorkflowTargets = allowed.filter(
    (s) => s !== "CUSTOMER_APPROVED" && s !== "CUSTOMER_REJECTED",
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
    // AUTO_START: finishing the review just confirms the price (the
    // customer already authorized the start) — it is not a proposal.
    if (
      isAutoStart &&
      ew.status === "UNDER_REVIEW" &&
      target === "PRICING_PROPOSED"
    ) {
      return t("detail.action_confirm_pricing");
    }
    const key = PROVIDER_ACTION_I18N[`${ew.status}->${target}`];
    return key
      ? t(key)
      : t("detail.workflow_move_to", { label: t(STATUS_I18N_KEY[target]) });
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
      const draft = list.find((p) => p.status === "DRAFT");
      if (draft) {
        const detail = await getProposalDetail(ewId, draft.id);
        setDraftProposalDetail(detail);
      } else {
        setDraftProposalDetail(null);
      }
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
      await createProposal(ewId);
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

  async function handleAddPricingItem(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    if (!pricingForm.description.trim()) {
      setPricingError(t("detail.pricing_error_description_required"));
      return;
    }
    setPricingError("");
    setPricingBusy(true);
    try {
      await createExtraWorkPricingItem(id, {
        description: pricingForm.description.trim(),
        unit_type: pricingForm.unit_type,
        quantity: pricingForm.quantity,
        unit_price: pricingForm.unit_price,
        vat_rate: pricingForm.vat_rate,
        customer_visible_note: pricingForm.customer_visible_note,
        internal_cost_note: pricingForm.internal_cost_note,
      });
      setPricingForm({
        description: "",
        unit_type: "FIXED",
        quantity: "1.00",
        unit_price: "0.00",
        vat_rate: "21.00",
        customer_visible_note: "",
        internal_cost_note: "",
      });
      await refresh();
    } catch (err) {
      setPricingError(getApiError(err));
    } finally {
      setPricingBusy(false);
    }
  }

  async function handleDeletePricingItem(itemId: number) {
    if (!id) return;
    setPricingError("");
    try {
      await deleteExtraWorkPricingItem(id, itemId);
      await refresh();
    } catch (err) {
      setPricingError(getApiError(err));
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

  return (
    <div data-testid="extra-work-detail-page">
      <PageHeader
        backLink={{ to: "/extra-work", label: t("back_to_extra_work") }}
        title={ew.title}
        meta={
          <div className="ew-detail-header-meta">
            <StatusBadge status={{ kind: "extra-work", value: ew.status }} />
            <RouteBadge value={ew.routing_decision} />
            <span className="muted small">
              {t(CATEGORY_I18N_KEY[ew.category] ?? ew.category)}
              {ew.category === "OTHER" && ew.category_other_text
                ? ` — ${ew.category_other_text}`
                : ""}
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
              <div className="form-2col">
                <div>
                  <div className="muted small">{t("detail.field_building")}</div>
                  <div>{ew.building_name}</div>
                </div>
                <div>
                  <div className="muted small">{t("detail.field_customer")}</div>
                  <div>{ew.customer_name}</div>
                </div>
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
                  <div>
                    {ew.preferred_date
                      ? formatDate(ew.preferred_date)
                      : t("detail.empty_dash")}
                  </div>
                </div>
              </div>
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
                    className="btn btn-secondary btn-sm"
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
                      className="btn btn-secondary btn-sm"
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
                            className={
                              target === "CUSTOMER_APPROVED"
                                ? "btn btn-primary btn-sm"
                                : "btn btn-secondary btn-sm"
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
                                          label: t(STATUS_I18N_KEY[target]),
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
            </div>
          </div>
          </div>{/* end .ew-detail-top-row */}

          {/* Sprint 28 Batch 4 — read-only Customer Contacts panel.
              Renders only for SUPER_ADMIN / COMPANY_ADMIN (mirrors the
              backend gate; other roles never see this card). Pure
              informational — full management lives on
              /admin/customers/:id/contacts. */}
          {canSeeCustomerContacts && (
            <div
              className="card"
              data-testid="extra-work-customer-contacts-panel"
              style={{ marginBottom: 16 }}
            >
              <div className="form-section">
                <div className="form-section-title">
                  {t("customer_contacts.panel_title", { ns: "common" })}
                </div>
                {customerContacts.length === 0 ? (
                  <div
                    className="muted small"
                    data-testid="extra-work-customer-contacts-empty"
                  >
                    {t("customer_contacts.panel_empty", { ns: "common" })}
                  </div>
                ) : (
                  <ul
                    style={{
                      listStyle: "none",
                      margin: 0,
                      padding: 0,
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    {customerContacts.map((contact) => (
                      <li
                        key={contact.id}
                        data-testid="extra-work-customer-contact-row"
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: 2,
                        }}
                      >
                        <span style={{ fontWeight: 600 }}>
                          {contact.full_name}
                        </span>
                        {contact.role_label && (
                          <span className="muted small">
                            {contact.role_label}
                          </span>
                        )}
                        {(contact.email || contact.phone) && (
                          <span
                            className="muted small"
                            style={{
                              display: "flex",
                              gap: 12,
                              flexWrap: "wrap",
                            }}
                          >
                            {contact.email && <span>{contact.email}</span>}
                            {contact.phone && <span>{contact.phone}</span>}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {/* ----- Cart line items (Sprint 28 Batch 6) ----- */}
          <div
            className="card"
            style={{ marginBottom: 16 }}
            data-testid="extra-work-detail-line-items"
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
              )}
            </div>
          </div>

          {/* ----- Pricing line items ----- */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="form-section">
              <div className="form-section-title">
                {t("detail.pricing_section_title")}
              </div>
              {canViewEwPricing && ew.pricing_line_items.length === 0 && (
                <div className="muted small">{t("detail.pricing_empty")}</div>
              )}
              {canViewEwPricing && ew.pricing_line_items.length > 0 && (
                <table className="data-table ew-pricing-table">
                  <thead>
                    <tr>
                      {INVOICE_LINE_COLUMN_KEYS.map((key) => (
                        <th key={key}>{t(key)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ew.pricing_line_items.map((item) => {
                      const showInternalNote =
                        isProvider && !!item.internal_cost_note;
                      const showCustomerNote = !!item.customer_visible_note;
                      return (
                        <InvoiceLineRow
                          key={item.id}
                          lineKind="pricing"
                          line={item}
                          editable={canPrepareProposal}
                          onRemove={() => handleDeletePricingItem(item.id)}
                          subLabel={
                            showCustomerNote || showInternalNote ? (
                              <>
                                {showCustomerNote && (
                                  <span className="muted small">
                                    {item.customer_visible_note}
                                  </span>
                                )}
                                {showInternalNote && (
                                  <span
                                    className="muted small"
                                    style={{ fontStyle: "italic" }}
                                  >
                                    internal: {item.internal_cost_note}
                                  </span>
                                )}
                              </>
                            ) : undefined
                          }
                        />
                      );
                    })}
                    <InvoiceLineTotalsRow
                      subtotal={ew.subtotal_amount}
                      vatAmount={ew.vat_amount}
                      total={ew.total_amount}
                    />
                  </tbody>
                </table>
              )}

              {canPrepareProposal && (
                <>
                  {pricingError && (
                    <div
                      className="alert-error"
                      style={{ marginTop: 12 }}
                      role="alert"
                    >
                      {pricingError}
                    </div>
                  )}
                  <form
                    onSubmit={handleAddPricingItem}
                    className="ew-pricing-add-form"
                    style={{ marginTop: 12 }}
                  >
                    {/* Single invoice-style row: Description | Unit |
                        Quantity | Unit price | VAT % | Customer note |
                        Internal note | [Add button]. Description and
                        the two free-text notes grow; the four
                        numeric/unit fields stay narrow. The existing
                        .ew-line-row helper wraps each field to its own
                        100%-wide row on <=760px (mobile). Every binding
                        + the submit payload are byte-identical to the
                        previous three-tier layout — only arrangement
                        changes. */}
                    <div className="ew-line-row">
                      <div className="field ew-line-field-grow">
                        <label
                          className="field-label"
                          htmlFor="pricing-description"
                        >
                          {t("detail.pricing_form_description")}
                        </label>
                        <input
                          id="pricing-description"
                          className="field-input"
                          type="text"
                          value={pricingForm.description}
                          onChange={(event) =>
                            setPricingForm((c) => ({
                              ...c,
                              description: event.target.value,
                            }))
                          }
                          placeholder={t(
                            "detail.pricing_form_description_placeholder",
                          )}
                          required
                        />
                      </div>
                      <div className="field ew-line-field-medium">
                        <label
                          className="field-label"
                          htmlFor="pricing-unit-type"
                        >
                          {t("detail.pricing_form_unit")}
                        </label>
                        <select
                          id="pricing-unit-type"
                          className="field-select"
                          value={pricingForm.unit_type}
                          onChange={(event) =>
                            setPricingForm((c) => ({
                              ...c,
                              unit_type: event.target
                                .value as ExtraWorkUnitType,
                            }))
                          }
                        >
                          {UNIT_TYPE_VALUES.map((value) => (
                            <option key={value} value={value}>
                              {t(UNIT_TYPE_I18N_KEY[value])}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field ew-line-field-compact">
                        <label className="field-label" htmlFor="pricing-qty">
                          {t("detail.pricing_form_quantity")}
                        </label>
                        <input
                          id="pricing-qty"
                          className="field-input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={pricingForm.quantity}
                          onChange={(event) =>
                            setPricingForm((c) => ({
                              ...c,
                              quantity: event.target.value,
                            }))
                          }
                          required
                        />
                      </div>
                      <div className="field ew-line-field-compact">
                        <label
                          className="field-label"
                          htmlFor="pricing-unit-price"
                        >
                          {t("detail.pricing_form_unit_price")}
                        </label>
                        <input
                          id="pricing-unit-price"
                          className="field-input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={pricingForm.unit_price}
                          onChange={(event) =>
                            setPricingForm((c) => ({
                              ...c,
                              unit_price: event.target.value,
                            }))
                          }
                          required
                        />
                      </div>
                      <div className="field ew-line-field-compact">
                        <label className="field-label" htmlFor="pricing-vat">
                          {t("detail.pricing_form_vat")}
                        </label>
                        <input
                          id="pricing-vat"
                          className="field-input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={pricingForm.vat_rate}
                          onChange={(event) =>
                            setPricingForm((c) => ({
                              ...c,
                              vat_rate: event.target.value,
                            }))
                          }
                          required
                        />
                      </div>
                      {/* Live, display-only line totals — replace the two
                          inline note inputs (now behind modal buttons),
                          freeing the row width. Mirrors the backend's
                          per-line rounding so the preview equals the line
                          once added. Aligned to the table's
                          SUBTOTAL / VAT / TOTAL money columns. */}
                      <div className="field ew-line-field-money">
                        <span className="field-label">
                          {t("invoice_row.col_subtotal")}
                        </span>
                        <div
                          className="field-input"
                          data-testid="pricing-live-subtotal"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "flex-end",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {formatMoney(liveTotals.subtotal)}
                        </div>
                      </div>
                      <div className="field ew-line-field-money">
                        <span className="field-label">
                          {t("invoice_row.col_vat")}
                        </span>
                        <div
                          className="field-input"
                          data-testid="pricing-live-vat"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "flex-end",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {formatMoney(liveTotals.vat)}
                        </div>
                      </div>
                      <div className="field ew-line-field-money">
                        <span className="field-label">
                          {t("invoice_row.col_total")}
                        </span>
                        <div
                          className="field-input"
                          data-testid="pricing-live-total"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "flex-end",
                            fontWeight: 600,
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {formatMoney(liveTotals.total)}
                        </div>
                      </div>

                      {/* The two free-text notes live behind buttons
                          styled as field boxes (same 38px height as the
                          inputs, so they align in the row). Values stay
                          in pricingForm and are sent unchanged on add.
                          The internal-cost-note box is provider-only,
                          mirroring the table's
                          `isProvider && item.internal_cost_note` gating. */}
                      <div className="field ew-line-field-note">
                        <span className="field-label">
                          {t("detail.pricing_customer_note_button")}
                        </span>
                        <button
                          type="button"
                          className="field-input ew-pricing-note-box"
                          data-testid="pricing-customer-note-button"
                          data-filled={
                            pricingForm.customer_visible_note.trim()
                              ? "true"
                              : "false"
                          }
                          title={pricingForm.customer_visible_note || undefined}
                          onClick={() => setNoteModal("customer")}
                        >
                          {pricingForm.customer_visible_note.trim() ? (
                            <>
                              <Check size={13} strokeWidth={2.5} aria-hidden />
                              <span className="ew-pricing-note-box-text">
                                {pricingForm.customer_visible_note}
                              </span>
                            </>
                          ) : (
                            <span className="muted">
                              {t("detail.empty_dash")}
                            </span>
                          )}
                        </button>
                      </div>
                      {isProvider && (
                        <div className="field ew-line-field-note">
                          <span className="field-label">
                            {t("detail.pricing_internal_note_button")}
                          </span>
                          <button
                            type="button"
                            className="field-input ew-pricing-note-box"
                            data-testid="pricing-internal-note-button"
                            data-filled={
                              pricingForm.internal_cost_note.trim()
                                ? "true"
                                : "false"
                            }
                            title={pricingForm.internal_cost_note || undefined}
                            onClick={() => setNoteModal("internal")}
                          >
                            {pricingForm.internal_cost_note.trim() ? (
                              <>
                                <Check size={13} strokeWidth={2.5} aria-hidden />
                                <span className="ew-pricing-note-box-text">
                                  {pricingForm.internal_cost_note}
                                </span>
                              </>
                            ) : (
                              <span className="muted">
                                {t("detail.empty_dash")}
                              </span>
                            )}
                          </button>
                        </div>
                      )}
                      <div className="ew-line-row-actions">
                        <button
                          type="submit"
                          className="btn btn-primary btn-sm"
                          disabled={pricingBusy}
                        >
                          {pricingBusy
                            ? t("detail.pricing_form_submitting")
                            : t("detail.pricing_form_submit")}
                        </button>
                      </div>
                    </div>
                  </form>
                </>
              )}
            </div>
          </div>

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
                ewId={ewId}
                proposal={draftProposalDetail}
                onChanged={reloadProposals}
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

      {/* Sprint 5 (frontend) — composer note editors. Mounted only while
          open so each open re-seeds from the current pricingForm value.
          Save writes back to pricingForm (sent unchanged on add); the
          internal-note editor is additionally provider-gated. */}
      {noteModal === "customer" && (
        <NoteEditorDialog
          testId="pricing-customer-note-modal"
          title={t("detail.pricing_customer_note_modal_title")}
          initialValue={pricingForm.customer_visible_note}
          placeholder={t("detail.pricing_form_customer_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            setPricingForm((c) => ({ ...c, customer_visible_note: value }));
            setNoteModal(null);
          }}
          onCancel={() => setNoteModal(null)}
        />
      )}
      {noteModal === "internal" && isProvider && (
        <NoteEditorDialog
          testId="pricing-internal-note-modal"
          title={t("detail.pricing_internal_note_modal_title")}
          initialValue={pricingForm.internal_cost_note}
          placeholder={t("detail.pricing_form_internal_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            setPricingForm((c) => ({ ...c, internal_cost_note: value }));
            setNoteModal(null);
          }}
          onCancel={() => setNoteModal(null)}
        />
      )}

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
                      #{ticket.id} — {ticket.title} ({ticket.status})
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





