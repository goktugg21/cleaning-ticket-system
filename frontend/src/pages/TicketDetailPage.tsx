import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRightLeft,
  ChevronLeft,
  Clock,
  MapPin,
  MessageSquare,
  Paperclip,
  TriangleAlert,
  UploadCloud,
  UserPlus,
  Users,
} from "lucide-react";
import axios from "axios";
import { Trans, useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import {
  cancelStaffAssignmentRequest,
  createStaffAssignmentRequest,
  getStaffCompletionRoute,
  listCustomerContacts,
  listStaffAssignmentRequests,
} from "../api/admin";
import { getMessageRecipients } from "../api/notifications";
import { StaffSlotEditor } from "./tickets/StaffSlotEditor";
import { SubTaskReadOnly } from "./tickets/SubTaskReadOnly";
import { ResponsibleManagersSection } from "./tickets/ResponsibleManagersSection";
import { TicketScheduleCard } from "./tickets/TicketScheduleCard";
import type {
  AssignableManager,
  Contact,
  MessageRecipient,
  PaginatedResponse,
  StaffCompletionRoute,
  TicketAttachment,
  TicketDetail,
  TicketMessage,
  TicketMessageType,
  TicketStatus,
  TicketStatusChangePayload,
  TicketTimelineRow,
} from "../api/types";
import { getTicketAuditTimeline } from "../api/ticketTimeline";
import { useAuth } from "../auth/AuthContext";
import {
  composerTiersForRole,
  isProviderAdmin,
  isProviderManagementRole,
  isStaff as isStaffRoleFn,
} from "../auth/permissions";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { ConvertToExtraWorkDialog } from "../components/ConvertToExtraWorkDialog";
import { RouteBadge } from "../components/RouteBadge";
import { UnifiedTimeline } from "../components/UnifiedTimeline";
import { SLABadge } from "../components/sla/SLABadge";
import { useFormatSLATime } from "../utils/useFormatSLATime";
import { useSLALabel } from "../utils/useSLALabel";

// B7 four-tier note taxonomy — per-tier UI vocabulary. The bubble class
// flags "private to provider" tiers ("internal") so existing CSS keeps
// applying the muted treatment; STAFF_COMPLETION is customer-visible so
// it gets no muted class. The tag class flags PUBLIC_REPLY as the
// customer-side conversation tier; the other three render with the
// default tag styling.
const NOTE_TIER_BADGE_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "tag_public",
  INTERNAL_NOTE: "tag_internal",
  STAFF_OPERATIONAL: "tag_staff_operational",
  STAFF_COMPLETION: "tag_staff_completion",
};

const NOTE_TIER_BUBBLE_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "",
  INTERNAL_NOTE: "internal",
  STAFF_OPERATIONAL: "internal",
  STAFF_COMPLETION: "",
};

const NOTE_TIER_TAG_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "public",
  INTERNAL_NOTE: "",
  STAFF_OPERATIONAL: "",
  STAFF_COMPLETION: "",
};

const NOTE_TIER_COMPOSER_LABEL_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public",
  INTERNAL_NOTE: "composer_internal",
  STAFF_OPERATIONAL: "composer_staff_operational",
  STAFF_COMPLETION: "composer_staff_completion",
};

const NOTE_TIER_PLACEHOLDER_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public_placeholder",
  INTERNAL_NOTE: "composer_internal_placeholder",
  STAFF_OPERATIONAL: "composer_staff_operational_placeholder",
  STAFF_COMPLETION: "composer_staff_completion_placeholder",
};

// "Who sees this" description rendered under the composer-tier
// toggle. The map covers all four tiers so the helper line renders
// even when the viewer only has one tier available (the toggle row
// itself hides in that case, but the visibility statement still
// shows so an author never posts without knowing the audience).
const NOTE_TIER_WHO_SEES_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public_who_sees",
  INTERNAL_NOTE: "composer_internal_who_sees",
  STAFF_OPERATIONAL: "composer_staff_operational_who_sees",
  STAFF_COMPLETION: "composer_staff_completion_who_sees",
};

const NOTE_TIER_TONE_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "",
  INTERNAL_NOTE: "internal",
  STAFF_OPERATIONAL: "internal",
  STAFF_COMPLETION: "",
};

// Sprint 15: backend is the source of truth for which transitions are
// available. Previously the frontend carried a SUPER_ADMIN_UI_NEXT_STATUS
// table that hard-coded a SUPER_ADMIN's next-step buttons; that table
// could drift from `state_machine.ALLOWED_TRANSITIONS` and bypass the
// pair-aware customer-user / building-manager scope checks. The viewset
// now returns a per-role `allowed_next_statuses` for every role
// (SUPER_ADMIN included via the special-case branch in
// `state_machine.allowed_next_statuses`), so the page renders that list
// directly.
function getVisibleWorkflowStatuses(ticket: TicketDetail): TicketStatus[] {
  return ticket.allowed_next_statuses;
}

function isAdminCustomerDecisionOverride(
  currentStatus: TicketStatus,
  nextStatus: TicketStatus,
  role?: string,
): boolean {
  return (
    (role === "SUPER_ADMIN" || role === "COMPANY_ADMIN") &&
    currentStatus === "WAITING_CUSTOMER_APPROVAL" &&
    (nextStatus === "APPROVED" || nextStatus === "REJECTED")
  );
}

// Sprint 30 Batch 30.1.1.5 — progressive disclosure of workflow
// transitions. SUPER_ADMIN sees up to 7 transitions on certain
// statuses; cramming them all as primary buttons buries the obvious
// forward action. PRIMARY_TRANSITIONS encodes the 1–2 "obvious next
// step(s)" per current status; everything else in
// `allowed_next_statuses` becomes secondary and lives behind a
// "More actions" toggle. The partition does NOT change which
// transitions are legal — 30.1.1's `visibleNextStatuses` gate still
// runs first; this only changes how the legal set is laid out.
const PRIMARY_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  OPEN: ["IN_PROGRESS"],
  IN_PROGRESS: ["WAITING_MANAGER_REVIEW", "CLOSED"],
  WAITING_MANAGER_REVIEW: ["APPROVED", "REJECTED"],
  WAITING_CUSTOMER_APPROVAL: ["APPROVED", "REJECTED"],
  APPROVED: ["CLOSED"],
  REJECTED: ["IN_PROGRESS"],
  CLOSED: [],
  REOPENED_BY_ADMIN: ["IN_PROGRESS"],
  // Terminal — no further status moves once converted to Extra Work.
  CONVERTED_TO_EXTRA_WORK: [],
};

function partitionTransitions(
  currentStatus: TicketStatus,
  allowed: TicketStatus[],
): { primary: TicketStatus[]; secondary: TicketStatus[] } {
  // Sprint 30 Batch 30.1.3 — preserve PRIMARY_TRANSITIONS *order* so
  // Approve renders above Reject on every customer-decision step,
  // regardless of how the backend orders `allowed_next_statuses`.
  // (SUPER_ADMIN gets statuses in TicketStatus.choices order which
  // puts REJECTED before APPROVED; reading from PRIMARY_TRANSITIONS
  // overrides that.)
  const primaryOrder = PRIMARY_TRANSITIONS[currentStatus] ?? [];
  const allowedSet = new Set(allowed);
  const primary = primaryOrder.filter((s) => allowedSet.has(s));
  const primarySet = new Set(primary);
  const secondary = allowed.filter((s) => !primarySet.has(s));
  return { primary, secondary };
}

// Sprint 7B (frontend) — statuses from which a ticket may be converted
// to a new Extra Work request. Mirrors the backend convertibility gate
// in `tickets/views.py::convert_to_extra_work` (OPEN / IN_PROGRESS /
// REOPENED_BY_ADMIN; CONVERTED_TO_EXTRA_WORK and every terminal status
// are rejected). The convert flow is a DEDICATED endpoint, never a raw
// status transition.
const CONVERTIBLE_TICKET_STATUSES: ReadonlySet<TicketStatus> = new Set<
  TicketStatus
>(["OPEN", "IN_PROGRESS", "REOPENED_BY_ADMIN"]);

const ACCEPTED_ATTACHMENT_TYPES =
  ".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf";
const MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024;

function formatDate(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function getInitials(value: string | null | undefined): string {
  if (!value) return "—";
  const localPart = value.split("@")[0] || value;
  const parts = localPart
    .replace(/[._-]+/g, " ")
    .split(" ")
    .filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return localPart.slice(0, 2).toUpperCase();
}

function humanName(email: string | null | undefined, fallback: string): string {
  if (!email) return fallback;
  const local = email.split("@")[0];
  return local
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getFileExtension(filename: string): string {
  const parts = filename.split(".");
  if (parts.length < 2) return "FILE";
  return (parts.pop() || "FILE").slice(0, 4).toUpperCase();
}

// Sprint 22 final polish: status-history notes set by the seed
// (`seed_demo_data → IN_PROGRESS`) and any other transition note
// that contains a raw enum value or an internal marker string are
// not meant to be shown to demo users. We strip them at render
// time so the timeline reads cleanly. Operator-typed notes are
// preserved verbatim.
function sanitizeStatusNote(raw: string | null | undefined): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (!trimmed) return "";
  // Drop notes that start with `seed_demo_data` (or contain the
  // legacy seed prefix anywhere). This matches the exact string
  // the canonical seed writes via apply_transition(..., note=…).
  if (/^seed_demo_data\b/i.test(trimmed)) return "";
  if (/seed_demo_data\s*→/i.test(trimmed)) return "";
  return trimmed;
}


export function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const { t } = useTranslation(["ticket_detail", "common"]);
  const slaLabel = useSLALabel();
  const formatSLATime = useFormatSLATime();

  const tStatus = (status: TicketStatus | string | null): string => {
    if (!status) return t("status_default_created");
    return t(`common:status.${status.toLowerCase()}`);
  };

  const priorityLabelLong = (priority: string): string => {
    switch (priority) {
      case "URGENT":
        return t("priority_long_urgent");
      case "HIGH":
        return t("priority_long_high");
      default:
        return t("priority_long_normal");
    }
  };

  // Sprint 27F-F1 — the inline "click again to confirm" banner copy is
  // retained for cases where the override modal copy needs a short
  // form (still wired via i18n). The two-press confirmation now lives
  // in a modal — see `overrideDecision` state below.
  const overrideModalSubmitLabel = (nextStatus: TicketStatus): string => {
    if (nextStatus === "APPROVED")
      return t("override_modal_submit_approve");
    if (nextStatus === "REJECTED")
      return t("override_modal_submit_reject");
    return t("override_modal_submit_approve");
  };

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);
  // Sprint 32 — unified audit timeline for provider-audit roles (SA / CA /
  // BM). STAFF + CUSTOMER_USER never fetch it (the endpoint 403s them); they
  // keep the status-history-only activity card. `null` while loading or on
  // error -> the page falls back to the status-history rendering so the
  // activity card is never blank.
  // Tagged with the ticket id the rows were fetched for, so a navigation
  // A -> B (TicketDetailPage does NOT unmount) never renders A's audit feed
  // under B during B's fetch — the render gate requires the tag to match the
  // CURRENT ticket id.
  const [auditTimeline, setAuditTimeline] = useState<{
    ticketId: number;
    rows: TicketTimelineRow[];
  } | null>(null);
  // Bumped on every ticket reload that follows an audited mutation (message,
  // attachment, assignment, status/override, completion). Drives a timeline
  // refetch so non-status audit rows appear without a full page reload, in
  // addition to the status-history-length trigger. Only bumped from
  // user-initiated reloads, so it never over-fetches.
  const [auditReloadNonce, setAuditReloadNonce] = useState(0);

  // Sprint 23B — Request-assignment state for STAFF users on a
  // ticket they have building visibility for but aren't yet
  // assigned to.
  //
  // Sprint 24C — instead of a one-way "submitted" flag, we now
  // track the actual PENDING request id so the staff user can
  // cancel it via the new modal. On ticket-detail mount we list
  // the staff user's requests and find one matching this ticket;
  // after a successful POST we set the id from the response; on
  // cancellation we clear it back to null so the "Request
  // assignment" button reappears (Sprint 23A's duplicate guard
  // only fires on still-PENDING rows).
  const [requestAssignmentBusy, setRequestAssignmentBusy] =
    useState(false);
  const [pendingRequestId, setPendingRequestId] =
    useState<number | null>(null);
  const [requestAssignmentError, setRequestAssignmentError] =
    useState("");
  const [requestAssignmentBanner, setRequestAssignmentBanner] =
    useState("");
  const [cancelRequestBusy, setCancelRequestBusy] = useState(false);
  const cancelRequestDialogRef = useRef<ConfirmDialogHandle>(null);

  const [loading, setLoading] = useState(true);
  const [statusNote, setStatusNote] = useState("");
  const [statusBusy, setStatusBusy] = useState<TicketStatus | null>(null);
  // Sprint 30 Batch 30.1.1.5 — progressive workflow disclosure. The
  // secondary transition list starts collapsed; the "More actions"
  // toggle expands it. When the current status has no primary
  // transitions (CLOSED), the secondary list renders inline-open
  // and the toggle is hidden — see `shouldDefaultOpen` below.
  const [secondaryOpen, setSecondaryOpen] = useState(false);
  // Sprint 27F-F1 — ticket-override modal state. Mirrors the
  // ExtraWorkDetailPage shape:
  //   overrideDecision  the target status the operator picked
  //                     (null = modal closed).
  //   overrideReason    bound to the mandatory textarea.
  //   overrideError     i18n string when the reason is empty or
  //                     when the backend returns
  //                     `code: "override_reason_required"`.
  //   overrideBusy      gates the submit button while the request
  //                     is in flight.
  const [overrideDecision, setOverrideDecision] =
    useState<TicketStatus | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [overrideBusy, setOverrideBusy] = useState(false);

  // Sprint 28 Batch 11 — STAFF "Complete work" modal state.
  // The modal opens when an assigned STAFF user clicks the Complete
  // Work button on an IN_PROGRESS ticket. The destination of the
  // resulting transition (WAITING_MANAGER_REVIEW vs
  // WAITING_CUSTOMER_APPROVAL) is resolved server-side via
  // GET /api/tickets/<id>/staff-completion-route/ on modal open. We
  // refetch the route if the backend ever returns the stable code
  // `staff_completion_route_mismatch` on submit, which means the
  // BSV flag changed between open and submit.
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [completeNote, setCompleteNote] = useState("");
  const [completeRoute, setCompleteRoute] =
    useState<StaffCompletionRoute | null>(null);
  const [completeRouteLoading, setCompleteRouteLoading] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);
  const [completeBusy, setCompleteBusy] = useState(false);

  const [message, setMessage] = useState("");
  // Composer tier list — driven by per-record `ticket.actions` when the
  // detail has loaded (PUBLIC_REPLY is always allowed for an
  // authenticated viewer in scope, plus whichever of INTERNAL_NOTE /
  // STAFF_OPERATIONAL / STAFF_COMPLETION the backend says this user
  // can author on THIS ticket). Falls back to the role-based predicate
  // before the detail loads (or for older serializers that don't carry
  // `actions`), so the page never crashes on undefined.
  const composerTiers = useMemo<TicketMessageType[]>(() => {
    const actions = ticket?.actions;
    if (actions) {
      const tiers: TicketMessageType[] = ["PUBLIC_REPLY"];
      if (actions.can_post_provider_internal_note) tiers.push("INTERNAL_NOTE");
      if (actions.can_post_staff_operational_note) tiers.push("STAFF_OPERATIONAL");
      if (actions.can_post_staff_completion_note) tiers.push("STAFF_COMPLETION");
      return tiers;
    }
    return composerTiersForRole(me?.role);
  }, [ticket?.actions, me?.role]);
  const [messageType, setMessageType] = useState<TicketMessageType>("PUBLIC_REPLY");
  // Render-time fallback: if `messageType` is no longer in the action-
  // driven tier list (e.g. role just loaded and dropped INTERNAL_NOTE),
  // fall back to the first allowed tier. Render-time derivation avoids
  // a setState-in-effect.
  const effectiveMessageType: TicketMessageType = composerTiers.includes(
    messageType,
  )
    ? messageType
    : composerTiers[0] ?? "PUBLIC_REPLY";
  const [sendingMessage, setSendingMessage] = useState(false);

  // M1 B3 — directed_to ("notify specific people") + RESTRICTED ("private")
  // compose state. The valid recipient set depends on the active tier, so we
  // refetch it whenever the effective tier changes and prune any now-invalid
  // selection. `effectivePrivate` mirrors the B1 restricted_requires_target
  // rule (RESTRICTED requires >=1 target) so the UI never sends a black-hole
  // message.
  const [directedTo, setDirectedTo] = useState<number[]>([]);
  const [isPrivate, setIsPrivate] = useState(false);
  const [recipients, setRecipients] = useState<MessageRecipient[]>([]);
  const effectivePrivate = isPrivate && directedTo.length > 0;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const loadRecipients = async () => {
      try {
        const data = await getMessageRecipients(id, effectiveMessageType);
        if (cancelled) return;
        setRecipients(data);
        // Drop any selected target that is not valid for the new tier
        // (e.g. switching PUBLIC_REPLY -> INTERNAL_NOTE removes customers).
        const validIds = new Set(data.map((recipient) => recipient.id));
        setDirectedTo((prev) => prev.filter((rid) => validIds.has(rid)));
      } catch {
        // A failed refetch must not strand a now-invalid, invisible
        // selection (the chip picker hides when recipients is empty). Clear
        // the selection + private intent so the next send can't carry a
        // target the user can no longer see/deselect.
        if (!cancelled) {
          setRecipients([]);
          setDirectedTo([]);
          setIsPrivate(false);
        }
      }
    };
    loadRecipients();
    return () => {
      cancelled = true;
    };
  }, [id, effectiveMessageType]);

  const toggleDirected = useCallback(
    (recipientId: number) => {
      const next = directedTo.includes(recipientId)
        ? directedTo.filter((rid) => rid !== recipientId)
        : [...directedTo, recipientId];
      setDirectedTo(next);
      // RESTRICTED is only meaningful with >=1 target; clearing the last
      // target drops the private intent so re-selecting someone later does
      // not silently re-arm "Private".
      if (next.length === 0) {
        setIsPrivate(false);
      }
    },
    [directedTo],
  );

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [attachmentHidden, setAttachmentHidden] = useState(false);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [downloadingAttachmentId, setDownloadingAttachmentId] =
    useState<number | null>(null);

  const [assignableManagers, setAssignableManagers] = useState<
    AssignableManager[]
  >([]);
  const [selectedAssigneeId, setSelectedAssigneeId] = useState<string>("");
  const [assigningTicket, setAssigningTicket] = useState(false);

  // Phase B — the dated staff-slot CRUD (Sprint 25A's flat add/remove
  // superseded) now lives in <StaffSlotEditor>, which owns its own state.

  const [error, setError] = useState("");

  // Sprint 12 — soft-delete state. confirmText is what the operator
  // types into the dialog input; the confirm button only activates
  // when it matches the ticket number, preventing single-click
  // accidents. busy gates the network round-trip.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deletingTicket, setDeletingTicket] = useState(false);

  // Sprint 7B (frontend) — Convert-to-Extra-Work dialog open state.
  // Converting a ticket is a dedicated endpoint that creates a new
  // ExtraWorkRequest; it is NOT the raw status transition to
  // CONVERTED_TO_EXTRA_WORK (which would flip the status without ever
  // creating the request). The button is gated below on
  // `canConvertTicket`.
  const [convertOpen, setConvertOpen] = useState(false);

  // Provider-management trio (SA + CA + BM). Drives note-author UI,
  // assignable-manager dropdown, etc. — the surface that may see+author
  // PROVIDER_INTERNAL notes (B7) and direct ticket assignment.
  const isStaff = isProviderManagementRole(me?.role);

  // "Provider acting on a customer-decision step." Drive ENTIRELY off
  // the per-record action `ticket.actions.can_override_customer_decision`
  // (backend tightens it to True only when the viewer holds override
  // authority AND the ticket is at WAITING_CUSTOMER_APPROVAL AND
  // APPROVED/REJECTED is in `allowed_next_statuses`). Replaces the
  // earlier `isProviderAdmin(me.role) && status==WCA` composition,
  // which wrongly hid the override path from a BM with the B6 override
  // key. Treat absent `actions` as False so the page hides the override
  // arming UI until the detail loads.
  const providerActsAsOverride =
    ticket?.actions?.can_override_customer_decision === true;

  // Sprint 30 Batch 30.1.3 — STAFF completion-evidence gate (frontend
  // mirror of the backend `completion_evidence_required` rule). For
  // STAFF on the IN_PROGRESS → completion transition we require a
  // note OR at least one image attachment before enabling the
  // transition button. The backend already returns 400 with this
  // stable code; the UX gate here only blocks the obvious empty case.
  // Note: backend STAFF rule for IN_PROGRESS → WAITING_CUSTOMER_APPROVAL
  // already enforces note OR attachment; we keep this client check
  // narrow to the STAFF role + completion targets so we never block
  // a provider's faster optional-note flow.
  const hasImageAttachment = useMemo(
    () => attachments.some((a) => a.mime_type?.startsWith("image/")),
    [attachments],
  );
  const staffCompletionEvidenceRequired =
    isStaffRoleFn(me?.role) &&
    !!ticket &&
    ticket.status === "IN_PROGRESS";

  // Sprint 28 Batch 4 — read-only Customer Contacts panel.
  // Backend `IsSuperAdminOrCompanyAdminForCompany` gate on the
  // contacts list endpoint rejects everyone else with 403; we mirror
  // that gate here so BUILDING_MANAGER / STAFF / CUSTOMER_USER never
  // emit the call (silent fail; the panel just doesn't render).
  const canSeeCustomerContacts = isProviderAdmin(me?.role);
  const [customerContacts, setCustomerContacts] = useState<Contact[]>([]);

  // Sprint 30 Batch 30.1.2 — multi-tenant fix for the Assigned field
  // staff heading. The TicketDetail payload now exposes `company_name`
  // directly via `source="company.name"` on the backend serializer
  // (Sprint 30 Batch 30.1.2 Phase B), so we render it inline without
  // an extra round-trip. A null value (legacy / hard-deleted provider
  // row) falls back to the unknown-tenant heading.

  // Sprint 12 — mirrors the backend `_user_can_soft_delete_ticket`
  // rule so the button only renders when the API will actually accept
  // the call. Backend stays the source of truth for security; this
  // is purely a UX gate.
  const canDeleteTicket =
    !!ticket &&
    !!me &&
    (me.role === "SUPER_ADMIN" ||
      me.role === "COMPANY_ADMIN" ||
      ticket.created_by === me.id);

  // Sprint 7B (frontend) — mirrors the backend convert gate in
  // `tickets/views.py::convert_to_extra_work`: provider-management role
  // (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) AND a convertible
  // status. Backend stays the source of truth (scope + role + status);
  // this is purely a UX gate so the prominent button only renders when
  // the action will actually be accepted.
  //
  // Codex P2 (PR #72) — also hide the action for an EW-origin ticket
  // (itself spawned from an Extra Work request): converting it would
  // nest a second EW and break the one-operational-ticket-per-EW model.
  // The backend rejects this with 400 `ticket_already_extra_work_origin`
  // (the authority, §11.4); this `!extra_work_origin` check is the UI
  // mirror so the button never even appears.
  const canConvertTicket =
    !!ticket &&
    isProviderManagementRole(me?.role) &&
    CONVERTIBLE_TICKET_STATUSES.has(ticket.status) &&
    !ticket.extra_work_origin;

  const loadTicket = useCallback(async () => {
    if (!id) return;
    try {
      const [ticketResponse, messageResponse, attachmentResponse] =
        await Promise.all([
          api.get<TicketDetail>(`/tickets/${id}/`),
          api.get<PaginatedResponse<TicketMessage>>(
            `/tickets/${id}/messages/`,
          ),
          api.get<PaginatedResponse<TicketAttachment>>(
            `/tickets/${id}/attachments/`,
          ),
        ]);
      setTicket(ticketResponse.data);
      setMessages(messageResponse.data.results);
      setAttachments(attachmentResponse.data.results);
      // Signal the audit-timeline effect to refetch (batched with the
      // setters above, so the effect runs once per reload). This is what
      // surfaces message / attachment audit rows — they do not change the
      // status-history length.
      setAuditReloadNonce((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    loadTicket();
  }, [loadTicket]);

  // Sprint 32 — provider-audit roles (SA / CA / BM, mirroring the backend
  // IsTicketAuditConsumer) get the UNIFIED audit timeline. STAFF /
  // CUSTOMER_USER are deliberately excluded: they must never call the
  // provider-audit endpoint (it 403s them) nor see audit_log / EW-internal /
  // severity rows. Refetches when the status-history length changes (a
  // status / override transition — covers the direct-setTicket status path)
  // OR when `auditReloadNonce` bumps (every other audited reload: message /
  // attachment / assignment). State is only set inside the async callbacks
  // (never synchronously in the effect body, so no set-state-in-effect), the
  // rows are tagged with the fetched ticket id, and a failed fetch leaves
  // `auditTimeline` null, so the activity card falls back to the
  // status-history rendering rather than blanking.
  const isProviderAudit = isProviderManagementRole(me?.role);
  const auditTimelineTicketId = ticket?.id ?? null;
  const auditTimelineHistoryLen = ticket?.status_history?.length ?? 0;
  useEffect(() => {
    if (!isProviderAudit || auditTimelineTicketId == null) return;
    let cancelled = false;
    getTicketAuditTimeline(auditTimelineTicketId)
      .then((data) => {
        if (!cancelled)
          setAuditTimeline({
            ticketId: auditTimelineTicketId,
            rows: data.timeline,
          });
      })
      .catch(() => {
        if (!cancelled) setAuditTimeline(null);
      });
    return () => {
      cancelled = true;
    };
  }, [
    isProviderAudit,
    auditTimelineTicketId,
    auditTimelineHistoryLen,
    auditReloadNonce,
  ]);

  useEffect(() => {
    setSelectedAssigneeId(
      ticket && ticket.assigned_to !== null
        ? String(ticket.assigned_to)
        : "",
    );
  }, [ticket?.id, ticket?.assigned_to]);

  // Sprint 27F-F1 — clear any pending override modal state when the
  // ticket loads or its status changes (so a successful transition
  // does not leave a stale reason in the textarea).
  useEffect(() => {
    setOverrideDecision(null);
    setOverrideReason("");
    setOverrideError(null);
  }, [ticket?.id, ticket?.status]);

  // Sprint 28 Batch 4 — fetch the customer's contacts when an admin
  // viewer opens a ticket attached to a customer. The panel is purely
  // informational (full_name / role_label / phone / email) and never
  // edits anything. Backend gate is SUPER_ADMIN / COMPANY_ADMIN only
  // (see customers/views_contacts.py); we mirror the gate above with
  // `canSeeCustomerContacts` so the call never even fires for other
  // roles. Failures are swallowed silently — the panel collapses to
  // empty state rather than disrupting the ticket flow.
  const ticketCustomerId = ticket?.customer ?? null;
  useEffect(() => {
    const cancelled = { current: false };
    const customerId =
      canSeeCustomerContacts && ticketCustomerId ? ticketCustomerId : null;
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
  }, [canSeeCustomerContacts, ticketCustomerId]);

  useEffect(() => {
    if (!isStaff || !id) return;
    let cancelled = false;
    api
      .get<AssignableManager[]>(`/tickets/${id}/assignable-managers/`)
      .then((response) => {
        if (!cancelled) setAssignableManagers(response.data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id, isStaff]);


  // Sprint 24C — discover the staff user's own PENDING request for
  // this ticket so the UI can show a Cancel button instead of the
  // submit-once banner. The backend's STAFF queryset is narrowed to
  // `staff=request.user`, so this list call is bounded to the
  // viewer's own requests.
  //
  // Sprint 24D — the viewset now declares `filterset_fields =
  // ["status", "ticket", "staff"]`, so we can ask for exactly the
  // single row we care about (`?ticket=<id>&status=PENDING`). The
  // backend's duplicate guard allows one PENDING per (staff, ticket),
  // so this returns 0 or 1 row regardless of pagination — fixing the
  // pre-24D bug where a staff user with >25 lifetime requests could
  // miss their own PENDING row if it fell off the first page.
  useEffect(() => {
    if (me?.role !== "STAFF" || !id) return;
    let cancelled = false;
    const numericId = Number(id);
    listStaffAssignmentRequests({
      ticket: numericId,
      status: "PENDING",
    })
      .then((response) => {
        if (cancelled) return;
        const match = response.results.find(
          (r) => r.ticket === numericId && r.status === "PENDING",
        );
        setPendingRequestId(match ? match.id : null);
      })
      .catch(() => {
        if (!cancelled) setPendingRequestId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id, me?.role]);

  const visibleNextStatuses = useMemo(
    () => (ticket ? getVisibleWorkflowStatuses(ticket) : []),
    [ticket],
  );

  // Sprint 30 Batch 30.1.1.5 — partition the already-legal transition
  // set into "obvious next step" primaries vs "edge-case" secondaries.
  // The partition is purely about visibility; both groups dispatch
  // through the same `changeStatus` (and through the Sprint 27F
  // override modal where applicable).
  const { primary: primaryNextStatuses, secondary: secondaryNextStatuses } =
    useMemo(
      () =>
        ticket
          ? partitionTransitions(ticket.status, visibleNextStatuses)
          : { primary: [] as TicketStatus[], secondary: [] as TicketStatus[] },
      [ticket, visibleNextStatuses],
    );
  // CLOSED has no primaries; render the disclosure inline-open by
  // default so the only available action (REOPENED_BY_ADMIN) is one
  // click away, without an extra toggle.
  const shouldDefaultOpenSecondary =
    primaryNextStatuses.length === 0 && secondaryNextStatuses.length > 0;
  const isSecondaryOpen = secondaryOpen || shouldDefaultOpenSecondary;

  // Sprint 28 Batch 11 — the "Complete work" button only renders for
  // a STAFF user who is actually on the ticket's assignment set and
  // is looking at an IN_PROGRESS ticket. Backend enforces the same
  // gate on the transition; this is purely UX.
  const canShowCompleteWorkButton =
    !!ticket &&
    me?.role === "STAFF" &&
    ticket.status === "IN_PROGRESS" &&
    ticket.is_assigned_staff === true;

  async function submitAssignment(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    setError("");
    setAssigningTicket(true);
    try {
      const assignedTo =
        selectedAssigneeId === "" ? null : Number(selectedAssigneeId);
      const response = await api.post<TicketDetail>(
        `/tickets/${id}/assign/`,
        { assigned_to: assignedTo },
      );
      setTicket(response.data);
      // Assignment changes emit an audit_log row but do NOT change the
      // status-history length, so nudge the timeline to refetch.
      setAuditReloadNonce((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setAssigningTicket(false);
    }
  }

  function openDeleteDialog() {
    setDeleteConfirmText("");
    setError("");
    deleteDialogRef.current?.open();
  }

  async function confirmDeleteTicket() {
    if (!id || !ticket) return;
    setDeletingTicket(true);
    try {
      await api.delete(`/tickets/${id}/`);
      deleteDialogRef.current?.close();
      // Sprint 12: navigate back to dashboard so the soft-deleted
      // ticket disappears from view immediately. The ticket list will
      // refetch on mount and the row will not appear.
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        t("delete_ticket_failed", { detail: getApiError(err) }),
      );
      deleteDialogRef.current?.close();
    } finally {
      setDeletingTicket(false);
    }
  }

  async function changeStatus(toStatus: TicketStatus) {
    if (!id || !ticket) return;

    setError("");

    // Sprint 27F-F1 — provider-driven customer-decision overrides now
    // route through the dedicated override modal. The button click
    // opens the modal (setting `overrideDecision`); the actual API
    // call fires from `submitOverride` below, which posts
    // `is_override + override_reason` per the 27F-B1 contract. The
    // existing isAdminCustomerDecisionOverride gate still governs
    // *who sees* the buttons — it has not moved.
    const needsAdminDecisionOverride = isAdminCustomerDecisionOverride(
      ticket.status,
      toStatus,
      me?.role,
    );

    if (needsAdminDecisionOverride) {
      setOverrideDecision(toStatus);
      setOverrideReason("");
      setOverrideError(null);
      return;
    }

    if (
      me?.role === "CUSTOMER_USER" &&
      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
      toStatus === "REJECTED" &&
      !statusNote.trim()
    ) {
      setError(t("workflow_customer_rejection_required"));
      return;
    }

    setStatusBusy(toStatus);

    try {
      const payload: TicketStatusChangePayload = {
        to_status: toStatus,
        note: statusNote.trim(),
      };
      const response = await api.post<TicketDetail>(
        `/tickets/${id}/status/`,
        payload,
      );

      setTicket(response.data);
      setStatusNote("");
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setStatusBusy(null);
    }
  }

  // Sprint 27F-F1 — mirrors ExtraWorkDetailPage.handleOverrideSubmit.
  // Submits {to_status, is_override:true, override_reason} and
  // refetches the ticket on success so the timeline picks up the new
  // status_history row carrying is_override + override_reason. On the
  // 400 `code: "override_reason_required"` response we surface the
  // i18n string (we match the stable `code` field, never the message).
  async function submitOverride(event: FormEvent) {
    event.preventDefault();
    if (!id || !overrideDecision) return;
    if (!overrideReason.trim()) {
      setOverrideError(t("override_modal_reason_required"));
      return;
    }
    setOverrideError(null);
    setOverrideBusy(true);
    try {
      const payload: TicketStatusChangePayload = {
        to_status: overrideDecision,
        is_override: true,
        override_reason: overrideReason.trim(),
        note: statusNote.trim(),
      };
      await api.post<TicketDetail>(`/tickets/${id}/status/`, payload);
      // Refetch via loadTicket so messages / attachments stay in sync
      // alongside the new status_history row.
      await loadTicket();
      setStatusNote("");
      setOverrideDecision(null);
      setOverrideReason("");
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const data = err.response?.data as
          | { code?: string; detail?: string }
          | undefined;
        if (data?.code === "override_reason_required") {
          setOverrideError(t("override_modal_reason_required"));
          return;
        }
      }
      setOverrideError(getApiError(err));
    } finally {
      setOverrideBusy(false);
    }
  }

  function cancelOverride() {
    setOverrideDecision(null);
    setOverrideReason("");
    setOverrideError(null);
  }

  // Sprint 28 Batch 11 — open the STAFF completion modal and
  // synchronously fetch the routing destination so the submit button
  // label and the explanation line match what the backend will do.
  async function openCompleteModal() {
    if (!id) return;
    setCompleteNote("");
    setCompleteError(null);
    setCompleteRoute(null);
    setCompleteModalOpen(true);
    setCompleteRouteLoading(true);
    try {
      const data = await getStaffCompletionRoute(Number(id));
      setCompleteRoute(data.route);
    } catch (err) {
      setCompleteError(getApiError(err));
    } finally {
      setCompleteRouteLoading(false);
    }
  }

  function closeCompleteModal() {
    setCompleteModalOpen(false);
    setCompleteNote("");
    setCompleteRoute(null);
    setCompleteError(null);
  }

  // Sprint 28 Batch 11 — submit the STAFF completion transition.
  // Maps the route -> target status, posts the status change with
  // the operator note as completion evidence, and handles the two
  // backend stable error codes:
  //   - `completion_evidence_required` — backend says the note (and
  //     visible attachments) are insufficient. Surface i18n string.
  //   - `staff_completion_route_mismatch` — BSV flag flipped between
  //     open and submit; refetch the route and surface i18n string.
  async function submitCompleteWork(event: FormEvent) {
    event.preventDefault();
    if (!id || !ticket) return;
    // Sprint 30 Batch 30.1.3 — accept either a typed note OR a
    // visible image attachment. The backend
    // `completion_evidence_required` rule for STAFF on IN_PROGRESS →
    // completion routes uses the same OR semantics; this matches.
    if (!completeNote.trim() && !hasImageAttachment) {
      setCompleteError(t("common:ticket_staff_complete.error_evidence_required"));
      return;
    }
    if (!completeRoute) {
      // Should not happen — the modal disables the submit until the
      // route resolves. Bail defensively rather than silently posting
      // a status the backend may not accept.
      return;
    }
    setCompleteError(null);
    setCompleteBusy(true);
    try {
      const toStatus: TicketStatus =
        completeRoute === "customer_approval"
          ? "WAITING_CUSTOMER_APPROVAL"
          : "WAITING_MANAGER_REVIEW";
      const payload: TicketStatusChangePayload = {
        to_status: toStatus,
        note: completeNote.trim(),
      };
      await api.post<TicketDetail>(`/tickets/${id}/status/`, payload);
      await loadTicket();
      closeCompleteModal();
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const data = err.response?.data as
          | { code?: string; detail?: string }
          | undefined;
        if (data?.code === "completion_evidence_required") {
          setCompleteError(
            t("common:ticket_staff_complete.error_evidence_required"),
          );
          return;
        }
        if (data?.code === "staff_completion_route_mismatch") {
          // Refetch the route so the next submit has the correct
          // target. Show the i18n explanation; submit stays gated
          // on the new route.
          setCompleteError(
            t("common:ticket_staff_complete.error_route_mismatch"),
          );
          try {
            const refreshed = await getStaffCompletionRoute(Number(id));
            setCompleteRoute(refreshed.route);
          } catch {
            // If even the refetch fails, leave the previous route in
            // place — the user can cancel + retry.
          }
          return;
        }
      }
      setCompleteError(getApiError(err));
    } finally {
      setCompleteBusy(false);
    }
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    if (!id || !message.trim()) return;
    setError("");
    setSendingMessage(true);
    try {
      // Send the effective (render-time-derived) tier so a stale
      // `messageType` set from a previous role context can never escape
      // onto the wire. The composer toggle only surfaces tiers the role
      // can write, but this kept honest at the network boundary too.
      await api.post(`/tickets/${id}/messages/`, {
        message: message.trim(),
        message_type: effectiveMessageType,
        // M1 B3 — attention targets + visibility. effectivePrivate guards
        // the B1 restricted_requires_target rule client-side (RESTRICTED is
        // only sent with >=1 target). The picker only offers valid targets,
        // so directed_to_not_visible / too_many_directed_recipients cannot
        // be reached from the UI; getApiError surfaces them if they ever do.
        directed_to: directedTo,
        visibility_mode: effectivePrivate ? "RESTRICTED" : "NORMAL",
      });
      setMessage("");
      setMessageType(composerTiers[0] ?? "PUBLIC_REPLY");
      setDirectedTo([]);
      setIsPrivate(false);
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSendingMessage(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file && file.size > MAX_ATTACHMENT_SIZE_BYTES) {
      setSelectedFile(null);
      setError(t("attachment_too_large"));
      event.target.value = "";
      return;
    }
    setError("");
    setSelectedFile(file);
  }

  async function downloadAttachment(item: TicketAttachment) {
    if (!id) return;
    setError("");
    setDownloadingAttachmentId(item.id);
    try {
      const response = await api.get(
        `/tickets/${id}/attachments/${item.id}/download/`,
        { responseType: "blob" },
      );
      const blobUrl = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = item.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  async function submitAttachment(event: FormEvent) {
    event.preventDefault();
    if (!id || !selectedFile) return;

    if (selectedFile.size > MAX_ATTACHMENT_SIZE_BYTES) {
      setError(t("attachment_too_large"));
      return;
    }

    setError("");
    setUploadingAttachment(true);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      if (isStaff) {
        formData.append("is_hidden", attachmentHidden ? "true" : "false");
      }
      await api.post(`/tickets/${id}/attachments/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setSelectedFile(null);
      setAttachmentHidden(false);
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setUploadingAttachment(false);
    }
  }

  if (loading && !ticket) {
    return (
      <div>
        <Link to="/" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {t("back_to_tickets")}
        </Link>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
        {error && <div className="alert-error">{error}</div>}
      </div>
    );
  }

  if (!ticket) {
    return (
      <div>
        <Link to="/" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {t("back_to_tickets")}
        </Link>
        <div className="alert-error">{error || t("ticket_not_found")}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="detail-header">
        <div className="detail-header-top">
          <Link to="/" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_tickets")}
          </Link>
          {/* Sprint 30 Batch 30.1.1 — the header-level "Delete accidental
              ticket" button has been demoted to a small text link in the
              Details card footer (see the consolidated Details card
              below). The confirmation dialog and the delete behaviour
              are unchanged; only the entry-point affordance moved.

              Sprint 7B (frontend) — prominent "Convert to Extra Work"
              header action. Opens the dedicated convert dialog (which
              POSTs to /tickets/<id>/convert-to-extra-work/ and creates
              a NEW ExtraWorkRequest); it is NOT the raw status hop to
              CONVERTED_TO_EXTRA_WORK. Gated on `canConvertTicket`
              (provider-management role + convertible status), mirroring
              the backend gate. */}
          {canConvertTicket && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setConvertOpen(true)}
              data-testid="ticket-convert-to-ew-button"
            >
              <ArrowRightLeft size={14} strokeWidth={2.2} />
              <span style={{ marginLeft: 6 }}>
                {t("workflow_convert_to_extra_work")}
              </span>
            </button>
          )}
        </div>
        <div className="detail-header-meta">
          <span className="detail-header-no">{ticket.ticket_no}</span>
          <span className={`badge badge-${ticket.priority.toLowerCase()}`}>
            {priorityLabelLong(ticket.priority)}
          </span>
          <span className={`badge badge-${ticket.status.toLowerCase()}`}>
            {tStatus(ticket.status)}
          </span>
        </div>
        <h1 className="detail-header-title">{ticket.title}</h1>
        <p className="detail-header-desc">{ticket.description}</p>
        {/* Sprint 28 Batch 15.4 — spawned-from-EW anchor. Renders only
            when the backend includes `extra_work_origin` (non-null
            for tickets created by an ExtraWorkRequest line). Mirrors
            the RouteBadge so operators can tell at a glance whether
            the parent EW skipped or went through the proposal phase. */}
        {ticket.extra_work_origin && (
          <div
            className="ticket-extra-work-origin"
            data-testid="ticket-extra-work-origin"
            data-origin={ticket.extra_work_origin.origin}
          >
            <span className="muted small">
              {t("detail.spawned_from_label")}
            </span>{" "}
            <Link
              to={`/extra-work/${ticket.extra_work_origin.extra_work_request_id}`}
            >
              {ticket.extra_work_origin.extra_work_request_title}
            </Link>{" "}
            <RouteBadge value={ticket.extra_work_origin.origin} />
          </div>
        )}
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="detail-grid">
        <div className="detail-main">
          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <Clock size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_activity_title")}
              </span>
            </div>
            <div className="timeline">
              {/* Sprint 32 — provider-audit roles see the UNIFIED timeline
                  (status history + audit_log + Extra Work + planned
                  occurrence + severity). STAFF / CUSTOMER_USER (and any
                  load / fetch-error state, where auditTimeline stays null)
                  fall through to the unchanged status-history rendering
                  below, so the activity card is never blank and their view
                  is exactly as before. */}
              {isProviderAudit &&
              auditTimeline !== null &&
              auditTimeline.ticketId === ticket.id &&
              auditTimeline.rows.length > 0 ? (
                <UnifiedTimeline rows={auditTimeline.rows} />
              ) : ticket.status_history.length === 0 ? (
                <div className="timeline-row" data-color="green">
                  <div className="timeline-dot" />
                  <div>
                    <div className="timeline-time">
                      {formatDate(ticket.created_at)}
                    </div>
                    <div className="timeline-text">
                      <Trans
                        i18nKey="ticket_detail:timeline_created"
                        values={{
                          name: humanName(
                            ticket.created_by_email,
                            t("unassigned"),
                          ),
                        }}
                        components={{ b: <b /> }}
                      />
                    </div>
                  </div>
                </div>
              ) : (
                ticket.status_history.map((entry, index) => (
                  <div
                    key={entry.id}
                    className="timeline-row"
                    data-color={
                      index === 0
                        ? "green"
                        : entry.new_status === "REJECTED"
                          ? "red"
                          : entry.new_status === "WAITING_CUSTOMER_APPROVAL"
                            ? "amber"
                            : "muted"
                    }
                  >
                    <div className="timeline-dot" />
                    <div>
                      <div className="timeline-time">
                        {formatDate(entry.created_at)}
                      </div>
                      <div className="timeline-text">
                        <b>
                          {humanName(
                            entry.changed_by_email,
                            t("unassigned"),
                          )}
                        </b>
                        {entry.old_status ? (
                          <>
                            {t("timeline_status_changed_from_to")}
                            <span
                              className={`pill ${entry.old_status === "OPEN" ? "open" : "progress"}`}
                            >
                              {tStatus(entry.old_status)}
                            </span>
                            {t("timeline_status_to")}
                            <span className="pill progress">
                              {tStatus(entry.new_status)}
                            </span>
                          </>
                        ) : (
                          <>
                            {t("timeline_created_as")}
                            <span className="pill progress">
                              {tStatus(entry.new_status)}
                            </span>
                          </>
                        )}
                        {(() => {
                          const cleaned = sanitizeStatusNote(entry.note);
                          return cleaned ? `. ${cleaned}` : ".";
                        })()}
                      </div>
                      {/* Sprint 27F-F1 — override badge + reason sub-
                          line. Backend always emits both fields
                          (defaulted false / ""); we only render the
                          badge for actual overrides. */}
                      {entry.is_override &&
                        (() => {
                          // Sanitize the override reason the same way
                          // UnifiedTimeline does, so the demo seed marker
                          // never leaks in the status-history fallback
                          // path (a real typed reason is unaffected).
                          const cleanedReason = sanitizeStatusNote(
                            entry.override_reason,
                          );
                          return (
                            <div
                              className="muted small"
                              data-testid="timeline-override-badge"
                              style={{ marginTop: 4 }}
                            >
                              <b>{t("timeline_override_badge")}</b>
                              {cleanedReason
                                ? ` · ${t("timeline_override_reason", {
                                    reason: cleanedReason,
                                  })}`
                                : ""}
                            </div>
                          );
                        })()}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <MessageSquare size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_messages_title")}
              </span>
            </div>
            <form className="notes-composer-body" onSubmit={submitMessage}>
              <textarea
                className="notes-textarea"
                placeholder={t(NOTE_TIER_PLACEHOLDER_KEY[effectiveMessageType])}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                required
              />
              {recipients.length > 0 && (
                <div className="composer-directed" data-testid="composer-directed">
                  <div className="composer-directed-label">
                    {t("directed.label")}
                  </div>
                  <div className="composer-directed-chips">
                    {recipients.map((recipient) => {
                      const selected = directedTo.includes(recipient.id);
                      return (
                        <button
                          key={recipient.id}
                          type="button"
                          className={`directed-chip${
                            selected ? " directed-chip-selected" : ""
                          }`}
                          aria-pressed={selected}
                          onClick={() => toggleDirected(recipient.id)}
                        >
                          {recipient.full_name}
                          <span className="directed-chip-side">
                            {t(`directed.side_${recipient.side}`)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <label className="composer-private-toggle">
                    <input
                      type="checkbox"
                      checked={effectivePrivate}
                      disabled={directedTo.length === 0}
                      onChange={(event) => setIsPrivate(event.target.checked)}
                      data-testid="composer-private-toggle"
                    />
                    <span>{t("directed.private_label")}</span>
                  </label>
                  <p className="muted small composer-directed-hint">
                    {directedTo.length === 0
                      ? t("directed.private_disabled_hint")
                      : effectivePrivate
                        ? t("directed.private_on_hint")
                        : t("directed.private_off_hint")}
                  </p>
                </div>
              )}
              <div className="notes-actions">
                <div className="notes-tools">
                  {composerTiers.length > 1 && (
                    <div className="composer-toggle" role="tablist">
                      {composerTiers.map((tier) => (
                        <button
                          key={tier}
                          type="button"
                          role="tab"
                          aria-selected={effectiveMessageType === tier}
                          className={`composer-toggle-btn ${
                            effectiveMessageType === tier
                              ? `active ${NOTE_TIER_TONE_CLASS[tier]}`
                              : ""
                          }`}
                          onClick={() => setMessageType(tier)}
                        >
                          {t(NOTE_TIER_COMPOSER_LABEL_KEY[tier])}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  disabled={sendingMessage || !message.trim()}
                >
                  {sendingMessage ? t("sending") : t("post_message")}
                </button>
              </div>
              {/* "Who sees this" helper, keyed to the active tier so
                  the author knows the visibility scope before posting.
                  Renders for every tier (even when only one is
                  available) so the author cannot post a note without
                  the visibility statement on screen. */}
              <p
                className="muted small composer-tier-help"
                data-testid="composer-tier-help"
                style={{ margin: "6px 22px 0", padding: "0 0 14px" }}
              >
                {t(NOTE_TIER_WHO_SEES_KEY[effectiveMessageType])}
              </p>
            </form>

            {messages.length === 0 ? (
              <p
                style={{
                  padding: "0 22px 22px",
                  color: "var(--text-faint)",
                  fontSize: 13,
                }}
              >
                {t("no_messages")}
              </p>
            ) : (
              messages.map((item) => (
                <div
                  key={item.id}
                  className={`note-bubble ${NOTE_TIER_BUBBLE_CLASS[item.message_type] ?? ""}`}
                >
                  <div className="note-bubble-avatar">
                    {getInitials(item.author_email)}
                  </div>
                  <div>
                    <div className="note-bubble-head">
                      <span className="note-bubble-name">
                        {humanName(item.author_email, t("unassigned"))}
                      </span>
                      <span className="note-bubble-time">
                        {formatDate(item.created_at)}
                      </span>
                      <span
                        className={`note-bubble-tag ${NOTE_TIER_TAG_CLASS[item.message_type] ?? ""}`}
                      >
                        {t(NOTE_TIER_BADGE_KEY[item.message_type] ?? "tag_public")}
                      </span>
                      {item.visibility_mode === "RESTRICTED" && (
                        <span
                          className="note-bubble-private"
                          data-testid="note-private"
                        >
                          {t("directed.private_badge")}
                        </span>
                      )}
                    </div>
                    {item.directed_to_detail &&
                      item.directed_to_detail.length > 0 && (
                        <div
                          className="note-bubble-directed"
                          data-testid="note-directed"
                        >
                          {t("directed.bubble_prefix")}{" "}
                          {item.directed_to_detail
                            .map((target) => target.full_name)
                            .join(", ")}
                        </div>
                      )}
                    <div className="note-bubble-text">{item.message}</div>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <Paperclip size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_attachments_title")}
              </span>
              <span className="card-head-icon-spacer" />
              <span className="card-head-icon-link">
                {t(
                  attachments.length === 1 ? "files_singular" : "files_plural",
                  { count: attachments.length },
                )}
              </span>
            </div>

            <div className="att-thumb-grid">
              {attachments.map((item) => (
                <div className="att-thumb" key={item.id}>
                  <button
                    type="button"
                    className={`att-thumb-tile ${item.is_hidden ? "internal" : ""}`}
                    onClick={() => downloadAttachment(item)}
                    disabled={downloadingAttachmentId === item.id}
                    aria-label={`Download ${item.original_filename}`}
                  >
                    <span className="att-thumb-ext">
                      {getFileExtension(item.original_filename)}
                    </span>
                    {item.is_hidden && (
                      <span className="att-thumb-internal-pill">
                        {t("internal_pill")}
                      </span>
                    )}
                  </button>
                  <div className="att-thumb-name">
                    {downloadingAttachmentId === item.id
                      ? t("downloading")
                      : item.original_filename}
                  </div>
                  <div className="att-thumb-size">
                    {formatBytes(item.file_size)} ·{" "}
                    {formatDate(item.created_at)}
                  </div>
                </div>
              ))}

              <label className="att-thumb-upload">
                <UploadCloud size={22} strokeWidth={2} />
                <span>
                  {selectedFile ? t("replace_selection") : t("upload_file")}
                </span>
                <input
                  type="file"
                  accept={ACCEPTED_ATTACHMENT_TYPES}
                  onChange={handleFileChange}
                  disabled={uploadingAttachment}
                />
              </label>
            </div>

            {selectedFile && (
              <form
                className="att-thumb-staged"
                onSubmit={submitAttachment}
              >
                <span className="att-thumb-staged-text">
                  {t("selected")} <b>{selectedFile.name}</b> ·{" "}
                  {formatBytes(selectedFile.size)}
                </span>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  {ticket?.actions?.can_upload_hidden_attachment && (
                    <label className="login-check" style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={attachmentHidden}
                        onChange={(event) =>
                          setAttachmentHidden(event.target.checked)
                        }
                        disabled={uploadingAttachment}
                      />
                      <span>{t("internal_only")}</span>
                    </label>
                  )}
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={uploadingAttachment}
                  >
                    {uploadingAttachment ? t("uploading") : t("upload_button")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>

        <div className="detail-side">
          {/* Sprint 30 Batch 30.1.1 — consolidated Assignment card.
              ONE outer card with TWO clearly-labeled subsections:
                - Building manager (ticket owner / BM dispatch — writes
                  `ticket.assigned_to` via /tickets/<id>/assign/).
                - Assigned {{companyName}} staff (field-staff dispatch —
                  reads `ticket.assigned_staff` and writes via
                  /tickets/<id>/staff-assignments/).
              They ARE different concepts (BM owner vs Field Staff
              dispatch). The field-staff heading interpolates the
              ticket's providing company name to remove the prior
              hardcoded "OSIUS" multi-tenant bug. */}
          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_assignment_title")}
              </div>
            </div>

            {/* --- Subsection 1: Building manager (owner) --- */}
            <div className="assign-body">
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                  marginBottom: 2,
                }}
              >
                {t("assignment_section_bm_heading")}
              </div>
              <p
                className="muted small"
                style={{ margin: "0 0 8px" }}
                data-testid="assignment-section-bm-helper"
              >
                {t("assignment_section_bm_helper")}
              </p>
              <div className="assignee-row">
                <div className="assignee-avatar">
                  {getInitials(ticket.assigned_to_email || "unassigned@")}
                </div>
                <div className="assignee-info">
                  <span className="assignee-name">
                    {ticket.assigned_to_email
                      ? humanName(ticket.assigned_to_email, t("unassigned"))
                      : t("unassigned")}
                  </span>
                  <span className="assignee-role">
                    {ticket.assigned_to_email
                      ? t("operations_lead")
                      : t("awaiting_assignment")}
                  </span>
                </div>
              </div>

              {isStaff ? (
                <form
                  onSubmit={submitAssignment}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <select
                    className="assign-select"
                    value={selectedAssigneeId}
                    onChange={(event) =>
                      setSelectedAssigneeId(event.target.value)
                    }
                    disabled={assigningTicket}
                  >
                    <option value="">{t("unassigned")}</option>
                    {ticket.assigned_to !== null &&
                      !assignableManagers.some(
                        (m) => m.id === ticket.assigned_to,
                      ) && (
                        <option value={String(ticket.assigned_to)}>
                          {ticket.assigned_to_email ??
                            t("assignment_user_n", {
                              id: ticket.assigned_to,
                            })}
                          {t("assignment_current")}
                        </option>
                      )}
                    {assignableManagers.map((manager) => (
                      <option key={manager.id} value={manager.id}>
                        {manager.full_name?.trim() || manager.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    className="btn btn-secondary"
                    style={{ width: "100%" }}
                    disabled={
                      assigningTicket ||
                      selectedAssigneeId ===
                        (ticket.assigned_to !== null
                          ? String(ticket.assigned_to)
                          : "")
                    }
                  >
                    <UserPlus size={14} strokeWidth={2} />
                    {assigningTicket ? t("updating") : t("update_assignment")}
                  </button>
                </form>
              ) : null}
            </div>

            {/* --- Subsection 2: Field staff (dispatch) --- */}
            {/* Sprint 23B — Assigned-staff list. Backend gates the
                contact-visibility per Customer.show_assigned_staff_*
                flags BEFORE returning to a CUSTOMER_USER; we just
                render what the API gives us. An empty array means
                no staff assigned yet.
                Sprint 30 Batch 30.1.1 — preserved `assigned-staff-card`
                testid on the subsection wrapper (was the outer card in
                the pre-30.1.1 layout). Existing Playwright specs assert
                visibility via this testid. */}
            <div
              data-testid="assigned-staff-card"
              style={{
                marginTop: 14,
                paddingTop: 14,
                borderTop: "1px solid var(--border)",
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                  padding: "0 18px",
                  marginBottom: 6,
                }}
              >
                {ticket.company_name
                  ? t("assignment_section_field_staff_heading", {
                      companyName: ticket.company_name,
                    })
                  : t("assignment_section_field_staff_heading_unknown")}
              </div>
              <div className="assign-body">
              {ticket.assigned_staff.length === 0 ? (
                <p
                  className="muted small"
                  style={{ padding: "4px 0 12px" }}
                  data-testid="assigned-staff-empty"
                >
                  {t("assigned_staff_empty")}
                </p>
              ) : (
                <ul
                  className="assigned-staff-list"
                  style={{
                    listStyle: "none",
                    margin: 0,
                    padding: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                  data-testid="assigned-staff-list"
                >
                  {ticket.assigned_staff.map((entry, index) => {
                    if ("anonymous" in entry && entry.anonymous) {
                      return (
                        <li
                          key={`anon-${index}`}
                          className="assignee-row"
                          data-testid="assigned-staff-anon"
                        >
                          <div className="assignee-avatar">·</div>
                          <div className="assignee-info">
                            <span className="assignee-name">
                              {/* Sprint 30 Batch 30.1.2 — interpolate the
                                  ticket's providing company name into the
                                  anonymous label. The backend emits a fixed
                                  key (`tickets.assigned_team_anonymous`); the
                                  frontend swaps to the `_unknown` variant
                                  when `company_name` is null. */}
                              {ticket.company_name
                                ? t(entry.label_key, {
                                    companyName: ticket.company_name,
                                  })
                                : t(`${entry.label_key}_unknown`)}
                            </span>
                          </div>
                        </li>
                      );
                    }
                    const named = entry as {
                      id: number;
                      full_name?: string;
                      email?: string;
                      phone?: string;
                    };
                    const displayName =
                      named.full_name ||
                      (named.email ? named.email.split("@")[0] : "—");
                    return (
                      <li
                        key={named.id}
                        className="assignee-row"
                        data-testid="assigned-staff-item"
                      >
                        <div className="assignee-avatar">
                          {getInitials(displayName)}
                        </div>
                        <div className="assignee-info">
                          <span className="assignee-name">{displayName}</span>
                          <span
                            className="assignee-role"
                            style={{ fontSize: 11 }}
                          >
                            {t("assigned_staff_role")}
                            {named.email ? ` · ${named.email}` : ""}
                            {named.phone ? ` · ${named.phone}` : ""}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}

              {isStaff && (
                <StaffSlotEditor
                  // Key by ticket id so the editor REMOUNTS on an A->B ticket
                  // change and its useState(autoCompleteOnSubtasks)-seeded
                  // autoFlag re-seeds from the new ticket (fixes a stale
                  // checkbox after navigation). A same-ticket reload keeps the
                  // key, so the local toggle state is correctly preserved.
                  key={ticket.id}
                  ticketId={ticket.id}
                  onChanged={() => {
                    void loadTicket();
                  }}
                  autoCompleteOnSubtasks={ticket.auto_complete_on_subtasks}
                  canSetAutoCompleteFlag={isProviderAdmin(me?.role)}
                  ticketStatus={ticket.status}
                />
              )}

              {/* Sprint 5 — read-only sub-tasks for NON-manager viewers.
                  STAFF (provider-side) see full detail; customer-side
                  viewers get a PII-safe summary (no staff identity/notes).
                  Only renders once a manager has created sub-tasks, so a
                  ticket with none is unchanged for these roles. */}
              {!isStaff && ticket.sub_tasks.length > 0 && (
                <SubTaskReadOnly
                  subTasks={ticket.sub_tasks}
                  autoCompleteOnSubtasks={ticket.auto_complete_on_subtasks}
                  showStaffDetails={me?.role === "STAFF"}
                />
              )}

              {/* Sprint 23B — STAFF-only "Request assignment"
                  button. Visible only when:
                    * the viewer's role is STAFF (CUSTOMER_USER and
                      OSIUS-side managers never see it),
                    * the staff user is NOT already assigned to this
                      ticket, and
                    * the local UI hasn't already POSTed a request
                      this session.
                  The backend separately enforces "active staff
                  profile + visibility for the ticket's building"
                  and 400s a duplicate. The UI flips to a friendly
                  message on duplicate so we don't let the user
                  repeatedly POST. */}
              {me?.role === "STAFF" && (() => {
                const alreadyAssigned = ticket.assigned_staff.some(
                  (entry) =>
                    !("anonymous" in entry && entry.anonymous) &&
                    (entry as { id: number }).id === me.id,
                );
                if (alreadyAssigned) return null;
                async function handleRequest() {
                  if (!ticket) return;
                  setRequestAssignmentBusy(true);
                  setRequestAssignmentError("");
                  setRequestAssignmentBanner("");
                  try {
                    const created = await createStaffAssignmentRequest(
                      ticket.id,
                    );
                    setPendingRequestId(created.id);
                    setRequestAssignmentBanner(
                      t("request_assignment_success"),
                    );
                  } catch (err) {
                    const message = getApiError(err);
                    // Backend returns "A pending request already exists."
                    // on duplicates. The pending-discovery effect should
                    // have set pendingRequestId already; flag the duplicate
                    // for clarity and let the next useEffect run catch up
                    // if it raced.
                    if (/pending request/i.test(message)) {
                      setRequestAssignmentError(
                        t("request_assignment_already_pending"),
                      );
                    } else {
                      setRequestAssignmentError(message);
                    }
                  } finally {
                    setRequestAssignmentBusy(false);
                  }
                }
                async function handleConfirmCancel() {
                  if (!pendingRequestId) return;
                  setCancelRequestBusy(true);
                  setRequestAssignmentError("");
                  try {
                    await cancelStaffAssignmentRequest(pendingRequestId);
                    cancelRequestDialogRef.current?.close();
                    setPendingRequestId(null);
                    setRequestAssignmentBanner(
                      t("request_assignment_cancelled_success"),
                    );
                  } catch (err) {
                    setRequestAssignmentError(getApiError(err));
                    cancelRequestDialogRef.current?.close();
                  } finally {
                    setCancelRequestBusy(false);
                  }
                }
                return (
                  <div
                    style={{
                      marginTop: 12,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                    data-testid="request-assignment-wrap"
                  >
                    {pendingRequestId !== null ? (
                      // Sprint 24C — pending state with cancel option.
                      <div
                        data-testid="request-assignment-pending"
                        style={{ display: "flex", flexDirection: "column", gap: 6 }}
                      >
                        <p
                          className="muted small"
                          style={{ margin: 0, fontWeight: 600 }}
                        >
                          {t("request_assignment_pending_title")}
                        </p>
                        <p className="muted small" style={{ margin: 0 }}>
                          {t("request_assignment_pending_body")}
                        </p>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={cancelRequestBusy}
                          onClick={() => cancelRequestDialogRef.current?.open()}
                          data-testid="cancel-request-assignment-button"
                          style={{ alignSelf: "flex-start" }}
                        >
                          {cancelRequestBusy
                            ? t("request_assignment_cancelling")
                            : t("request_assignment_cancel")}
                        </button>
                      </div>
                    ) : (
                      <>
                        <p className="muted small" style={{ margin: 0 }}>
                          {t("request_assignment_hint")}
                        </p>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={requestAssignmentBusy}
                          onClick={handleRequest}
                          data-testid="request-assignment-button"
                        >
                          {requestAssignmentBusy
                            ? t("requesting_assignment")
                            : t("request_assignment")}
                        </button>
                      </>
                    )}
                    {requestAssignmentBanner && (
                      <p
                        className="muted small"
                        role="status"
                        data-testid="request-assignment-banner"
                        style={{ marginTop: 4 }}
                      >
                        {requestAssignmentBanner}
                      </p>
                    )}
                    {requestAssignmentError && (
                      <div
                        className="alert-error"
                        role="alert"
                        style={{ marginTop: 6 }}
                      >
                        {requestAssignmentError}
                      </div>
                    )}
                    <ConfirmDialog
                      ref={cancelRequestDialogRef}
                      title={t("request_assignment_cancel_dialog_title")}
                      body={t("request_assignment_cancel_dialog_body")}
                      confirmLabel={t("request_assignment_cancel")}
                      busyLabel={t("request_assignment_cancelling")}
                      onConfirm={handleConfirmCancel}
                      busy={cancelRequestBusy}
                      destructive
                    />
                  </div>
                );
              })()}
            </div>
            {/* close Sprint 30 Batch 30.1.1 assigned-staff-card subsection wrapper */}
            </div>
          </div>

          {/* #7 Part B — Responsible managers (M:N), distinct from the
              primary "Assigned" field above. Self-gates to provider-
              management roles and hides on a LIST 403. onChanged reloads
              the ticket so the activity timeline picks up the audit row. */}
          <ResponsibleManagersSection
            key={ticket.id}
            ticketId={ticket.id}
            canManage={isStaff}
            assignableManagers={assignableManagers}
            onChanged={() => {
              void loadTicket();
            }}
          />

          {/* Sprint 1 (frontend) — operational "Scheduled date" control.
              Surfaces the existing POST/DELETE /tickets/<id>/schedule/
              action (Sprint 9B backend) as a set / change / clear control,
              for ALL ticket types. Provider-management gated (SA/CA/BM via
              isProviderManagementRole); STAFF + customer roles see the
              scheduled date read-only inside the same card (no control, no
              403 call). A successful set/clear refetches the ticket so the
              date and the audit timeline refresh. */}
          <TicketScheduleCard
            ticket={ticket}
            canManage={isProviderManagementRole(me?.role)}
            onChanged={() => {
              void loadTicket();
            }}
          />

          {/* Sprint 30 Batch 30.1.1 — consolidated Details card. Merges
              the prior Ticket details, Customer Contacts, and SLA cards
              into ONE card with subtle subsection separators. Contacts
              are hidden entirely when the list is empty (no "No
              contacts on file." line). The Delete affordance lives at
              the card footer as a small text link; the confirmation
              dialog is unchanged. */}
          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_details_title")}
              </div>
            </div>
            <div style={{ padding: "14px 18px 16px" }}>
              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_location")}</span>
                  <span className="detail-kv-val">
                    <MapPin size={14} strokeWidth={2} />
                    {ticket.room_label || ticket.building_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_customer")}</span>
                  <span className="detail-kv-val">
                    <Users size={14} strokeWidth={2} />
                    {ticket.customer_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_category")}</span>
                  <span className="detail-kv-val">{ticket.type}</span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_created_by")}</span>
                  <span className="detail-kv-val">
                    {ticket.created_by_email}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_created")}</span>
                  <span className="detail-kv-val">
                    <Clock size={14} strokeWidth={2} />
                    {formatDate(ticket.created_at)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_first_response")}</span>
                  <span className="detail-kv-val">
                    {formatDate(ticket.first_response_at)}
                  </span>
                </div>
                {ticket.sent_for_approval_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_sent_for_approval")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.sent_for_approval_at)}
                    </span>
                  </div>
                )}
                {ticket.approved_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_approved")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.approved_at)}
                    </span>
                  </div>
                )}
                {ticket.closed_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_closed")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.closed_at)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Sprint 30 Batch 30.1.1 — Customer Contacts subsection
                inline in the consolidated Details card. SUPER_ADMIN /
                COMPANY_ADMIN only. The entire subsection (heading +
                body) is HIDDEN when the list is empty — no
                "No contacts on file." placeholder line. The previous
                outer-card `data-testid="ticket-customer-contacts-panel"`
                is preserved on the subsection wrapper so existing
                Playwright specs keep working. */}
            {canSeeCustomerContacts && customerContacts.length > 0 && (
              <div
                data-testid="ticket-customer-contacts-panel"
                style={{
                  borderTop: "1px solid var(--border)",
                  padding: "14px 18px 16px",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-faint)",
                    marginBottom: 10,
                  }}
                >
                  {t("details_subsection_contacts")}
                </div>
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
                      data-testid="ticket-customer-contact-row"
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
                          style={{ display: "flex", gap: 12, flexWrap: "wrap" }}
                        >
                          {contact.email && <span>{contact.email}</span>}
                          {contact.phone && <span>{contact.phone}</span>}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Sprint 30 Batch 30.1.1 — SLA subsection inline. The rich
                rendering (badge + paused/breached/completed meta) is
                preserved verbatim; only the wrapping card collapsed to
                a subsection inside Details. */}
            <div
              style={{
                borderTop: "1px solid var(--border)",
                padding: "14px 18px 16px",
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                  marginBottom: 10,
                }}
              >
                {t("details_subsection_sla")}
              </div>
              <div className="sla-detail-row">
                <SLABadge
                  state={ticket.sla_display_state}
                  remainingSeconds={ticket.sla_remaining_business_seconds}
                  size="md"
                />
                <span style={{ color: "var(--text-2)", fontSize: 13 }}>
                  {slaLabel(ticket.sla_display_state)}
                  {ticket.sla_display_state !== "PAUSED" &&
                    ticket.sla_display_state !== "COMPLETED" &&
                    ticket.sla_display_state !== "HISTORICAL" &&
                    ticket.sla_remaining_business_seconds !== null && (
                      <>
                        {" — "}
                        {formatSLATime(
                          ticket.sla_remaining_business_seconds,
                        )}
                      </>
                    )}
                </span>
              </div>
              <div className="sla-detail-meta">
                {ticket.sla_due_at &&
                  ticket.sla_display_state !== "HISTORICAL" &&
                  ticket.sla_display_state !== "COMPLETED" && (
                    <>
                      <span className="sla-detail-meta-label">{t("sla_due_label")}</span>
                      <span className="sla-detail-meta-value">
                        {formatDate(ticket.sla_due_at)}
                      </span>
                    </>
                  )}
                {ticket.sla_paused_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_paused_since_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_paused_at)}
                    </span>
                  </>
                )}
                {ticket.sla_first_breached_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_first_breached_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_first_breached_at)}
                    </span>
                  </>
                )}
                {ticket.sla_completed_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_completed_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_completed_at)}
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Sprint 30 Batch 30.1.1 — Delete-link footer. Demoted
                from the page header to a small text link in the card
                footer. The confirmation dialog and the underlying
                deletion endpoint are unchanged; only the entry-point
                affordance moved. Visible only to users the backend
                will actually accept (`canDeleteTicket` mirrors the
                `_user_can_soft_delete_ticket` rule). */}
            {canDeleteTicket && (
              <div
                style={{
                  borderTop: "1px solid var(--border)",
                  padding: "10px 18px 12px",
                  textAlign: "right",
                }}
              >
                <button
                  type="button"
                  onClick={openDeleteDialog}
                  disabled={deletingTicket}
                  className="link-back"
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    color: "var(--text-faint)",
                    fontSize: 12,
                  }}
                >
                  {t("delete_ticket_footer_link")}
                </button>
              </div>
            )}
          </div>

          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {canShowCompleteWorkButton
                  ? t("card_workflow_title_staff_complete")
                  : t("card_workflow_title")}
              </div>
            </div>
            <div className="workflow-body">
              {/* Sprint 28 Batch 11 — STAFF "Complete work" entry
                  point. Renders only for the assigned STAFF actor on
                  an IN_PROGRESS ticket; opens a modal that resolves
                  the destination (manager review vs customer
                  approval) and submits the corresponding status
                  transition.

                  UX hotfix: when this CTA renders, the generic
                  next-status UI (Status note + "Move to X" buttons)
                  is suppressed entirely so STAFF only sees ONE
                  clear action — "Complete work". The destination is
                  resolved server-side via the BSV
                  `staff_completion_routes_to_customer` flag; the
                  backend `allowed_next_statuses` also narrows STAFF
                  + IN_PROGRESS to the single resolved target so the
                  API contract matches. */}
              {canShowCompleteWorkButton ? (
                <>
                  <p
                    className="muted small"
                    data-testid="ticket-staff-complete-card-subtitle"
                    style={{ marginTop: 0, marginBottom: 8 }}
                  >
                    {t("card_workflow_subtitle_staff_complete")}
                  </p>
                  <div className="status-actions" style={{ marginBottom: 0 }}>
                    <button
                      type="button"
                      className="status-btn"
                      onClick={openCompleteModal}
                      disabled={completeModalOpen}
                      data-testid="ticket-staff-complete-button"
                    >
                      {t("common:ticket_staff_complete.button_label")}
                      <span className="status-btn-arrow">→</span>
                    </button>
                  </div>
                </>
              ) : visibleNextStatuses.length === 0 ? (
                // Disabled-action clarity: when the backend gives the
                // viewer zero transitions on a WCA ticket AND the
                // override action is explicitly false, surface the
                // *reason* rather than the generic terminal helper.
                // Driven by the per-record action, not a role string —
                // the only people who land here are providers without
                // override authority (CUSTOMER_USER on their own WCA
                // ticket gets APPROVED/REJECTED in allowed_next; STAFF
                // sees Complete Work or a non-WCA status).
                ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                ticket.actions?.can_override_customer_decision === false ? (
                  <p
                    className="muted small"
                    data-testid="workflow-wca-no-provider-decision"
                  >
                    {t("workflow_wca_no_provider_decision")}
                  </p>
                ) : (
                  <p className="muted small">
                    {t("workflow_no_transitions")}
                  </p>
                )
              ) : (
                <>
                  <div className="field">
                    <label className="field-label" htmlFor="status-note">
                      {me?.role === "CUSTOMER_USER" &&
                      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                      visibleNextStatuses.includes("REJECTED")
                        ? t("workflow_rejection_reason_label")
                        : staffCompletionEvidenceRequired
                          ? t("workflow_status_note_label_staff_required")
                          : t("workflow_status_note_label")}
                    </label>
                    <input
                      id="status-note"
                      className="field-input"
                      data-testid="workflow-status-note-input"
                      value={statusNote}
                      onChange={(event) => setStatusNote(event.target.value)}
                      placeholder={
                        me?.role === "CUSTOMER_USER" &&
                        ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                        visibleNextStatuses.includes("REJECTED")
                          ? t("workflow_rejection_reason_placeholder")
                          : t("workflow_status_note_placeholder")
                      }
                    />
                  </div>

                  {/* Sprint 25C — OSIUS staff-completion evidence hint.
                      Backend rejects the IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL
                      hop unless the ticket carries a note OR at least one
                      visible attachment. The page already has a full
                      attachments card lower down (upload + list); this hint
                      nudges the operator toward proof-of-work without
                      blocking the flow when a note alone is enough. */}
                  {isStaff &&
                    ticket.status === "IN_PROGRESS" &&
                    visibleNextStatuses.includes("WAITING_CUSTOMER_APPROVAL") && (
                      <p
                        className="muted small"
                        data-testid="workflow-completion-evidence-hint"
                        style={{ marginTop: 4, marginBottom: 4 }}
                      >
                        {t("workflow_completion_evidence_hint")}
                      </p>
                    )}

                  {me?.role === "CUSTOMER_USER" &&
                    ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                    visibleNextStatuses.includes("REJECTED") && (
                      <div className="alert-warning">
                        {t("workflow_customer_reject_warning")}
                      </div>
                    )}

                  {/* Sprint 30 Batch 30.1.1.5 — progressive disclosure.
                      Primary transitions render directly under
                      `.status-actions` so existing selectors keep
                      working. Secondary transitions live behind a
                      "More actions" toggle (or render inline-open
                      when the current status has zero primaries, e.g.
                      CLOSED). The per-button JSX is identical for
                      both groups — the `renderTransitionButton`
                      helper parameterises only the className.

                      Sprint 30 Batch 30.1.3 — on WCA, the override
                      arming flow is folded INTO the primary buttons:
                      a provider's click on Approve/Reject expands an
                      inline reason + Confirm/Cancel pair directly
                      under the buttons (no separate override card).
                      For a CUSTOMER_USER on the same step the
                      buttons stay direct (no `is_override` flag, no
                      reason prompt). */}
                  {(() => {
                    // STAFF on a completion-evidence-required step
                    // needs a note OR an image attachment before we
                    // enable any transition button. Frontend mirror
                    // of the backend `completion_evidence_required`
                    // 400 check.
                    const evidenceMissing =
                      staffCompletionEvidenceRequired &&
                      !statusNote.trim() &&
                      !hasImageAttachment;
                    const renderTransitionButton = (
                      status: TicketStatus,
                      variant: "primary" | "secondary",
                    ) => (
                      <button
                        key={status}
                        type="button"
                        className={
                          variant === "primary"
                            ? "status-btn"
                            : "status-btn status-btn-secondary"
                        }
                        disabled={statusBusy !== null || evidenceMissing}
                        data-testid={
                          variant === "primary"
                            ? `workflow-move-${status}`
                            : undefined
                        }
                        onClick={() => changeStatus(status)}
                      >
                        {statusBusy === status ? (
                          t("updating")
                        ) : (
                          <>
                            {/* Sprint 7B (frontend) — CONVERTED_TO_EXTRA_WORK
                                is filtered out of the render arrays above,
                                so this only ever labels real status moves.
                                Conversion lives on the dedicated header
                                "Convert to Extra Work" button. */}
                            {t("workflow_move_to", {
                              status: tStatus(status),
                            })}
                            <span className="status-btn-arrow">→</span>
                          </>
                        )}
                      </button>
                    );
                    // Sprint 30 Batch 30.1.3 — drop the plain
                    // APPROVED/REJECTED button targets when the
                    // actor is a provider on WCA. They re-render in
                    // the override-arming block below so the click
                    // never POSTs without an `override_reason` (the
                    // backend returns 400 `override_reason_required`
                    // on the empty-reason path).
                    // Sprint 7B (frontend) — NEVER render
                    // CONVERTED_TO_EXTRA_WORK as a raw status-transition
                    // button. That hop would flip the status WITHOUT
                    // creating the ExtraWorkRequest; conversion now runs
                    // through the dedicated convert endpoint + dialog
                    // (the prominent header "Convert to Extra Work"
                    // button). Drop it from both render groups so it can
                    // never POST to /status/.
                    const primaryForRender = (
                      providerActsAsOverride
                        ? primaryNextStatuses.filter(
                            (s) => s !== "APPROVED" && s !== "REJECTED",
                          )
                        : primaryNextStatuses
                    ).filter((s) => s !== "CONVERTED_TO_EXTRA_WORK");
                    const secondaryForRender = (
                      providerActsAsOverride
                        ? secondaryNextStatuses.filter(
                            (s) => s !== "APPROVED" && s !== "REJECTED",
                          )
                        : secondaryNextStatuses
                    ).filter((s) => s !== "CONVERTED_TO_EXTRA_WORK");
                    // Override-arming targets — only the WCA decision
                    // targets the actor is actually allowed to drive.
                    const overrideTargets: TicketStatus[] =
                      providerActsAsOverride
                        ? (PRIMARY_TRANSITIONS["WAITING_CUSTOMER_APPROVAL"]
                            .filter((s) => visibleNextStatuses.includes(s))) as TicketStatus[]
                        : [];
                    const renderOverrideButton = (status: TicketStatus) => {
                      const isArmed = overrideDecision === status;
                      return (
                        <div
                          key={status}
                          className="workflow-override-target"
                          data-testid={`workflow-override-${status}`}
                        >
                          <button
                            type="button"
                            className="status-btn"
                            disabled={statusBusy !== null || overrideBusy}
                            onClick={() => changeStatus(status)}
                            data-testid={`workflow-move-${status}`}
                            aria-expanded={isArmed}
                          >
                            <>
                              {t("workflow_move_to", { status: tStatus(status) })}
                              <span className="status-btn-arrow">→</span>
                            </>
                          </button>
                          {isArmed && (
                            <div
                              className="workflow-override-inline"
                              data-testid="ticket-override-modal"
                            >
                              <form onSubmit={submitOverride}>
                                <p
                                  className="muted small"
                                  style={{ margin: "0 0 6px" }}
                                >
                                  {t("override_inline_helper")}
                                </p>
                                <div className="field">
                                  <label
                                    className="field-label"
                                    htmlFor="ticket-override-reason"
                                  >
                                    {t("override_modal_reason_label")}
                                  </label>
                                  <textarea
                                    id="ticket-override-reason"
                                    data-testid="ticket-override-reason"
                                    className="field-textarea"
                                    rows={3}
                                    value={overrideReason}
                                    onChange={(event) =>
                                      setOverrideReason(event.target.value)
                                    }
                                    required
                                  />
                                </div>
                                {overrideError && (
                                  <div
                                    className="alert-error"
                                    role="alert"
                                    data-testid="ticket-override-error"
                                    style={{ marginTop: 6 }}
                                  >
                                    {overrideError}
                                  </div>
                                )}
                                <div className="override-card-footer card-actions-cluster">
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-sm"
                                    onClick={cancelOverride}
                                    disabled={overrideBusy}
                                    data-testid="ticket-override-cancel"
                                  >
                                    {t("override_modal_cancel")}
                                  </button>
                                  <button
                                    type="submit"
                                    className="btn btn-primary btn-sm"
                                    disabled={
                                      overrideBusy ||
                                      !overrideReason.trim()
                                    }
                                    data-testid="ticket-override-submit"
                                  >
                                    {overrideBusy
                                      ? t("updating")
                                      : overrideModalSubmitLabel(status)}
                                  </button>
                                </div>
                              </form>
                            </div>
                          )}
                        </div>
                      );
                    };
                    return (
                      <>
                        {(overrideTargets.length > 0 ||
                          primaryForRender.length > 0) && (
                          <div className="status-actions">
                            {overrideTargets.map((status) =>
                              renderOverrideButton(status),
                            )}
                            {primaryForRender.map((status) =>
                              renderTransitionButton(status, "primary"),
                            )}
                          </div>
                        )}
                        {evidenceMissing && (
                          <p
                            className="muted small"
                            data-testid="workflow-completion-evidence-required"
                            style={{ marginTop: 4 }}
                          >
                            {t("workflow_completion_evidence_required")}
                          </p>
                        )}
                        {secondaryForRender.length > 0 &&
                          !shouldDefaultOpenSecondary && (
                            <button
                              type="button"
                              className="workflow-more-actions-toggle"
                              data-testid="workflow-more-actions-toggle"
                              aria-expanded={isSecondaryOpen}
                              onClick={() =>
                                setSecondaryOpen((prev) => !prev)
                              }
                            >
                              {isSecondaryOpen
                                ? t("workflow_correction_actions_hide")
                                : t("workflow_correction_actions_show")}
                            </button>
                          )}
                        {secondaryForRender.length > 0 && isSecondaryOpen && (
                          <div
                            className="workflow-secondary-list"
                            data-testid="workflow-secondary-list"
                          >
                            {/* Set-subtraction header: every status here
                                is in allowed_next_statuses but NOT in
                                PRIMARY_TRANSITIONS for the current
                                state. They are admin corrections, not
                                the normal next step. The frontend does
                                not filter what the backend permits —
                                the partition only changes layout. */}
                            <p
                              className="muted small"
                              style={{ margin: "0 0 6px" }}
                            >
                              {t("workflow_correction_actions_help")}
                            </p>
                            {secondaryForRender.map((status) =>
                              renderTransitionButton(status, "secondary"),
                            )}
                          </div>
                        )}
                      </>
                    );
                  })()}
                </>
              )}
            </div>
          </div>

          {/* Sprint 30 Batch 30.1.3 — the standalone provider override
              card has been folded INTO the workflow card. The
              previously-locked 27F testids (`ticket-override-modal`,
              `ticket-override-reason`, `ticket-override-submit`,
              `ticket-override-cancel`, `ticket-override-error`) now
              live on the inline arming block under each Approve /
              Reject button. The two-press confirmation and mandatory
              `override_reason` audit contract are unchanged. */}

          {/* Sprint 28 Batch 11 — STAFF completion modal. Inline card
              shape (matches the override modal above rather than a
              floating overlay) so it slots into the right-rail
              naturally. Sourced from common.json
              `ticket_staff_complete.*` keys (EN/NL parity preserved
              by Batch 11's bundle update). The submit button label
              switches based on the resolved route. Photo upload is
              NOT inline — the page already has a dedicated
              Attachments card; the modal carries an explicit hint to
              upload first. Documented as remaining UX debt. */}
          {completeModalOpen && (
            <div className="card" data-testid="ticket-staff-complete-modal">
              <div className="section-head">
                <div
                  className="section-head-title"
                  style={{
                    fontSize: 11,
                    fontWeight: 800,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: "var(--text-faint)",
                  }}
                >
                  {t("common:ticket_staff_complete.modal_title")}
                </div>
              </div>
              <form
                onSubmit={submitCompleteWork}
                style={{ padding: "12px 18px 16px" }}
              >
                <p
                  className="muted small"
                  style={{ marginBottom: 12 }}
                  data-testid="ticket-staff-complete-route"
                >
                  {completeRouteLoading
                    ? t("common:ticket_staff_complete.route_loading")
                    : completeRoute === "customer_approval"
                      ? t(
                          "common:ticket_staff_complete.route_customer_approval",
                        )
                      : completeRoute === "manager_review"
                        ? t("common:ticket_staff_complete.route_manager_review")
                        : ""}
                </p>
                <div className="field">
                  <label
                    className="field-label"
                    htmlFor="ticket-staff-complete-note"
                  >
                    {/* Sprint 30 Batch 30.1.3 — STAFF completion gate
                        is note OR photo; relax the label so the user
                        knows either satisfies the audit requirement. */}
                    {t("common:ticket_staff_complete.note_label_or_photo")}
                  </label>
                  <textarea
                    id="ticket-staff-complete-note"
                    data-testid="ticket-staff-complete-note"
                    className="field-textarea"
                    rows={3}
                    value={completeNote}
                    onChange={(event) => setCompleteNote(event.target.value)}
                    placeholder={t(
                      "common:ticket_staff_complete.note_placeholder",
                    )}
                  />
                  <p className="muted small" style={{ marginTop: 4 }}>
                    {t("common:ticket_staff_complete.note_or_photo_hint")}
                  </p>
                </div>
                <p className="muted small" style={{ marginTop: 4 }}>
                  {hasImageAttachment
                    ? t("common:ticket_staff_complete.attachment_hint_satisfied")
                    : t("common:ticket_staff_complete.attachment_hint")}
                </p>
                {completeError && (
                  <div
                    className="alert-error"
                    role="alert"
                    data-testid="ticket-staff-complete-error"
                    style={{ marginTop: 8 }}
                  >
                    {completeError}
                  </div>
                )}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    gap: 8,
                    marginTop: 12,
                  }}
                >
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={closeCompleteModal}
                    disabled={completeBusy}
                    data-testid="ticket-staff-complete-cancel"
                  >
                    {t("common:ticket_staff_complete.cancel")}
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={
                      completeBusy ||
                      completeRouteLoading ||
                      !completeRoute ||
                      // Sprint 30 Batch 30.1.3 — STAFF can submit with
                      // a note OR an image attachment (mirrors the
                      // backend `completion_evidence_required` rule
                      // for STAFF on IN_PROGRESS → completion routes).
                      (!completeNote.trim() && !hasImageAttachment)
                    }
                    data-testid="ticket-staff-complete-submit"
                  >
                    {completeBusy
                      ? t("updating")
                      : completeRoute === "customer_approval"
                        ? t(
                            "common:ticket_staff_complete.submit_customer_approval",
                          )
                        : t(
                            "common:ticket_staff_complete.submit_manager_review",
                          )}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Sprint 30 Batch 30.1.1 — Status history card removed.
              The Activity Timeline above the fold already renders the
              same `ticket.status_history` rows (with override badge
              `timeline-override-badge`), so the bottom-of-page Status
              history card was a duplicate widget. The override badge
              testid for the timeline (`timeline-override-badge`) is
              still emitted from the activity timeline block above. */}

          {ticket.priority === "URGENT" && (
            <div className="card">
              <div className="card-head-icon">
                <span
                  className="card-head-icon-glyph"
                  style={{
                    background: "var(--red-soft)",
                    color: "var(--red)",
                  }}
                >
                  <TriangleAlert size={14} strokeWidth={2.2} />
                </span>
                <span className="card-head-icon-title">
                  {t("card_critical_title")}
                </span>
              </div>
              <p
                style={{
                  padding: "0 22px 18px",
                  fontSize: 13,
                  color: "var(--text-2)",
                  lineHeight: 1.55,
                }}
              >
                {t("card_critical_body")}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Sprint 7B (frontend) — Convert-to-Extra-Work dialog. Posts to
          the dedicated convert endpoint and, on success, navigates to
          the freshly-created ExtraWorkRequest detail page. */}
      {convertOpen && (
        <ConvertToExtraWorkDialog
          ticketId={ticket.id}
          onClose={() => setConvertOpen(false)}
          onConverted={(extraWorkRequestId) => {
            setConvertOpen(false);
            navigate(`/extra-work/${extraWorkRequestId}`);
          }}
        />
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("delete_ticket_dialog_title", {
          ticket_no: ticket.ticket_no,
        })}
        body={
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, lineHeight: 1.5 }}>
              {t("delete_ticket_dialog_body")}
            </p>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                fontSize: 12,
                color: "var(--text-muted)",
              }}
            >
              <span>{t("delete_ticket_confirm_label")}</span>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={ticket.ticket_no ?? ""}
                autoFocus
                style={{
                  height: 34,
                  padding: "0 10px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontFamily: "inherit",
                  fontSize: 13,
                }}
              />
            </label>
          </div>
        }
        confirmLabel={t("delete_ticket_confirm_button")}
        busyLabel={t("delete_ticket_confirm_busy")}
        onConfirm={confirmDeleteTicket}
        onCancel={() => setDeleteConfirmText("")}
        busy={deletingTicket}
        confirmDisabled={
          deleteConfirmText.trim() !== (ticket.ticket_no ?? "").trim()
        }
        destructive
      />
    </div>
  );
}

