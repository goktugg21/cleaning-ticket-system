import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  Activity,
  Archive,
  ArrowRightLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Eye,
  MapPin,
  MessageSquare,
  Paperclip,
  TriangleAlert,
  Undo2,
  UploadCloud,
  Users,
} from "lucide-react";
import axios from "axios";
import { Trans, useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
// W-UX1-B — reuse, not redesign: the same viewer the invoice preview
// opens, with its download button switched off.
import { PdfPreviewDialog } from "../components/PdfPreviewDialog";
import type { PdfPreviewDialogHandle } from "../components/PdfPreviewDialog";
import { markThreadRead, notifyInboxUnreadChanged } from "../api/inbox";
import {
  cancelStaffAssignmentRequest,
  createStaffAssignmentRequest,
  getStaffCompletionRoute,
  getTransitionRequirements,
  listAssignableStaff,
  listCustomerContacts,
  listStaffAssignmentRequests,
} from "../api/admin";
import { listTicketCategories, setTicketCategory } from "../api/tickets";
import { getMessageRecipients } from "../api/notifications";
import { formatDateTime } from "../lib/intl";
import { MyPartsPanel } from "./tickets/MyPartsPanel";
import { StaffAssignmentSection } from "./tickets/StaffAssignmentSection";
import { SubTaskReadOnly } from "./tickets/SubTaskReadOnly";
import { ResponsibleManagersSection } from "./tickets/ResponsibleManagersSection";
import {
  TicketTransitionModal,
  type TransitionAnswers,
} from "./tickets/TicketTransitionModal";
import { TicketScheduleCard } from "./tickets/TicketScheduleCard";
import type { AssignableStaff } from "../api/admin";
import type {
  AssignableManager,
  AssignedStaffNamedEntry,
  Contact,
  EwMessage,
  MessageRecipient,
  PaginatedResponse,
  StaffCompletionRoute,
  TicketAttachment,
  TicketDetail,
  TicketMessage,
  TicketMessageType,
  TicketStatus,
  TicketStatusChangePayload,
  TicketCategory,
  TicketTimelineRow,
  TransitionRequirements,
  // W6 §3 — the SHARED upload-visibility wire type. W-FIX5 deleted the
  // per-person explanation sentences and with them
  // `UPLOAD_SOURCE_LABEL_KEY`, which was this page's only reader of
  // `UploadVisibilitySource`.
  TicketUploadVisibility,
} from "../api/types";
import {
  getExtraWork,
  listEwMessages,
  listExtraWorkAssignments,
  planExtraWork,
} from "../api/extraWork";
import type {
  ExtraWorkAssignment,
  ExtraWorkPlanPayload,
  ExtraWorkRequestDetail,
} from "../api/types";
import { PlanWorkDialog } from "../components/extra-work/PlanWorkDialog";
import {
  getTicketUploadVisibility,
  setTicketUploadVisibility,
} from "../api/uploadVisibility";
import { getTicketAuditTimeline } from "../api/ticketTimeline";
import { useAuth } from "../auth/AuthContext";
import { useBackLink } from "../hooks/useBackLink";
import {
  canAccessExtraWork,
  composerTiersForRole,
  isCustomerUser,
  isProviderAdmin,
  isProviderManagementRole,
  isStaff as isStaffRoleFn,
} from "../auth/permissions";
import { TicketExtraWorkCards } from "../components/extra-work/TicketExtraWorkCards";
import { AttachmentThumb } from "../components/AttachmentThumb";
import { BillingCutoffNotice } from "../components/BillingCutoffNotice";
import { BoundedList } from "../components/BoundedList";
import { CollapsibleCard } from "../components/CollapsibleCard";
import { TicketArchiveDialog } from "../components/TicketArchiveDialog";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Toggle } from "../components/Toggle";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { ConvertToExtraWorkDialog } from "../components/ConvertToExtraWorkDialog";
import { useToast } from "../components/ToastProvider";
import { RouteBadge } from "../components/RouteBadge";
import { UnifiedTimeline } from "../components/UnifiedTimeline";
import { SLABadge } from "../components/sla/SLABadge";
import { describeTicketChange } from "../lib/describeTicketChange";
import { ticketStatusLabelKey } from "../lib/enumLabels";

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
  CUSTOMER_INTERNAL: "tag_customer_internal",
};

const NOTE_TIER_BUBBLE_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "",
  INTERNAL_NOTE: "internal",
  STAFF_OPERATIONAL: "internal",
  STAFF_COMPLETION: "",
  CUSTOMER_INTERNAL: "internal",
};

const NOTE_TIER_TAG_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "public",
  INTERNAL_NOTE: "",
  STAFF_OPERATIONAL: "",
  STAFF_COMPLETION: "",
  CUSTOMER_INTERNAL: "",
};

const NOTE_TIER_COMPOSER_LABEL_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public",
  INTERNAL_NOTE: "composer_internal",
  STAFF_OPERATIONAL: "composer_staff_operational",
  STAFF_COMPLETION: "composer_staff_completion",
  CUSTOMER_INTERNAL: "composer_customer_internal",
};

const NOTE_TIER_PLACEHOLDER_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public_placeholder",
  INTERNAL_NOTE: "composer_internal_placeholder",
  STAFF_OPERATIONAL: "composer_staff_operational_placeholder",
  STAFF_COMPLETION: "composer_staff_completion_placeholder",
  CUSTOMER_INTERNAL: "composer_customer_internal_placeholder",
};

// "Who sees this" description rendered under the composer-tier
// toggle. The map covers all five tiers so the helper line renders
// even when the viewer only has one tier available (the toggle row
// itself hides in that case, but the visibility statement still
// shows so an author never posts without knowing the audience).
const NOTE_TIER_WHO_SEES_KEY: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "composer_public_who_sees",
  INTERNAL_NOTE: "composer_internal_who_sees",
  STAFF_OPERATIONAL: "composer_staff_operational_who_sees",
  STAFF_COMPLETION: "composer_staff_completion_who_sees",
  CUSTOMER_INTERNAL: "composer_customer_internal_who_sees",
};

const NOTE_TIER_TONE_CLASS: Record<TicketMessageType, string> = {
  PUBLIC_REPLY: "",
  INTERNAL_NOTE: "internal",
  STAFF_OPERATIONAL: "internal",
  STAFF_COMPLETION: "",
  CUSTOMER_INTERNAL: "internal",
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
  // W13 §1 — ONE entry per status. The renderer takes the FIRST legal
  // one and puts every other legal move behind "other actions".
  //
  // The owner's father, on a card offering three: "I press it, I don't
  // know what it does, I don't know why I press it — because you are
  // telling me to press it." Two buttons that both look like the next
  // step mean the page has not decided, and a reader cannot decide
  // either. The list is still a LIST because the first entry may be
  // illegal for this actor; the second is then the primary, and so on.
  //
  // IN_PROGRESS carried three (manager review, customer approval, on
  // hold). Manager review is first because it is the system's own
  // default: `BuildingStaffVisibility.staff_completion_routes_to_customer`
  // is false unless somebody set it, and when it IS set the backend
  // narrows `allowed_next_statuses` to the customer route for that
  // staffer, so the first LEGAL entry resolves to the right one without
  // this table knowing anything about the flag.
  OPEN: ["ACKNOWLEDGED"],
  ACKNOWLEDGED: ["IN_PROGRESS"],
  ON_HOLD: ["IN_PROGRESS"],
  IN_PROGRESS: ["WAITING_MANAGER_REVIEW", "WAITING_CUSTOMER_APPROVAL"],
  WAITING_MANAGER_REVIEW: ["WAITING_CUSTOMER_APPROVAL"],
  // The customer's own decision is a genuine pair: approving and
  // rejecting are opposite answers to one question, not two candidate
  // next steps, and hiding "reject" behind a disclosure would be a
  // dishonest screen. This is the one deliberate exception.
  WAITING_CUSTOMER_APPROVAL: ["APPROVED", "REJECTED"],
  APPROVED: ["CLOSED"],
  REJECTED: ["IN_PROGRESS"],
  CLOSED: [],
  REOPENED_BY_ADMIN: ["IN_PROGRESS"],
  CONVERTED_TO_EXTRA_WORK: [],
};
/**
 * W9 §2 — WHICH MOVES UNDO PROGRESS, by rank rather than by list.
 *
 * The owner: "if something moves from In Progress to a customer-related
 * status or another stage, there should be a clear way to move it back
 * ... I couldn't clearly find where this exists in Tickets." He could
 * not find it because it lived behind a text link called "Show
 * correction actions", and on the status where it matters most it was
 * not reachable at all (see WAITING_MANAGER_REVIEW above).
 *
 * WHY A RANK AND NOT A HARDCODED PAIR LIST. `ALLOWED_TRANSITIONS` has
 * only two backward pairs, so a pair list looked right — and it was
 * wrong for the one role that matters here. `allowed_next_statuses`
 * (state_machine.py, the SUPER_ADMIN_ALLOWED_NEXT_ALL_STATUSES branch,
 * Sprint 184 §2) deliberately hands a SUPER_ADMIN EVERY status except
 * the current one and CONVERTED_TO_EXTRA_WORK. So for the owner's own
 * role a backward move exists from every status, including the
 * WAITING_CUSTOMER_APPROVAL -> IN_PROGRESS he asked about, and a
 * two-entry list would have surfaced almost none of them.
 *
 * The rank is the normal progression. A move is a correction when it
 * goes to a lower rank than where the ticket stands. That is true for
 * whoever is looking: a manager sending work back, a SUPER_ADMIN
 * pulling a job out of the customer's hands. Nothing here widens what
 * anybody may do — every button still comes from the backend's
 * `allowed_next_statuses` and the endpoint re-checks it.
 */
const STATUS_RANK: Record<TicketStatus, number> = {
  OPEN: 0,
  // W10 §1 — between open and started, which is what it means.
  ACKNOWLEDGED: 0.5,
  IN_PROGRESS: 1,
  // W10 §2 — a hold is a PAUSE, not a step back. It ranks with the work
  // it interrupts, so resuming reads as forward and parking does not
  // read as a correction.
  ON_HOLD: 1,
  // Back in the crew's hands, so it ranks with IN_PROGRESS rather than
  // after CLOSED, where its name would otherwise put it.
  REOPENED_BY_ADMIN: 1,
  WAITING_MANAGER_REVIEW: 2,
  WAITING_CUSTOMER_APPROVAL: 3,
  APPROVED: 4,
  REJECTED: 4,
  CLOSED: 5,
  CONVERTED_TO_EXTRA_WORK: 5,
};

/**
 * States whose backward-looking move is the ONLY thing to do next, and
 * is therefore resumption rather than correction. A rejected job going
 * back to IN_PROGRESS is the crew getting on with it — the existing
 * `WORKFLOW_TONE` note makes the same call and calls it forward motion.
 * Painting it amber under "Correct a mistake" would tell an operator
 * that the normal path through a rejection is an error.
 */
const RESUME_TARGETS: Partial<Record<TicketStatus, TicketStatus[]>> = {
  REJECTED: ["IN_PROGRESS"],
  REOPENED_BY_ADMIN: ["IN_PROGRESS"],
};

/** Is this move a correction rather than a step forward? */
function isCorrection(
  currentStatus: TicketStatus,
  nextStatus: TicketStatus,
): boolean {
  if ((RESUME_TARGETS[currentStatus] ?? []).includes(nextStatus)) return false;
  return STATUS_RANK[nextStatus] < STATUS_RANK[currentStatus];
}

// Sprint 190 §3 — colour carries MEANING on the workflow rail, so the
// mapping from "where this button sends the ticket" to "what colour it
// wears" is a Record over the whole TicketStatus union, not a list of
// the negative ones. A Record is exhaustive by construction: add a
// tenth status to `TicketStatus` and this fails to compile until
// somebody says whether it is a forward step or a rejection. A
// `Set(["REJECTED"])` would instead silently paint the new status green
// — which is exactly the class of bug CLAUDE.md's "iterate the shared
// exported constant" note was written about.
//
// "advance" is every step that moves work along, INCLUDING CLOSED (the
// normal end of a job) and INCLUDING IN_PROGRESS reached from REJECTED
// (redoing the work is forward motion). Only an actual rejection is
// "reject". CONVERTED_TO_EXTRA_WORK is filtered out of both render
// arrays and never reaches a button; it is listed so the Record stays
// total.
type WorkflowTone = "advance" | "reject" | "hold";

/** Work that is over. A finished job is never "upcoming", whatever its
 *  planned start says. */
const TERMINAL_UI_STATUSES = new Set<TicketStatus>([
  "APPROVED",
  "REJECTED",
  "CLOSED",
  "CONVERTED_TO_EXTRA_WORK",
]);
const WORKFLOW_TONE: Record<TicketStatus, WorkflowTone> = {
  OPEN: "advance",
  ACKNOWLEDGED: "advance",
  IN_PROGRESS: "advance",
  // Parking a job is neither progress nor a rejection. It gets the
  // "needs a person to act" tone, which is what `--state-waiting` is
  // for, rather than the green of a step completed.
  ON_HOLD: "hold",
  WAITING_MANAGER_REVIEW: "advance",
  WAITING_CUSTOMER_APPROVAL: "advance",
  APPROVED: "advance",
  REJECTED: "reject",
  CLOSED: "advance",
  REOPENED_BY_ADMIN: "advance",
  CONVERTED_TO_EXTRA_WORK: "advance",
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
  // W9 §2 — a correction never counts as a forward step, even when
  // PRIMARY_TRANSITIONS names it. `WAITING_MANAGER_REVIEW` legitimately
  // lists IN_PROGRESS as one of its two real targets; it belongs in the
  // correction group, which is where the split below puts it.
  const legalPrimaries = primaryOrder.filter(
    (s) => allowedSet.has(s) && !isCorrection(currentStatus, s),
  );
  // W13 §1 — ONE primary, and the first legal one wins.
  //
  // The exception is a QUESTION PUT TO THE READER rather than a next
  // step: approve and reject are the two answers to "do you accept
  // this work", and putting one behind a disclosure would hide half
  // the question. Everywhere else, a second forward button means the
  // page has not decided.
  const primary =
    currentStatus === "WAITING_CUSTOMER_APPROVAL"
      ? legalPrimaries
      : legalPrimaries.slice(0, 1);
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

// W4-M §4a — frontend mirror of the backend `_SCHEDULE_TERMINAL_STATUSES`
// set that also guards PATCH /tickets/<id>/attachment-visibility-policy/
// (400 `attachment_visibility_policy_not_allowed_terminal`). Declared
// here rather than imported from TicketScheduleCard: that file is a card
// component, not a constants module, and the two uses are independent.
const PHOTO_POLICY_TERMINAL_STATUSES: ReadonlySet<TicketStatus> = new Set<
  TicketStatus
>(["APPROVED", "REJECTED", "CLOSED", "CONVERTED_TO_EXTRA_WORK"]);

// W4-M §4b — the PER-TICKET half of the staff photo pre-permission.
//
// The field, the resolver and both endpoints are chat P's
// (`backend/tickets/models.py::UploadVisibilityGrant`,
// `backend/tickets/attachment_visibility.py`,
// `backend/tickets/views_upload_visibility.py`). This page renders the
// per-ticket scope only:
//
//   GET   /api/tickets/<id>/upload-visibility/
//   PATCH /api/tickets/<id>/upload-visibility/<user_id>/
//         { uploads_customer_visible: true | false | null }
//
// `null` is not `false`. null CLEARS the decision at this scope and lets
// the standing permission answer again; false is an explicit refusal
// that outranks the standing permission for this ticket. The control
// below is therefore three-state, not a toggle — a toggle would have to
// silently pick one of grant/clear and would make one of them
// unreachable.
//
// W6 §3 — THE TYPES USED TO BE DECLARED HERE, AND ARE NOT ANY MORE.
//
// W4-P wrote local copies of `UploadVisibilitySource`,
// `TicketUploadVisibilityPerson` and the response shape in this file,
// with the note "declared here rather than in `api/types.ts` because the
// same wave is writing that file for the STANDING scope". That was the
// right call for one sprint and the wrong thing to leave behind: the
// shared versions landed in `api/types.ts` in that same wave, together
// with a typed client in `api/uploadVisibility.ts`, and two
// independently maintained descriptions of one wire contract is the
// Sprint 126/130 failure mode — the copy nobody edits goes quietly stale
// and the compiler cannot tell you, because each copy is internally
// consistent.
//
// Two deliberate differences absorbed by collapsing onto the shared
// types, neither of which changes behaviour here:
//
//   * `ticket_id` is `number | null` on the shared type, because
//     `UploadVisibilityGrantState` also describes the STANDING scope,
//     which has no ticket. This page never reads the field.
//   * `effective_visibility` is `AttachmentVisibility`, which IS
//     `"INTERNAL" | "CUSTOMER"` — the same two strings the local copy
//     spelled out, now derived from the same `as const` array the
//     attachment types use.
//
// `UploadVisibilitySource` is now derived from the exported
// `UPLOAD_VISIBILITY_SOURCES` constant, so the exhaustive Record below
// is checked against the one list a new source would be added to.

// The three states the <select> offers. A union type, not a `const`
// array: nothing iterates the list (the three <option>s are written out
// so each can carry its own scope-bearing label), so an array would be a
// runtime value that exists only to be read as a type.
type UploadGrantChoice = "INHERIT" | "GRANT" | "REFUSE";

function grantChoiceOf(value: boolean | null): UploadGrantChoice {
  if (value === null) return "INHERIT";
  return value ? "GRANT" : "REFUSE";
}

function grantChoiceValue(choice: UploadGrantChoice): boolean | null {
  if (choice === "INHERIT") return null;
  return choice === "GRANT";
}

const ACCEPTED_ATTACHMENT_TYPES =
  ".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf";
const MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024;

// Delegates to lib/intl so dates follow the app language (nl-NL/en-US
// derived from i18n.language), not the host OS locale. Name kept so the
// existing call sites stay unchanged; lib formatDateTime handles
// null/empty/parse-fail (returns "—").
function formatDate(value: string | null): string {
  return formatDateTime(value);
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

// RF-4 (Ramazan 2026-06-23) — the unified audit timeline carries low-signal
// system rows (e.g. "Created · Ticketmanagerassignment — No tracked field
// changed"): an audit_log entry with no diffed fields and no reason. We hide
// these by default and reveal them behind a "show system events" toggle, so
// the (already collapsed) Activity drawer reads cleanly when opened. Nothing
// is removed — the full set is one click away.
function isLowSignalAuditRow(row: TicketTimelineRow): boolean {
  if (row.source !== "audit_log") return false;
  const hasChanges =
    !!row.changes &&
    typeof row.changes === "object" &&
    Object.keys(row.changes).length > 0;
  const hasReason = !!(row.reason && row.reason.trim());
  return !hasChanges && !hasReason;
}

// RF-5 — how an attachment can be previewed in-app, derived from its stored
// MIME type. PDFs render in an <iframe>; browser-native raster images render
// in an <img>. HEIC/HEIF (allowed on upload but not decodable by most
// browsers) and anything else fall back to a download-only notice.
type AttachmentPreviewKind = "pdf" | "image" | "unsupported";
function attachmentPreviewKind(mimeType: string): AttachmentPreviewKind {
  if (mimeType === "application/pdf") return "pdf";
  if (
    mimeType === "image/jpeg" ||
    mimeType === "image/png" ||
    mimeType === "image/webp"
  ) {
    return "image";
  }
  return "unsupported";
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


/* W-TABS Task 4 — THE SAME SPINE AS THE EXTRA WORK PAGE ("chip chip").
 * The exported ordered constant every consumer iterates (CLAUDE.md —
 * a second, independently maintained render list is how the Sprint 126
 * headerless column happened), the same `composer-toggle` pill classes,
 * the same `?tab=` search param with `replace: true` and absence as the
 * overview default. Visibility is resolved per render because the Money
 * tab depends on the TICKET (extra-work origin), not only the role —
 * absent entirely for tickets with no money dimension. */
const TICKET_TABS = [
  "overview",
  "people",
  "plan",
  "money",
  "messages",
] as const;
type TicketTab = (typeof TICKET_TABS)[number];

export function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  /**
   * W14 §3 — "BACK TO TICKETS" NOW GOES TO TICKETS.
   *
   * All three of this page's back links were `<Link to="/">` under the
   * label `back_to_tickets`. So the control that says "Back to tickets"
   * landed on the DASHBOARD — the owner's "it throws me to the
   * dashboard", in the literal sense that the link pointed there — and
   * being a `<Link>` it PUSHED, so the browser's own Back then came
   * straight back into the ticket.
   *
   * `/tickets` is the page the label names and the page the reader came
   * from, and `useBackLink` steps the history back to it when it is the
   * entry behind this one, so the list returns with its filters, its
   * page and its scroll rather than remounted from scratch.
   */
  /* W17 §1 — BACK GOES WHERE YOU CAME FROM (the W15 rule, moved here
   * with the destination). A chargeable row opens the TICKET now, and
   * Chargeable work mounts on two routes (`/tickets/chargeable` and
   * `/admin/customers/<id>/chargeable`), so the row puts its own
   * address in history state. Read, never trusted for navigation
   * beyond a same-origin path: anything that is not a string beginning
   * with a single `/` falls back to the tickets list. */
  const routeLocation = useLocation();
  const chargeableFrom = (() => {
    const raw = (routeLocation.state as { chargeableFrom?: unknown } | null)
      ?.chargeableFrom;
    if (typeof raw !== "string") return null;
    // `//host` is a protocol-relative URL, not an in-app path.
    if (!raw.startsWith("/") || raw.startsWith("//")) return null;
    return raw;
  })();
  const backToTickets = useBackLink(chargeableFrom ?? "/tickets");

  /* W-TABS Task 4 — the tab, from the URL, the EW page's exact rule:
     absence IS overview, so the plain /tickets/<id> every existing link
     and notification uses stays the canonical address. Clamping against
     the VISIBLE set happens below once the ticket is loaded. */
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const requestedTicketTab: TicketTab = (
    TICKET_TABS as readonly string[]
  ).includes(tabParam ?? "")
    ? (tabParam as TicketTab)
    : "overview";
  const setTicketTab = (next: TicketTab) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === "overview") params.delete("tab");
        else params.set("tab", next);
        return params;
      },
      { replace: true },
    );
  };
  const { me } = useAuth();
  const { t } = useTranslation(["ticket_detail", "common"]);
  // The label never lies about the destination: it names the chargeable
  // list exactly when the link goes there. Key reused from the bundle
  // that already owns the phrase.
  const backToTicketsLabel = chargeableFrom
    ? t("extra_work:back_to_chargeable_work")
    : t("back_to_tickets");
  // M2 P5 — type / customer-facing labels for the resolver-gated
  // credential summaries on assigned-staff entries (reuses the P4
  // namespace; keys are NOT duplicated here).
  const { t: tCred } = useTranslation("staff_credentials");
  const toast = useToast();

  const tStatus = (status: TicketStatus | string | null): string => {
    if (!status) return t("status_default_created");
    // Sprint 182 integration -- one vocabulary. See UnifiedTimeline.
    return t(`common:${ticketStatusLabelKey(status)}`);
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

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  /** Sprint 185 E §1 — the company's own kinds of WORK, for the picker.
   *  Loaded once; non-fatal on failure, like every other optional picker
   *  here — a catalog that would not load must not stop somebody reading
   *  the melding. */
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [categoryBusy, setCategoryBusy] = useState(false);
  // W4-M §4a — the per-work photo-visibility switch (PA/SA only). One
  // busy flag; the value itself is read straight off the ticket so the
  // control can never drift from what the server stored.
  const [photoPolicyBusy, setPhotoPolicyBusy] = useState(false);
  // W4-M §4b — the per-ticket upload permission per assigned person.
  // `null` while the read has not answered (or is not available to this
  // viewer); the section renders nothing at all in that case rather than
  // showing an empty control that cannot be used.
  const [uploadGrants, setUploadGrants] =
    useState<TicketUploadVisibility | null>(null);
  const [uploadGrantBusyUserId, setUploadGrantBusyUserId] = useState<
    number | null
  >(null);
  const [uploadGrantsNonce, setUploadGrantsNonce] = useState(0);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  // W18 — the Extra Work thread of the job this ticket was born from,
  // shown read-only inside the ONE Messages card (merged by date). Both
  // endpoints are server-filtered by the canonical visibility
  // chokepoints; this is display only. A failed fetch collapses to the
  // ticket thread alone.
  const [ewMessages, setEwMessages] = useState<EwMessage[]>([]);
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
  // RF-4 (Ramazan 2026-06-23) — the Activity timeline is a good, transparent
  // feature but should not dominate the page at first glance. It now lives in
  // a drawer collapsed by default ("at a glance minimal, depth behind a
  // click"); `showSystemEvents` reveals the low-signal no-op audit rows that
  // are otherwise condensed away while the drawer is open.
  const [activityOpen, setActivityOpen] = useState(false);
  const [showSystemEvents, setShowSystemEvents] = useState(false);
  // W14 §2 — where the Activity card sits on the page, so a note that
  // was just written can be shown ARRIVING instead of described.
  const activityCardRef = useRef<HTMLDivElement>(null);
  // Armed by `revealStatusNote()`, consumed by the effect that does the
  // scrolling once the drawer and its rows are actually on the page.
  const revealPendingRef = useRef(false);
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
  // W11 §1 — is the correction-actions list open, and ON WHICH TICKET.
  //
  // Storing the ticket id rather than a boolean is what makes the list
  // collapse again when you navigate to the next melding. A boolean
  // would need somebody to remember to reset it — an effect, or a key,
  // or a bug. The route param already owns "which ticket am I looking
  // at", so this just says which one the operator opened the door on,
  // and any other id closes it by definition.
  const [correctionsOpenFor, setCorrectionsOpenFor] =
    useState<string | null>(null);
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
  // Composer tier list (M1 B5) — driven by the per-record `ticket.actions`
  // POSTING flags when the detail has loaded, so the composer NEVER offers a
  // tier the backend would reject. Net per role: CUST = PUBLIC_REPLY +
  // CUSTOMER_INTERNAL; STAFF = STAFF_OPERATIONAL + STAFF_COMPLETION; MGMT/SA =
  // PUBLIC_REPLY + INTERNAL_NOTE + STAFF_OPERATIONAL + STAFF_COMPLETION.
  // Falls back to the role-based predicate before the detail loads (or for
  // older serializers without `actions`), so the page never crashes on
  // undefined.
  const composerTiers = useMemo<TicketMessageType[]>(() => {
    const actions = ticket?.actions;
    if (actions) {
      const tiers: TicketMessageType[] = [];
      if (actions.can_post_public_reply) tiers.push("PUBLIC_REPLY");
      if (actions.can_post_provider_internal_note) tiers.push("INTERNAL_NOTE");
      if (actions.can_post_staff_operational_note) tiers.push("STAFF_OPERATIONAL");
      if (actions.can_post_staff_completion_note) tiers.push("STAFF_COMPLETION");
      if (actions.can_post_customer_internal_note) tiers.push("CUSTOMER_INTERNAL");
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
  // M1 B5 — who may make a message RESTRICTED ("Private"): provider
  // management / SA on any tier they post; a customer-side user ONLY on the
  // CUSTOMER_INTERNAL tier (they can notify customer-side people on a
  // PUBLIC_REPLY, but cannot make a PUBLIC_REPLY private). STAFF never (and
  // their picker is empty anyway, so the whole block is hidden). This mirrors
  // the server-side `restricted_only_for_customer_internal` /
  // `staff_cannot_direct_or_restrict` rules so RESTRICTED stays UI-unreachable
  // where the backend would 400.
  const canUsePrivate =
    isProviderManagementRole(me?.role) ||
    (isCustomerUser(me?.role) && effectiveMessageType === "CUSTOMER_INTERNAL");
  const effectivePrivate =
    canUsePrivate && isPrivate && directedTo.length > 0;

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
  /** W-UX1-B — the in-app viewer for credential / property documents.
   *  One dialog for the whole section: it is opened imperatively with a
   *  target, so a second instance per row would buy nothing. Rendered
   *  UNCONDITIONALLY at the end of the page and driven entirely through
   *  this ref — a native <dialog> mounted behind a condition is an
   *  invisible dialog and a dead-looking button. */
  const credentialPreviewRef = useRef<PdfPreviewDialogHandle>(null);

  /** W-FIX-B — OPEN A BACKEND-EMITTED `document_url` IN THE VIEWER.
   *
   *  The credential / property payloads carry Django `reverse()` paths,
   *  which begin "/api/..." (`tickets/serializers.py:1364`), while the
   *  axios instance's baseURL ALREADY ends in "/api". Handing the raw
   *  value to `PdfPreviewDialog.open()` made it fetch
   *  "/api/api/users/<id>/credentials/<id>/download/", and the viewer
   *  reported the only thing it could: "We couldn't find what you were
   *  looking for". The badge was right, the document was there, and the
   *  request went to a URL that does not exist.
   *
   *  The DOWNLOAD path has always known this — `downloadDocumentFromUrl`
   *  (`api/staffCredentials.ts:169`) strips the same prefix and says why
   *  in its docstring. The preview added in W-UX1-B simply did not
   *  inherit it. One function here, used by all three preview call sites
   *  (provider table badge, customer credential row, customer property
   *  row), so the page cannot fix one and leave another broken.
   *
   *  AUTHORIZATION IS UNTOUCHED. The endpoint is unchanged and
   *  `credential_document_visible_to_user` stays the only gate; this
   *  corrects which URL the browser asks for, not who may be answered. */
  function openDocumentPreview(documentUrl: string, filename: string) {
    const path = documentUrl.startsWith("/api/")
      ? documentUrl.slice("/api".length)
      : documentUrl;
    credentialPreviewRef.current?.open({ url: path, filename });
  }

  /** W-FIX3 — each assigned person's credentials, keyed by user id.
   *  Straight off `ticket.assigned_staff`, which the SERVER has already
   *  filtered through `accounts.visibility` for this viewer's role
   *  (W-UX1-A widened that to every viewer). No filtering happens here:
   *  a second ladder on the client is how the two drift apart. */
  const credentialsByUserId = useMemo(() => {
    const out: Record<
      number,
      { type: string; expiry_date?: string | null; document_url?: string | null }[]
    > = {};
    for (const entry of ticket?.assigned_staff ?? []) {
      if ("anonymous" in entry && entry.anonymous) continue;
      const named = entry as {
        id: number;
        credentials?: {
          type: string;
          expiry_date?: string | null;
          document_url?: string | null;
        }[];
      };
      if (named.credentials?.length) out[named.id] = named.credentials;
    }
    return out;
  }, [ticket?.assigned_staff]);

  /** W-FIX1 — the crew already on this ticket, as {id, label}. The modal
   *  shows them as the settled default and NEVER posts them back: the
   *  assignable-staff endpoint already excludes anyone holding a base
   *  slot here (`views_staff_assignments.py:952`), so re-sending them is
   *  a duplicate the server refuses with `staff_already_assigned`. */
  const currentAssignees = useMemo(
    () =>
      (ticket?.assigned_staff ?? [])
        .filter((entry) => !("anonymous" in entry && entry.anonymous))
        .map((entry) => {
          const named = entry as {
            id: number;
            full_name?: string;
            email?: string;
          };
          return {
            id: named.id,
            label:
              named.full_name?.trim() || named.email || String(named.id),
          };
        }),
    [ticket?.assigned_staff],
  );

  /** R2 — the ticket's planned start as `<input type="datetime-local">`
   *  wants it: LOCAL wall time, no zone, minute precision. Built by hand
   *  rather than with `toISOString().slice(0,16)`, which would render the
   *  UTC instant and show an operator east of Greenwich the wrong hour —
   *  the mirror of the bug the modal's own confirm() comment warns about
   *  in the other direction. */
  const currentScheduledStartLocal = useMemo(() => {
    const raw = ticket?.scheduled_start_at;
    if (!raw) return "";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }, [ticket?.scheduled_start_at]);

  const [downloadingAttachmentId, setDownloadingAttachmentId] =
    useState<number | null>(null);
  // RF-5 (Ramazan 2026-06-23) — in-app attachment preview. Clicking a tile
  // opens a modal that renders the file IN the app (PDF inline / image
  // inline) over an authenticated blob object URL, instead of triggering a
  // download. The bytes are fetched the same way the download path already
  // does (authenticated axios blob), so no backend change is needed. The
  // object URL is tracked in a ref so it can be revoked on close AND on
  // unmount without a setState-in-effect.
  const [previewItem, setPreviewItem] = useState<TicketAttachment | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const previewUrlRef = useRef<string | null>(null);
  const previewDialogRef = useRef<HTMLDialogElement>(null);
  // M2 P5 — busy marker for a staff credential/property document
  // download (keyed by document_url; one in flight at a time).

  const [assignableManagers, setAssignableManagers] = useState<
    AssignableManager[]
  >([]);

  /** W-FIX-C — bumped when a staff assignment is written from OUTSIDE
   *  `<StaffAssignmentSection>`, which owns a separate copy of the
   *  roster. Today that is exactly one path: the transition modal posts
   *  `assigned_staff_ids` with the move, so `changeStatus` bumps it on
   *  success. Reloading the page's own ticket is not enough — that
   *  refreshes the card's header count and the customer-side list, and
   *  the provider's assignment TABLE is the section's own state. */
  const [assignmentReloadNonce, setAssignmentReloadNonce] = useState(0);

  // W13-FIX §1 — THE TRANSITION MODAL's state. `transitionTarget` is the
  // status the operator pressed; while it is set the modal is open and
  // NOTHING has been posted yet. The move only happens when the modal
  // calls back with its answers.
  const [transitionTarget, setTransitionTarget] =
    useState<TicketStatus | null>(null);
  const [transitionReqs, setTransitionReqs] =
    useState<TransitionRequirements | null>(null);
  const [transitionLoading, setTransitionLoading] = useState(false);
  const [transitionStaff, setTransitionStaff] = useState<AssignableStaff[]>([]);
  const [transitionError, setTransitionError] = useState("");

  // Phase B — the dated staff-slot CRUD (Sprint 25A's flat add/remove
  // superseded) now lives in <StaffAssignmentSection>, which owns its own state.

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
  // W-T3 §1 — ERRORS AT THE ACTION.
  //
  // Seven mutations on this page reported failure by setting the
  // page-level `error`, which renders in a banner at the very top of a
  // long scrolling ticket. Flip the photo switch near the attachments,
  // or fail to send a message from the composer, and the only sign was
  // a sentence far above the fold, often off screen entirely: the
  // control simply looked as if it had done nothing.
  //
  // The page already had the right shape in three places
  // (`overrideError`, `requestAssignmentError`, `completeError`): a
  // dedicated message rendered beside the control that failed. This is
  // that pattern for the remaining seven. ONE keyed store rather than
  // seven more `useState`s, because the per-person photo-permission
  // buttons need a key per row and separate states cannot express that.
  //
  // `error` itself stays, and stays at the top, for the one thing that
  // genuinely belongs there: the initial ticket LOAD failing, which is
  // not an action anybody just took.
  const [actionError, setActionError] = useState<Record<string, string>>({});

  function failAt(key: string, err: unknown) {
    setActionError((current) => ({ ...current, [key]: getApiError(err) }));
  }
  function clearAt(key: string) {
    setActionError((current) => {
      if (current[key] === undefined) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }
  function actionErrorNode(key: string, testId: string) {
    const message = actionError[key];
    if (!message) return null;
    return (
      <div className="alert-error" role="alert" data-testid={testId}>
        {message}
      </div>
    );
  }

  const isStaff = isProviderManagementRole(me?.role);

  // W26.4 — how many of this ticket's parts the VIEWER is on. Drives the
  // choice between the worker's actionable "My parts" and the read-only
  // split view; `MyPartsPanel` applies the same filter internally, so
  // the two cannot disagree about what "mine" means.
  const myPartCount = (ticket?.sub_tasks ?? []).filter((part) =>
    part.staff_assignments.some((slot) => slot.user_id === me?.id),
  ).length;

  /**
   * W11 §1 — IS THIS MOVE A DECISION TAKEN OUT OF THE CUSTOMER'S HANDS?
   *
   * Answered by the backend, per record:
   * `actions.can_override_customer_decision` is True only when the
   * viewer holds override authority AND the ticket stands at
   * WAITING_CUSTOMER_APPROVAL AND the decision targets are in
   * `allowed_next_statuses`. The page used to answer it a second time
   * from the role name — which read SUPER_ADMIN and COMPANY_ADMIN and
   * therefore missed a Building Manager holding the B6 override key,
   * and would keep missing whoever the rule admits next. Two answers to
   * one question, and the local one was the wrong one.
   */
  const isCustomerDecisionOverride = (toStatus: TicketStatus): boolean =>
    ticket?.actions?.can_override_customer_decision === true &&
    (toStatus === "APPROVED" || toStatus === "REJECTED");

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

  /* W-H §1 — THE ARCHIVE, and it is the same button in two directions.
   *
   * Terminal-only, so it can never take live work out of the list, and
   * `TERMINAL_UI_STATUSES` is disjoint from `CONVERTIBLE_TICKET_STATUSES`
   * — which is what keeps rule 2 (one primary action) true in the
   * header: on a finished ticket Convert is impossible, and archiving IS
   * the next thing to do. */
  const isArchived = !!ticket?.archived_at;
  const canArchive =
    !!ticket &&
    isProviderManagementRole(me?.role) &&
    TERMINAL_UI_STATUSES.has(ticket.status) &&
    !isArchived;
  const canUnarchive =
    !!ticket && isProviderManagementRole(me?.role) && isArchived;
  const [archiveMode, setArchiveMode] = useState<
    "archive" | "unarchive" | null
  >(null);

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

  // RF-1 — opening the ticket marks its message thread read for this user
  // (advance the inbox cursor) and refreshes the sidebar badge. Async, no
  // setState here.
  useEffect(() => {
    if (!id) return;
    void markThreadRead("ticket", Number(id))
      .then(() => notifyInboxUnreadChanged())
      .catch(() => {});
  }, [id]);

  // W18 — the origin Extra Work's own thread, for the merged Messages
  // card. Same gate as the Extra-work card mount (`canAccessExtraWork`:
  // STAFF are hard-404'd by `scope_extra_work_for`, so the call must
  // never fire for them; customers keep their surfaces). The endpoint
  // is chokepoint-filtered server-side — display only. Failure or an
  // ordinary ticket collapses to the ticket thread alone. State is set
  // only in async callbacks / a microtask (no set-state-in-effect).
  const ewOriginId = ticket?.extra_work_origin?.extra_work_request_id ?? null;

  /* W-PLAN Task 2 — THE PLAN LIVES ON THE OPERATIONAL PAGE TOO.
     One component, two mounts: this is the SAME PlanWorkDialog the
     Extra Work page opens, bound to the SAME store — the plan has one
     home (the EW: `provider_planned_*`, `ExtraWorkPlannedHours`,
     `budget_hours`, the two proof toggles the ticket's own completion
     gate already reads via `tickets/completion_requirements.py`), so
     there is nothing to copy and nothing to fork. Delivery dates write
     through the one date writer, which moves this ticket's schedule
     (`extra_work/dates.py` -> `planned_date.py`). Crew changes stay in
     the Assignment section: candidates are handed over EMPTY, so the
     dialog's picker renders nothing and adds nobody. */
  const [ewPlanOpen, setEwPlanOpen] = useState(false);
  const [ewPlanDetail, setEwPlanDetail] = useState<
    ExtraWorkRequestDetail | null
  >(null);
  const [ewPlanAssignments, setEwPlanAssignments] = useState<
    ExtraWorkAssignment[]
  >([]);
  const [ewPlanLoading, setEwPlanLoading] = useState(false);
  const [ewPlanBusy, setEwPlanBusy] = useState(false);
  const [ewPlanError, setEwPlanError] = useState("");

  /* W-TABS Task 4 — the Plan tab shows the plan it holds (planned
     hours per person), read from the SAME store the dialog writes.
     Lazy: fetched when the tab is looked at, refetched after a save
     (submitEwPlan clears `ewPlanDetail`). */
  useEffect(() => {
    if (
      requestedTicketTab !== "plan" ||
      ewOriginId === null ||
      ewPlanDetail !== null ||
      !isProviderManagementRole(me?.role) ||
      !canAccessExtraWork(me?.role)
    ) {
      return;
    }
    let cancelled = false;
    getExtraWork(ewOriginId)
      .then((detail) => {
        if (!cancelled) setEwPlanDetail(detail);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [requestedTicketTab, ewOriginId, ewPlanDetail, me?.role]);

  async function openEwPlan() {
    if (ewOriginId === null) return;
    setEwPlanError("");
    setEwPlanLoading(true);
    setEwPlanOpen(true);
    try {
      const [detail, assignments] = await Promise.all([
        getExtraWork(ewOriginId),
        listExtraWorkAssignments(ewOriginId),
      ]);
      setEwPlanDetail(detail);
      setEwPlanAssignments(assignments);
    } catch (err) {
      setEwPlanOpen(false);
      toast.push({ variant: "error", title: getApiError(err) });
    } finally {
      setEwPlanLoading(false);
    }
  }

  async function submitEwPlan(payload: ExtraWorkPlanPayload) {
    if (ewOriginId === null) return;
    setEwPlanBusy(true);
    setEwPlanError("");
    try {
      // `start: false` — starting is the TICKET's business after spawn
      // (the EW's status follows the ticket); this save is a plan
      // change, and it answers in one sentence via the toast while the
      // timeline gains its "Plan changed: ..." row server-side.
      await planExtraWork(ewOriginId, { ...payload, start: false });
      setEwPlanOpen(false);
      setEwPlanDetail(null);
      toast.push({ variant: "success", title: t("ew_plan_saved") });
      await loadTicket();
    } catch (err) {
      setEwPlanError(getApiError(err));
    } finally {
      setEwPlanBusy(false);
    }
  }
  useEffect(() => {
    let cancelled = false;
    if (ewOriginId === null || !canAccessExtraWork(me?.role)) {
      queueMicrotask(() => {
        if (!cancelled) setEwMessages([]);
      });
      return () => {
        cancelled = true;
      };
    }
    listEwMessages(ewOriginId)
      .then((list) => {
        if (!cancelled) setEwMessages(list);
      })
      .catch(() => {
        if (!cancelled) setEwMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ewOriginId, me?.role]);

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

  // W4-M §4b — read the per-ticket upload permissions.
  //
  // Provider management only, mirroring the endpoint's own gate; the
  // request does not even fire for anyone else. A failure is swallowed
  // and the section stays unrendered: this permission is an optional
  // refinement of a ticket page that has to keep working without it,
  // and — while the two halves of this wave land in parallel — a 404
  // from a backend that does not carry the endpoint yet must read as
  // "not available here", never as a page-level error.
  const canGrantUploadVisibility = isProviderManagementRole(me?.role);
  const uploadGrantsTicketId = ticket?.id ?? null;
  useEffect(() => {
    const cancelled = { current: false };
    if (!canGrantUploadVisibility || uploadGrantsTicketId === null) {
      queueMicrotask(() => {
        if (!cancelled.current) setUploadGrants(null);
      });
    } else {
      getTicketUploadVisibility(uploadGrantsTicketId)
        .then((data) => {
          if (!cancelled.current) setUploadGrants(data);
        })
        .catch(() => {
          if (!cancelled.current) setUploadGrants(null);
        });
    }
    return () => {
      cancelled.current = true;
    };
  }, [canGrantUploadVisibility, uploadGrantsTicketId, uploadGrantsNonce]);

  // W4-M §4b — grant / refuse / clear one person's uploads on THIS
  // ticket. The PATCH answers with that one person's new row, so the
  // list is patched in place instead of refetched; the ticket itself is
  // untouched by the call.
  async function setUploadGrant(userId: number, choice: UploadGrantChoice) {
    if (!id) return;
    clearAt(`grant:${userId}`);
    setUploadGrantBusyUserId(userId);
    try {
      const updated = await setTicketUploadVisibility(
        id,
        userId,
        grantChoiceValue(choice),
      );
      setUploadGrants((previous) =>
        previous === null
          ? previous
          : {
              ...previous,
              people: previous.people.map((person) =>
                person.user_id === userId ? updated : person,
              ),
            },
      );
      // The grant writes an AuditLog row and no status history, so the
      // timeline needs the same nudge the category change gives it.
      setAuditReloadNonce((n) => n + 1);
    } catch (err) {
      failAt(`grant:${userId}`, err);
      // A refused write must not leave the control showing the value the
      // operator picked, so re-read the authoritative list.
      setUploadGrantsNonce((n) => n + 1);
    } finally {
      setUploadGrantBusyUserId(null);
    }
  }

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

  const correctionsOpen = correctionsOpenFor === id;

  // W4-M §2 — when did this job arrive at the status it is in? Read off
  // `status_history` rather than any single timestamp column, because
  // no one column covers every status (there is an `approved_at` and a
  // `closed_at`, but nothing for OPEN or IN_PROGRESS). Ordering of the
  // serialized rows is not contracted, so this takes the LATEST
  // created_at among the rows that landed on the current status rather
  // than trusting first/last. A ticket that never transitioned (still
  // OPEN, no history) yields null and the line simply does not render.
  const currentStatusSince = useMemo(() => {
    if (!ticket) return null;
    let latest: string | null = null;
    for (const row of ticket.status_history ?? []) {
      if (row.new_status !== ticket.status) continue;
      if (latest === null || row.created_at > latest) latest = row.created_at;
    }
    return latest;
  }, [ticket]);

  /**
   * W10 §5 — THE STEP JUST TAKEN, which is the only step there is
   * anything to undo.
   *
   * Corrections used to be every reverse edge in the graph, listed at
   * once, always. On a closed ticket a SUPER_ADMIN saw seven ways
   * backwards — a menu of moves nobody had made and nobody wanted. A
   * correction is only meaningful against a MISTAKE, and the mistake it
   * can plausibly fix is the last transition.
   *
   * So this reads the newest history row's `old_status`: where the
   * ticket came from. `status_history` already owns that fact, so
   * nothing new is stored and there is no second place to keep it in
   * step. A ticket that has never moved has no previous status and
   * therefore offers no correction, which is right — there is nothing
   * to take back.
   *
   * This applies to SUPER_ADMIN exactly as to everyone else; the owner
   * asked for that by name. It removes no power: every other backward
   * move a role holds is still in the quiet list below, and the backend
   * still decides what is legal.
   */
  /**
   * W10 §3 — is this job still in the future?
   *
   * True when a planned start exists, is still ahead of now, and the
   * work is not finished. Derived on every render from the clock, so it
   * turns itself off when the date arrives — no job, no flag, nobody
   * remembering. `scheduled_start_at` is the single owner of when the
   * work is due; this reads it and stores nothing.
   */
  // THE CLOCK IS NOT READ DURING RENDER. `Date.now()` in a memo is
  // impure — and it is also wrong for this feature: a memo over the
  // ticket never recomputes just because time passed, so the strip
  // would still claim "upcoming" at midday on the day the job started.
  // The tick is what makes "moves itself when the date arrives" true
  // rather than a thing somebody has to reload the page for. It starts
  // at 0 so the first render reads no clock at all; the immediate
  // timeout fills it in a moment later, and the interval keeps it
  // honest once a minute.
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const immediate = setTimeout(tick, 0);
    const every = setInterval(tick, 60_000);
    return () => {
      clearTimeout(immediate);
      clearInterval(every);
    };
  }, []);

  const isUpcoming = useMemo(() => {
    if (now === 0) return false;
    if (!ticket?.scheduled_start_at) return false;
    if (TERMINAL_UI_STATUSES.has(ticket.status)) return false;
    return new Date(ticket.scheduled_start_at).getTime() > now;
  }, [ticket, now]);

  const previousStatus = useMemo<TicketStatus | null>(() => {
    if (!ticket) return null;
    let newest: { at: string; from: TicketStatus } | null = null;
    for (const row of ticket.status_history ?? []) {
      if (row.new_status !== ticket.status) continue;
      if (newest === null || row.created_at > newest.at) {
        newest = { at: row.created_at, from: row.old_status as TicketStatus };
      }
    }
    return newest?.from ?? null;
  }, [ticket]);

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
  // Sprint 28 Batch 11 — the "Complete work" button only renders for
  // a STAFF user who is actually on the ticket's assignment set and
  // is looking at an IN_PROGRESS ticket. Backend enforces the same
  // gate on the transition; this is purely UX.
  const canShowCompleteWorkButton =
    !!ticket &&
    me?.role === "STAFF" &&
    ticket.status === "IN_PROGRESS" &&
    ticket.is_assigned_staff === true;

  // W13 — the pickable categories, loaded once. Non-fatal: a catalog
  // that would not load must not stop somebody reading the melding, and
  // the row falls back to the stored name.
  //
  // UNFILTERED, unlike the create forms. This screen must offer
  // "Ongegrond" (§4 — the verdict is reached here) and must keep
  // offering an archived category the melding already carries, so
  // narrowing happens in the `.filter()` at the picker rather than in
  // the request.
  //
  // W13-FIX §3 — SCOPED TO THIS MELDING'S COMPANY.
  //
  // The seven categories are seeded PER COMPANY, so an unfiltered read
  // returns seven per tenant and the picker listed the owner's seven
  // three times over. A melding belongs to exactly one company and can
  // only ever carry that company's category, so the request says so.
  // For a single-tenant operator this changes nothing; for a
  // SUPER_ADMIN it is the difference between seven options and
  // twenty-one.
  useEffect(() => {
    if (!isProviderManagementRole(me?.role)) return;
    const companyId = ticket?.company;
    if (!companyId) return;
    let cancelled = false;
    listTicketCategories({ company: companyId })
      .then((rows) => {
        if (!cancelled) setCategories(rows);
      })
      .catch(() => {
        /* non-fatal: the melding still reads */
      });
    return () => {
      cancelled = true;
    };
  }, [me?.role, ticket?.company]);

  async function saveCategory(categoryId: number | null) {
    if (!id) return;
    clearAt("category");
    setCategoryBusy(true);
    try {
      const updated = await setTicketCategory(Number(id), categoryId);
      setTicket(updated);
      // A category change writes an AuditLog row and no status history,
      // so the timeline needs the same nudge assignment gives it.
      setAuditReloadNonce((n) => n + 1);
    } catch (err) {
      failAt("category", err);
    } finally {
      setCategoryBusy(false);
    }
  }

  // W4-M §4a — flip Ticket.staff_uploads_customer_visible.
  //
  // What this changes is what happens to the NEXT staff upload on this
  // work. It does not reach back: photos already stored keep the
  // audience they were given, which is why the caption under the switch
  // says so in words rather than leaving a manager to assume otherwise.
  // The endpoint answers with the full ticket, so the response is the
  // new state — no optimistic local value to get out of step.
  async function setPhotoVisibilityPolicy(nextValue: boolean) {
    if (!id) return;
    clearAt("photo_policy");
    setPhotoPolicyBusy(true);
    try {
      const response = await api.patch<TicketDetail>(
        `/tickets/${id}/attachment-visibility-policy/`,
        { staff_uploads_customer_visible: nextValue },
      );
      setTicket(response.data);
      // The flip writes an AuditLog row and no status history, so the
      // timeline needs the same nudge the category change gives it.
      setAuditReloadNonce((n) => n + 1);
      toast.push({
        variant: "success",
        title: nextValue
          ? t("photo_policy_toast_on")
          : t("photo_policy_toast_off"),
        description: t("photo_policy_toast_scope"),
      });
    } catch (err) {
      failAt("photo_policy", err);
    } finally {
      setPhotoPolicyBusy(false);
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

  /**
   * W13-FIX §1 — the operator pressed a workflow move.
   *
   * This no longer posts. It asks the server what the step needs and
   * opens the modal; `changeStatus` runs only when the modal calls back
   * with the answers. The two customer-decision / override paths still
   * arm the reason prompt as they did, because a reason is a different
   * question from "what does this step need" and already has its own
   * dedicated surface.
   */
  async function openTransition(toStatus: TicketStatus) {
    if (!id || !ticket) return;
    if (isCustomerDecisionOverride(toStatus)) {
      // Unchanged Sprint 27F-F1 behaviour: arm the reason prompt.
      setOverrideDecision(toStatus);
      setOverrideReason("");
      setOverrideError(null);
      return;
    }

    setTransitionTarget(toStatus);
    setTransitionReqs(null);
    setTransitionError("");
    setTransitionLoading(true);
    try {
      const reqs = await getTransitionRequirements(Number(id), toStatus);
      setTransitionReqs(reqs);
      // Only fetch the staff list when the step actually asks who is
      // doing the work -- most moves do not, and an unused list is a
      // request the operator waits on for nothing.
      // W-FIX1 — WHENEVER THE BLOCK RENDERS, not only when the
      // requirement is unmet. R2 made the assignee block render on a
      // step that already has a crew, and this condition did not follow:
      // the list stayed empty, so a modal on a fully-assigned ticket
      // said "nobody available to assign" about a job with people on it.
      if (reqs.requirements.some((r) => r.key === "assignee")) {
        try {
          setTransitionStaff(await listAssignableStaff(Number(id)));
        } catch {
          // A caller without the staff-assign permission still gets the
          // modal; the picker simply reports nobody available rather
          // than the whole step failing.
          setTransitionStaff([]);
        }
      } else {
        setTransitionStaff([]);
      }
    } catch (err) {
      setTransitionError(getApiError(err));
    } finally {
      setTransitionLoading(false);
    }
  }

  async function changeStatus(
    toStatus: TicketStatus,
    answers?: TransitionAnswers,
  ) {
    if (!id || !ticket) return;

    setError("");

    // Sprint 27F-F1 — a provider taking the customer's decision arms
    // the reason prompt BEFORE posting. The button click sets
    // `overrideDecision`; the actual API call fires from
    // `submitOverride` below, which posts the reason per the 27F-B1
    // contract. This is the one case armed pre-emptively, because there
    // the prompt is a deliberate speed bump rather than a reaction to a
    // refusal.
    const needsAdminDecisionOverride = isCustomerDecisionOverride(toStatus);

    // W10 §4 — A REQUIRED FIELD THAT DOES NOT EXIST MAKES THE ACTION
    // IMPOSSIBLE. This is the bug the owner hit: he tried to move a
    // ticket back to Open, was told a reason was required, and had
    // nowhere to type one.
    //
    // Sprint 184 §2 made EVERY jump outside `ALLOWED_TRANSITIONS` an
    // override that demands `override_reason` — correctly, because a
    // hand-typed jump was otherwise indistinguishable from a step
    // somebody earned. But the page only ever collected a reason for
    // ONE case, the provider driving a customer decision on
    // WAITING_CUSTOMER_APPROVAL. Every other jump posted `note` alone
    // and came back 400 `override_reason_required`, with no field on
    // screen for the reason it was asking for. For a SUPER_ADMIN, whose
    // `allowed_next_statuses` is every status, that is most of the
    // buttons on the card.
    //
    // WHO KNOWS WHICH MOVES NEED A REASON. The state machine, and only
    // the state machine. Mirroring `ALLOWED_TRANSITIONS` here to predict
    // it would put one fact in two files and guarantee they drift — the
    // failure this codebase has already had twice. So the page does not
    // predict: it asks, the backend refuses with the stable code
    // `override_reason_required`, and the catch below opens this same
    // prompt and resubmits. One owner, and a page that cannot be wrong
    // about a rule it does not hold.
    //
    // The pre-emptive branch stays for the customer-decision case only,
    // because there the prompt is a deliberate speed bump rather than a
    // reaction to a refusal.
    //
    // The status note is NOT the reason and is not repurposed as one:
    // the note is the operational comment on the move, `override_reason`
    // is the justification the audit row carries, and collapsing them
    // would put one value in two meanings.
    if (needsAdminDecisionOverride) {
      setOverrideDecision(toStatus);
      setOverrideReason("");
      setOverrideError(null);
      return;
    }

    // W13-FIX §1 — read the EFFECTIVE note. A customer rejecting through
    // the modal types their reason into the modal, not into the card's
    // inline note, so checking `statusNote` alone would refuse a
    // rejection that was in fact explained.
    const effectiveNote = (answers?.note ?? statusNote).trim();
    if (
      me?.role === "CUSTOMER_USER" &&
      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
      toStatus === "REJECTED" &&
      !effectiveNote
    ) {
      const message = t("workflow_customer_rejection_required");
      setError(message);
      setTransitionError(message);
      return;
    }

    setStatusBusy(toStatus);

    try {
      const payload: TicketStatusChangePayload = {
        to_status: toStatus,
        // The modal's note wins when it collected one; the card's
        // inline status note stays the fallback for the paths that do
        // not go through the modal.
        note: effectiveNote,
        ...(answers?.assigned_staff_ids
          ? { assigned_staff_ids: answers.assigned_staff_ids }
          : {}),
        ...(answers?.scheduled_start_at
          ? { scheduled_start_at: answers.scheduled_start_at }
          : {}),
        // W14 §4 — the modal asked for it because
        // `transition-requirements` said this move is an override, so
        // it travels with the move. Absent on every ordinary step, and
        // `apply_transition` stores it only when it coerces the flag —
        // whether this IS an override stays the backend's call.
        ...(answers?.override_reason
          ? { override_reason: answers.override_reason }
          : {}),
        // W-UX1 §4 — and the FLAG, on the one path that must send it.
        // The comment above is still the rule everywhere else: whether a
        // move is an override is the backend's call. The proof bypass is
        // the exception, because the machine cannot infer it — the
        // status pair is an ordinary completion, and what makes it an
        // override is that the operator chose to skip required evidence.
        // Without the flag `state_machine` writes
        // `override_reason if is_override else ""` and the reason is
        // dropped, so the bypass would cost nothing and record nothing.
        ...(answers?.is_override ? { is_override: true } : {}),
      };
      const response = await api.post<TicketDetail>(
        `/tickets/${id}/status/`,
        payload,
      );

      // W13 — the transition ANSWERS. It used to do exactly these two
      // lines and nothing else, which is the father's "I press it, I
      // don't know what it does": the page looked slightly different
      // afterwards and you were left to work out whether that was you.
      const said = describeTicketChange(ticket, response.data, t, tStatus);
      setTicket(response.data);
      // W-FIX-C — the move CARRIED PEOPLE, so the card that lists them
      // has to re-read. `setTicket` above refreshes the header count and
      // the customer-side roster (both read `ticket.assigned_staff`,
      // which the status response rebuilds from the database), but the
      // provider's assignment table is `<StaffAssignmentSection>`'s own
      // state and nothing here reaches it. Bumped only when people
      // actually travelled with the move, so an ordinary status change
      // costs no extra requests.
      if (answers?.assigned_staff_ids?.length) {
        setAssignmentReloadNonce((n) => n + 1);
      }
      setStatusNote("");
      setTransitionTarget(null);
      setTransitionReqs(null);
      // W14 §2 — EVERY ACTION ANSWERS (rule 4), and when the operator
      // wrote something the answer has to account for it too. The
      // sentence names the place, and `revealStatusNote()` below opens
      // it, so the words and the page say the same thing.
      const noteLine = effectiveNote ? t("change.note_recorded") : null;
      if (said) {
        const detail = [said.description, noteLine].filter(
          (part): part is string => Boolean(part),
        );
        toast.push({
          variant: "success",
          title: said.title,
          description: detail.length > 0 ? detail.join(" ") : undefined,
        });
      }
      if (effectiveNote) revealStatusNote();
    } catch (err) {
      // W10 §4 — the backend asked for a reason, so give the operator
      // somewhere to type one instead of an error they cannot act on.
      // Matching the stable `code`, never the message.
      if (axios.isAxiosError(err)) {
        const data = err.response?.data as { code?: string } | undefined;
        if (data?.code === "override_reason_required") {
          // W14 §4 — THE MODAL STAYS OPEN AND SAYS WHAT IS MISSING.
          //
          // This used to close the modal and arm the small inline
          // reason prompt in the workflow card instead. Walked on
          // crmtest: the modal vanished, no toast was raised, nothing
          // said the ticket had not moved, and a different form
          // appeared somewhere else on the page. From the operator's
          // chair the button simply did nothing — the owner's "I could
          // not get them to work".
          //
          // With `transition-requirements` now reporting
          // `override_reason` this branch should no longer be reached
          // for a move the modal opened; it stays as the safety net for
          // the case the two ever disagree, and a safety net that
          // silently swallows the refusal is not one. So: same surface,
          // requirement added, answers already typed kept, and the
          // reason stated inside the modal that asked.
          setTransitionReqs((current) =>
            current === null || current.unmet.includes("override_reason")
              ? current
              : {
                  ...current,
                  requirements: [
                    ...current.requirements,
                    { key: "override_reason", satisfied: false },
                  ],
                  unmet: [...current.unmet, "override_reason"],
                },
          );
          setTransitionError(t("transition.reason_required"));
          setStatusBusy(null);
          return;
        }
      }
      // W13 — a failure is louder than a success and names the next
      // move. `error` toasts are sticky in the provider, so this waits
      // to be dismissed rather than vanishing unread, and it says the
      // ticket did NOT move — the thing an operator has to know before
      // pressing anything again.
      // W-FIX1 — ONCE, and where the press happened. This used to do
      // both: a sticky error toast AND the inline line, so one refusal
      // arrived twice and the toast covered the modal it was about.
      // The modal is the surface the operator is looking at, so when one
      // is open it gets the refusal and the toast stays quiet.
      setTransitionError(getApiError(err));
      if (transitionTarget === null) {
        toast.push({
          variant: "error",
          title: t("change.failed"),
          description: getApiError(err),
        });
      }
    } finally {
      setStatusBusy(null);
    }
  }

  // W14 §2 — SHOW THE NOTE LANDING.
  //
  // "Where does the note I write here go, what is it for? I write it and
  // leave — does it show anywhere?"
  //
  // It was never swallowed. It is `TicketStatusHistory.note`, it comes
  // back on `GET /api/tickets/<id>/` as `status_history[].note` and on
  // `GET /api/audit/tickets/<id>/timeline/`, and BOTH timeline
  // renderers on this page already print it against the transition row
  // it belongs to. What was missing was the room: the Activity card is
  // collapsed by default (RF-4, on purpose — "at a glance minimal") and
  // sits under three other cards, so somebody who typed a note, pressed
  // a button and left never saw it arrive and had no reason to believe
  // it had.
  //
  // So the page shows them, once, at the only moment it is an answer to
  // a question they just asked: the drawer opens and the card is
  // scrolled to, right after a transition that carried something. Every
  // other arrival at this page is untouched — RF-4's default still
  // holds.
  //
  // THE SCROLL CANNOT HAPPEN HERE, and the first cut of this that did
  // was measured not working: the card ended up at y=911 in a 1000px
  // viewport, barely on screen. Two reasons, both real. The transition
  // modal is a native `<dialog>`, and while one is open the page behind
  // it is inert — a `scrollIntoView()` fired in the same synchronous
  // block as `setTransitionTarget(null)` runs before the dialog is
  // actually gone, and does nothing. And the row being scrolled to does
  // not exist yet: the ticket has only just been replaced and the audit
  // timeline has not refetched, so the card is still at its old height
  // and its old place on the page. Both are fixed by deferring to the
  // effect below, which runs after the dialog has unmounted and after
  // the rows that move the card have rendered.
  function revealStatusNote() {
    revealPendingRef.current = true;
    setActivityOpen(true);
    // W-TABS Task 4 — the activity card lives on the Overview tab now;
    // a reveal fired from anywhere else must land where the card is.
    setTicketTab("overview");
  }

  // W14 §2 — the deferred half of `revealStatusNote()`.
  //
  // Runs on the render after the drawer opened, which is also the render
  // after the transition modal unmounted, so the page is scrollable
  // again. `ticket` and `auditTimeline` are dependencies because they
  // are what MOVES the card: each one lands more rows in the drawer and
  // pushes the card's position on the page. The ref makes every one of
  // those re-runs a no-op except the first that finds something to show.
  //
  // `block: "center"` rather than "start": the card ends up in the
  // middle of the viewport with the new row inside it, instead of
  // pinned to the top edge where the reader has to work out that the
  // page moved at all.
  useEffect(() => {
    const rowsOnPage =
      (ticket?.status_history.length ?? 0) + (auditTimeline?.rows.length ?? 0);
    if (!revealPendingRef.current || !activityOpen || rowsOnPage === 0) return;
    revealPendingRef.current = false;
    activityCardRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [activityOpen, ticket, auditTimeline]);

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
      // W10 §4 — `is_override` is the BACKEND's call, not ours.
      //
      // It coerces the flag True for a provider-driven customer decision
      // and for any jump outside the transition table, and it stores the
      // reason only when the flag is set. Asserting `is_override: true`
      // from here on a move the backend considers ordinary would stamp a
      // legitimate step as an override in the audit trail — a fact
      // written by the wrong owner. Sending the reason and letting the
      // machine decide keeps the history telling the truth either way.
      const payload: TicketStatusChangePayload = {
        to_status: overrideDecision,
        override_reason: overrideReason.trim(),
        note: statusNote.trim(),
      };
      await api.post<TicketDetail>(`/tickets/${id}/status/`, payload);
      // Refetch via loadTicket so messages / attachments stay in sync
      // alongside the new status_history row.
      await loadTicket();
      // W14 §2 — this path carries the SAME status-note field plus the
      // override reason, and both land on the same timeline row. A note
      // written here would otherwise be the one that still vanished.
      const wroteSomething = Boolean(statusNote.trim() || overrideReason.trim());
      setStatusNote("");
      setOverrideDecision(null);
      setOverrideReason("");
      if (wroteSomething) revealStatusNote();
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
    clearAt("message");
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
      failAt("message", err);
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
    clearAt("download");
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
      failAt("download", err);
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  // RF-5 — revoke the current preview object URL and drop the ref. Called on
  // close and (via the unmount effect) when the page goes away.
  function revokePreviewUrl() {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  }

  // RF-5 — open the in-app preview modal for an attachment. The fetch is
  // driven by this click handler (never an effect), so there is no
  // setState-in-effect; the modal opens immediately in a loading state and
  // fills in once the authenticated blob resolves.
  async function openAttachmentPreview(item: TicketAttachment) {
    if (!id) return;
    revokePreviewUrl();
    setPreviewItem(item);
    setPreviewUrl(null);
    setPreviewError("");
    setPreviewLoading(true);
    previewDialogRef.current?.showModal();
    try {
      const response = await api.get(
        `/tickets/${id}/attachments/${item.id}/download/`,
        { responseType: "blob" },
      );
      const blobUrl = URL.createObjectURL(response.data);
      previewUrlRef.current = blobUrl;
      setPreviewUrl(blobUrl);
    } catch (err) {
      setPreviewError(getApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  // Buttons / backdrop request a close; the real cleanup runs in the
  // dialog's onClose handler so Esc-to-close is handled the same way.
  function requestPreviewClose() {
    previewDialogRef.current?.close();
  }

  function handlePreviewClosed() {
    revokePreviewUrl();
    setPreviewUrl(null);
    setPreviewItem(null);
    setPreviewError("");
    setPreviewLoading(false);
  }

  // RF-5 — revoke a still-open preview URL if the page unmounts mid-preview.
  // Empty deps + cleanup-only body ⇒ no setState in an effect.
  // Also close the preview <dialog> if it is still open: showModal() puts it in
  // the top layer and makes the document inert, and tearing the node out on
  // unmount without close() can leave the page scrollable-but-click-dead on
  // engines that don't run the <dialog> "removing steps" reliably (same top-
  // layer safety as ConfirmDialog). The node is copied in the effect body so
  // the ref read keeps the hooks lint rule satisfied.
  useEffect(() => {
    const dialog = previewDialogRef.current;
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = null;
      }
      if (dialog?.open) dialog.close();
    };
  }, []);

  async function submitAttachment(event: FormEvent) {
    event.preventDefault();
    if (!id || !selectedFile) return;

    if (selectedFile.size > MAX_ATTACHMENT_SIZE_BYTES) {
      setError(t("attachment_too_large"));
      return;
    }

    clearAt("attachment");
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
      failAt("attachment", err);
    } finally {
      setUploadingAttachment(false);
    }
  }

  if (loading && !ticket) {
    return (
      <div>
        <Link {...backToTickets} className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {backToTicketsLabel}
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
        <Link {...backToTickets} className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {backToTicketsLabel}
        </Link>
        <div className="alert-error">{error || t("ticket_not_found")}</div>
      </div>
    );
  }

  // W18 — ONE Messages card for the job: the ticket thread plus the
  // origin Extra Work's thread (read-only, chip-marked), merged by
  // date. Both endpoints return ascending `created_at`, so the merge
  // sorts the same way; ids collide across the two tables, hence the
  // prefixed keys.
  const jobThread: Array<
    | { key: string; source: "ticket"; msg: TicketMessage }
    | { key: string; source: "ew"; msg: EwMessage }
  > = [
    ...messages.map((msg) => ({
      key: `t-${msg.id}`,
      source: "ticket" as const,
      msg,
    })),
    ...ewMessages.map((msg) => ({
      key: `ew-${msg.id}`,
      source: "ew" as const,
      msg,
    })),
  ].sort((a, b) =>
    a.msg.created_at < b.msg.created_at
      ? -1
      : a.msg.created_at > b.msg.created_at
        ? 1
        : 0,
  );

  // W22 §5 — the spawn paths append a raw per-line echo to the ticket
  // description ("<label> × <qty>", `proposal_tickets._line_label`).
  // The Agreement card owns the lines now (rule 7), so the header shows
  // the human half of the description and drops the machine lines. The
  // customer-visible explanations the spawn also appends do not match
  // the pattern and stay. Non-EW tickets render their description
  // untouched.
  const headerDescription = ticket.extra_work_origin
    ? ticket.description
        .split("\n")
        .filter((line) => !/^.+ × \d+([.,]\d+)?$/.test(line.trim()))
        .join("\n")
        .trim()
    : ticket.description;

  /* W-TABS Task 4 — which tabs exist for THIS viewer on THIS ticket.
     Money is a property of the ticket (an extra-work origin) AND the
     role (provider management with extra-work access) — for everyone
     else the tab is ABSENT, not empty. The other four hold content for
     every role: their inner blocks keep their own gates. */
  const moneyTabVisible =
    Boolean(ticket.extra_work_origin) &&
    isProviderManagementRole(me?.role) &&
    canAccessExtraWork(me?.role);
  const visibleTicketTabs = TICKET_TABS.filter(
    (key) => key !== "money" || moneyTabVisible,
  );
  const ticketTab: TicketTab = visibleTicketTabs.includes(
    requestedTicketTab,
  )
    ? requestedTicketTab
    : "overview";

  return (
    <div>
      <div className="detail-header">
        <div className="detail-header-top">
          <Link {...backToTickets} className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {backToTicketsLabel}
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
          {/* W-PLAN2 Task 3 — the Plan action is ALWAYS in reach on
              One-off work: header-level, beside the primary action,
              rendered whichever pill tab is active. Same predicate,
              same modal, same handler as the Plan tab's card. */}
          {ticket.extra_work_origin &&
            isProviderManagementRole(me?.role) &&
            canAccessExtraWork(me?.role) && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void openEwPlan()}
                disabled={ewPlanLoading}
                data-testid="ticket-ew-plan-open"
              >
                {ewPlanLoading ? t("ew_plan_loading") : t("ew_plan_button")}
              </button>
            )}
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
          {/* W-H §1 — "I put a button saying my job on this ticket is
              finished." On a finished ticket this is the only thing
              left to do, so it is the primary. */}
          {canArchive && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setArchiveMode("archive")}
              data-testid="ticket-archive-button"
            >
              <Archive size={14} strokeWidth={2.2} aria-hidden="true" />
              <span style={{ marginLeft: 6 }}>{t("common:archive.button")}</span>
            </button>
          )}
          {/* A STATE IS A SENTENCE ABOUT THE WORK, A BUTTON IS A VERB
              (rule 5): the chip says it is archived and by whom, the
              button says what pressing it does. Never the same words. */}
          {isArchived && (
            <span className="cell-tag" data-testid="ticket-archived-badge">
              {ticket?.archived_by_name
                ? t("common:archive.by", {
                    who: ticket.archived_by_name,
                    when: formatDate(ticket.archived_at ?? null),
                  })
                : t("common:archive.badge")}
            </span>
          )}
          {canUnarchive && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setArchiveMode("unarchive")}
              data-testid="ticket-unarchive-button"
            >
              {t("common:archive.unarchive_button")}
            </button>
          )}
        </div>
        {/* Sprint 191 §1 — the header is a BAND: title on the left,
            Location and Customer on the right, directly under the
            Convert-to-Extra-Work button and in the same horizontal row
            as the title.

            Sprint 189 built this as a card in the right column and
            Sprint 190 moved that card up one slot. Both were wrong in
            the same way — the owner asked for header text twice and got
            a card twice. It is plain text here: no border, no surface,
            no shadow, nothing that reads as a panel.

            The block is NOT conditional on `canConvertTicket`. When
            that button is absent the row above simply holds the back
            link and everything settles upward; no space is reserved and
            nothing disappears. */}
        <div className="detail-header-band">
          <div className="detail-header-band-main">
        {/* W14 §1 — THE STATUS IS NOT A CHIP IN THIS ROW ANY MORE.
            It was an 11px badge third in a line of three, above a 36px
            title, and the owner opened a ticket that was sitting at
            "waiting for the customer", read none of it, and met a big
            Approve button. It now has its own block at the head of the
            band (see `.detail-header-status` below), where it is read
            before the buttons in the side column underneath it. This
            row keeps the two facts that were never in question: which
            ticket this is, and how urgent it is. */}
        <div className="detail-header-meta">
          <span className="detail-header-no">{ticket.ticket_no}</span>
          <span className={`badge badge-${ticket.priority.toLowerCase()}`}>
            {priorityLabelLong(ticket.priority)}
          </span>
        </div>
        <h1 className="detail-header-title">{ticket.title}</h1>
        {headerDescription && (
          <p className="detail-header-desc">{headerDescription}</p>
        )}
        {/* Sprint 28 Batch 15.4 — spawned-from-EW anchor. Renders only
            when the backend includes `extra_work_origin` (non-null
            for tickets created by an ExtraWorkRequest line). Mirrors
            the RouteBadge so operators can tell at a glance whether
            the parent EW skipped or went through the proposal phase.
            W21 — NO DOOR BACK. W18's "Request & proposal" link (and
            its `?full=1` escape) is gone with the escape itself: for a
            provider the request page no longer exists once work is
            spawned, and everything it held lives in the Agreement and
            Extra work cards on THIS page. The origin is a fact, so it
            stays — as text.
            W22 §5 — the title is gone too: a spawned ticket carries its
            parent's title as its OWN heading two lines up, and a line
            that repeats the h1 verbatim says nothing (rule 8). The
            label and the route badge are the two facts the heading does
            not already state. */}
        {ticket.extra_work_origin && (
          <div
            className="ticket-extra-work-origin"
            data-testid="ticket-extra-work-origin"
            data-origin={ticket.extra_work_origin.origin}
          >
            <span className="muted small">
              {t("detail.spawned_from_label")}
            </span>{" "}
            <RouteBadge value={ticket.extra_work_origin.origin} />
          </div>
        )}

        {/* W6-H — MY PLANNED DAYS.
            The worker's answer to "which days am I on this job, and for
            how many hours". It lives here because a worker cannot open
            the parent Extra Work at all (scope_extra_work_for returns
            none() for STAFF, the P0 staff-privacy fix), so the ticket is
            the surface they already use.

            The caller's OWN rows and nobody else's — the server filters
            by the requesting user, so this is not a crew roster and
            carries no other person's name and no money. Rendered only
            when there is something to say. */}
        {(ticket.extra_work_origin?.my_planned_hours?.length ?? 0) > 0 && (
          <div
            className="ticket-my-planned-hours"
            data-testid="ticket-my-planned-hours"
          >
            <span className="muted small">
              {t("detail.my_planned_days_label")}
            </span>{" "}
            {ticket.extra_work_origin?.my_planned_hours?.map((row) => (
              <span
                key={row.date ?? "none"}
                className="ticket-my-planned-day"
                data-testid="ticket-my-planned-day"
                data-date={row.date ?? ""}
              >
                {/* No day yet is a REAL state, not a blank. It is what
                    every plan said before days existed. */}
                {row.date ?? t("detail.my_planned_no_day")}
                {": "}
                <strong>
                  {t("detail.my_planned_hours_value", { hours: row.hours })}
                </strong>
              </span>
            ))}
          </div>
        )}
          </div>{/* end .detail-header-band-main */}

          {/* W14 §1 — the right of the band is now THREE facts in one
              row, in the order somebody actually needs them: what state
              this job is in, where it is, who it is for.

              The owner asked for the status "left of the Location /
              Customer block", and that is what this is. It is also the
              reading order that fixes the mistake he made: the side
              column with the transition buttons starts directly under
              this block, so the state is passed over on the way to the
              button, not after it. Same plain-text treatment as the
              pair beside it — no border, no surface, no panel. */}
          <div className="detail-header-aside">
          <div
            className="detail-header-status"
            data-testid="ticket-header-status"
            data-status={ticket.status}
          >
            <span className="detail-header-status-label">
              <Activity size={10} strokeWidth={2.6} aria-hidden="true" />
              {t("workflow_current_status_label")}
            </span>
            <span className="detail-header-status-value">
              {/* The tone lives in the dot, not in the word: the dot
                  colours are the same tokens `.workflow-current-status`
                  uses, and every status has one (the `.badge-*` family
                  has no rule for WAITING_MANAGER_REVIEW or
                  CONVERTED_TO_EXTRA_WORK and would render those two
                  invisible). */}
              <span className="detail-header-status-dot" aria-hidden="true" />
              <span data-testid="ticket-header-status-text">
                {tStatus(ticket.status)}
              </span>
            </span>
            {/* A STATE IS A SENTENCE ABOUT THE WORK (rule 5). The name
                above is what the system files it under; this is what is
                true of the job right now, and it is the half that
                answers "why is there an Approve button on my screen".
                Same string the Workflow card prints when a role has no
                buttons — one vocabulary, one owner. */}
            <span
              className="detail-header-status-sentence"
              data-testid="ticket-header-status-sentence"
            >
              {t(`workflow_state.${ticket.status}`)}
            </span>
          </div>

          {/* WHERE the work is and WHO it is for. Still ALSO rendered
              inside the Ticket details card below — this is an added
              display, not a move, and that has been right since Sprint
              189. */}
          <div
            className="detail-header-place"
            data-testid="ticket-header-place"
          >
            {/* W4-M §1 — same two facts, one type step down and with a
                micro-icon on each label. The owner asked for "smaller
                and nicer" after Sprint 191 landed the placement. It is
                still PLAIN TEXT: no wrapper, no surface, no border, no
                shadow — the craft is in the type scale and the icons,
                not in a panel. */}
            <div className="detail-header-place-item">
              <span className="detail-header-place-label">
                <MapPin size={10} strokeWidth={2.6} aria-hidden="true" />
                {t("details_location")}
              </span>
              <span
                className="detail-header-place-value"
                data-testid="ticket-header-location"
              >
                {ticket.room_label || ticket.building_name}
              </span>
              {/* A room label alone loses the building it sits in; the
                  building stays underneath it whenever both exist. */}
              {ticket.room_label && ticket.building_name && (
                <span className="detail-header-place-sub">
                  {ticket.building_name}
                </span>
              )}
            </div>
            <div className="detail-header-place-item">
              <span className="detail-header-place-label">
                <Users size={10} strokeWidth={2.6} aria-hidden="true" />
                {t("details_customer")}
              </span>
              <span
                className="detail-header-place-value"
                data-testid="ticket-header-customer"
              >
                {ticket.customer_name}
              </span>
            </div>
          </div>
          </div>{/* end .detail-header-aside */}
        </div>{/* end .detail-header-band */}
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {/* W-TABS Task 4 — the pill bar, the EW page's exact classes. */}
      <div
        className="composer-toggle ew-detail-tabs"
        role="tablist"
        aria-label={t("tabs_aria")}
      >
        {visibleTicketTabs.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={ticketTab === key}
            className={`composer-toggle-btn ${
              ticketTab === key ? "active" : ""
            }`}
            onClick={() => setTicketTab(key)}
            data-testid={`ticket-tab-${key}`}
          >
            {t(`tab_${key}`)}
          </button>
        ))}
      </div>

      <div
        className={
          ticketTab === "overview"
            ? "detail-grid"
            : "detail-grid tk-tabs-stack"
        }
      >
        <div className="detail-main">
          {ticketTab === "messages" && (
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
                  {/* M1 B5 — the "Private" (RESTRICTED) toggle renders only
                      where the author may restrict: provider mgmt / SA on any
                      tier, customer-side ONLY on CUSTOMER_INTERNAL. STAFF have
                      an empty picker so this whole block is already hidden. */}
                  {canUsePrivate && (
                    <>
                      <label className="composer-private-toggle">
                        <Toggle
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
                    </>
                  )}
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
              {actionErrorNode("message", "ticket-message-error")}
            </form>

            {jobThread.length === 0 ? (
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
              jobThread.map(({ key, source, msg: item }) => (
                <div
                  key={key}
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
                      {source === "ew" && (
                        <span
                          className="note-bubble-tag"
                          data-testid="note-ew-chip"
                        >
                          {t("ew_thread_chip")}
                        </span>
                      )}
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

          )}
          {ticketTab === "overview" && (
          <>
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

            {/* W4-M §4a — THE PER-WORK PHOTO SETTING.

                The field and its endpoint shipped in Sprint 191 §2.5 with
                no UI anywhere; this is the mount point. It belongs on the
                attachments card because that is where the photos are —
                a manager deciding what the customer sees is looking at
                this list when the question comes up.

                Two things the copy has to carry and does:
                  - the SCOPE is this job, not this worker and not every
                    job. It is in the label, not in a tooltip;
                  - it changes what happens NEXT. A manager who believes
                    the switch releases yesterday's photos is wrong in a
                    way the customer finds out about, so the caption says
                    so under both states.

                PA / SA only, matching the endpoint's own gate. On a
                terminal ticket the endpoint 400s, so the switch is
                disabled and says why rather than offering a click that
                cannot land. */}
            {isProviderAdmin(me?.role) && (
              <div
                className="photo-policy"
                data-testid="ticket-photo-policy"
                data-enabled={
                  ticket.staff_uploads_customer_visible ? "true" : "false"
                }
              >
                <div className="photo-policy-row">
                  <Toggle
                    id="ticket-photo-policy-toggle"
                    checked={ticket.staff_uploads_customer_visible}
                    onChange={(event) =>
                      void setPhotoVisibilityPolicy(event.target.checked)
                    }
                    disabled={
                      photoPolicyBusy ||
                      PHOTO_POLICY_TERMINAL_STATUSES.has(ticket.status)
                    }
                    data-testid="ticket-photo-policy-toggle"
                  />
                  <label
                    className="photo-policy-label"
                    htmlFor="ticket-photo-policy-toggle"
                  >
                    {t("photo_policy_label")}
                  </label>
                </div>
                {/* W-T3 §3 — two explanatory paragraphs deleted. One
                    restated the switch's own label back at the reader
                    ("On: a photo ... is visible to the customer"); the
                    other explained that the setting is forward-only.
                    That second fact is worth saying, but at the moment
                    it matters rather than permanently above the
                    control: the success toast already carries it
                    (`photo_policy_toast_scope`, "Applies to uploads
                    from now on, on this job only"). Flipping the switch
                    gains no confirm dialog here, so per the treatment
                    the prose is deleted rather than moved into one.
                    The terminal-status line below survives — it is a
                    one-line STATE, not an explanation. */}
                {actionErrorNode(
                  "photo_policy",
                  "ticket-photo-policy-error",
                )}
                {PHOTO_POLICY_TERMINAL_STATUSES.has(ticket.status) && (
                  <p
                    className="photo-policy-help"
                    data-testid="ticket-photo-policy-terminal"
                  >
                    {t("photo_policy_help_terminal")}
                  </p>
                )}
              </div>
            )}

            {/* W-T3 §1 — a failed download names itself above the
                grid it came from, not at the top of the page. */}
            {actionErrorNode("download", "ticket-download-error")}
            <div className="att-thumb-grid">
              {attachments.map((item) => (
                <div className="att-thumb" key={item.id}>
                  {/* RF-5 — the tile opens the in-app preview; the file type
                      is shown up-front via the extension badge (no click
                      needed). A separate Download action stays available on
                      every tile. */}
                  <button
                    type="button"
                    className={`att-thumb-tile ${item.is_hidden ? "internal" : ""}`}
                    onClick={() => openAttachmentPreview(item)}
                    aria-label={t("preview_file_aria", {
                      name: item.original_filename,
                    })}
                    data-testid="attachment-preview-open"
                  >
                    {/* RF-12 — real preview with no click: image cards render
                        the image, PDFs a first-page thumbnail; the extension
                        badge is the graceful fallback. */}
                    <AttachmentThumb
                      ticketId={id ?? ""}
                      attachment={item}
                      fallback={
                        <span className="att-thumb-ext">
                          {getFileExtension(item.original_filename)}
                        </span>
                      }
                    />
                    {item.is_hidden && (
                      <span className="att-thumb-internal-pill">
                        {t("internal_pill")}
                      </span>
                    )}
                  </button>
                  <div className="att-thumb-name">{item.original_filename}</div>
                  <div className="att-thumb-meta-row">
                    <span className="att-thumb-size">
                      {formatBytes(item.file_size)} ·{" "}
                      {formatDate(item.created_at)}
                    </span>
                    <button
                      type="button"
                      className="att-thumb-download"
                      onClick={() => downloadAttachment(item)}
                      disabled={downloadingAttachmentId === item.id}
                      aria-label={t("download_file_aria", {
                        name: item.original_filename,
                      })}
                      title={t("download")}
                    >
                      {downloadingAttachmentId === item.id ? (
                        <span className="att-thumb-download-busy">
                          {t("downloading")}
                        </span>
                      ) : (
                        <Download size={13} strokeWidth={2.2} />
                      )}
                    </button>
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
                {actionErrorNode("attachment", "ticket-attachment-error")}
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
                      <Toggle
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

          <div
            className="card"
            ref={activityCardRef}
            data-testid="ticket-activity-card"
          >
            {/* RF-4 (Ramazan 2026-06-23) — the audit timeline is valuable but
                should not dominate the page at first glance. It now lives in a
                drawer collapsed by default: the header IS the toggle; the
                timeline body is revealed on demand ("at a glance minimal,
                depth behind a click"). */}
            <button
              type="button"
              className="card-head-icon card-head-toggle"
              aria-expanded={activityOpen}
              aria-controls="ticket-activity-body"
              onClick={() => setActivityOpen((open) => !open)}
              data-testid="ticket-activity-toggle"
            >
              <span className="card-head-icon-glyph">
                <Clock size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_activity_title")}
              </span>
              <span className="card-head-icon-spacer" />
              <span className="card-head-icon-link">
                {activityOpen ? t("activity_hide") : t("activity_show")}
              </span>
              <span className="card-head-icon-chevron" aria-hidden="true">
                {activityOpen ? (
                  <ChevronDown size={16} strokeWidth={2.2} />
                ) : (
                  <ChevronRight size={16} strokeWidth={2.2} />
                )}
              </span>
            </button>
            {activityOpen && (
              <div id="ticket-activity-body">
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
                <UnifiedTimeline
                  rows={
                    showSystemEvents
                      ? auditTimeline.rows
                      : auditTimeline.rows.filter(
                          (row) => !isLowSignalAuditRow(row),
                        )
                  }
                />
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
                        {/* Sprint 180 §1 — a status-history row with no
                            `changed_by` is a SYSTEM transition (today,
                            the customer-approval auto-close). Falling
                            through to the generic "unassigned" label
                            would read as "Unassigned closed the
                            ticket": it names nobody and still implies
                            somebody. */}
                        <b>
                          {entry.changed_by_email
                            ? humanName(
                                entry.changed_by_email,
                                t("unassigned"),
                              )
                            : t("common:audit_logs.system_actor")}
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
            {/* RF-4 — reveal the condensed low-signal system rows on demand
                (only meaningful on the provider-audit unified timeline; the
                status-history fallback has no such rows). */}
            {isProviderAudit &&
              auditTimeline !== null &&
              auditTimeline.ticketId === ticket.id &&
              (() => {
                const hiddenCount =
                  auditTimeline.rows.filter(isLowSignalAuditRow).length;
                if (hiddenCount === 0) return null;
                return (
                  <div className="activity-system-toggle">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setShowSystemEvents((shown) => !shown)}
                      data-testid="ticket-activity-system-toggle"
                    >
                      {showSystemEvents
                        ? t("activity_hide_system_events")
                        : t("activity_show_system_events", {
                            count: hiddenCount,
                          })}
                    </button>
                  </div>
                );
              })()}
              </div>
            )}
          </div>
          </>
          )}
        </div>

        {/* #109 Part I — key the right column by ticket.id so every
            CollapsibleCard REMOUNTS on navigation. With persistKey
            removed from all of them, local open/closed state cannot
            leak between tickets: each ticket lands on its per-mount
            defaults (Assignment/Details collapsed, Workflow open). */}
        <div className="detail-side" key={`detail-side-${ticket.id}`}>
          {/* Sprint 191 §2 — the right column is five cards:
              Workflow -> Managers -> Assignment -> Scheduling
              -> Ticket details.

              W13-FIX 6a: Managers moved ABOVE Assignment on the owner's
              instruction ("Managers goes above assignment"). Who is
              responsible is read before who is dispatched.

              The Location & Customer CARD that stood here is deleted.
              It was built in Sprint 189 and reordered in Sprint 190; the
              owner wanted that information in the page header both
              times, and it is there now as plain text. Keeping a card
              too would put the same two facts on screen three times.
              This supersedes the orders in
              `docs/planning/ew-gap-closing-plan.md` §2.1 items 4 and 5,
              both updated in the same commit. */}
          {ticketTab === "overview" && (
          <CollapsibleCard
            title={
              canShowCompleteWorkButton
                ? t("card_workflow_title_staff_complete")
                : t("card_workflow_title")
            }
            meta={t(`common:${ticketStatusLabelKey(ticket.status)}`)}
            defaultOpen
            testId="side-card-workflow"
          >
            {/* W10 §3 — FUTURE-DATED WORK IS NOT ACTIVE WORK.
                A job whose planned start is still ahead says so, and
                stops saying it the moment the date arrives. Nothing is
                stored and nothing has to be remembered: this is read
                from `scheduled_start_at`, which already owns when the
                work is due, compared against now. There is no second
                field, no status change, and nobody to move it — "active"
                simply means the planned start has arrived and the job is
                not finished. */}
            {isUpcoming && (
              <p className="workflow-upcoming" data-testid="workflow-upcoming">
                <Clock size={14} strokeWidth={2.4} aria-hidden="true" />
                {t("workflow_upcoming", {
                  when: formatDateTime(ticket.scheduled_start_at as string),
                })}
              </p>
            )}
            {/* W9 §1 — the card carries the colour of WHERE THE JOB IS.
                The owner asked for "more visually informative rather
                than everything being white and green", and the most
                informative colour on this page is the one fact the card
                exists for. The accent reuses the exact status-to-token
                mapping the status dot already uses, so the rail and the
                dot can never disagree, and every value is an existing
                `:root` token. */}
            <div className="workflow-body" data-status={ticket.status}>
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
                      /* Sprint 190 §3 — completing the work IS the
                         forward action for the assigned staffer, and it
                         is the only button they get. */
                      data-tone="advance"
                      data-emphasis="solid"
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
                /* W4-M §2 — the read-only Workflow card.

                   This branch used to print "No status transitions
                   available for your role." A customer opening their own
                   ticket is not a failed provider, and a sentence about
                   what their role cannot do tells them nothing they
                   wanted to know. The sentence is gone. What stands in
                   its place is the one fact the card is for: where this
                   job is right now, and since when.

                   Everyone with no button lands here — a customer on an
                   OPEN job, a manager on a CLOSED one — and everyone
                   gets the status readout. The provider-only reason line
                   underneath is the single exception: it explains why a
                   provider who would normally decide has no button on a
                   WCA ticket, which is information a provider acts on
                   and a customer never sees. */
                <div
                  className="workflow-current-status"
                  data-testid="workflow-current-status"
                  data-status={ticket.status}
                >
                  <span className="workflow-current-status-label">
                    {t("workflow_current_status_label")}
                  </span>
                  <span className="workflow-current-status-value">
                    <span
                      className="workflow-current-status-dot"
                      aria-hidden="true"
                    />
                    {/* W13 §4 — A STATE IS A SENTENCE ABOUT THE WORK.
                        The enum label ("Scheduled, not started") is a
                        filing category; this says what is true of the
                        job right now, which is what somebody arriving
                        at the page is actually asking. */}
                    <span data-testid="workflow-current-status-text">
                      {t(`workflow_state.${ticket.status}`)}
                    </span>
                  </span>
                  {currentStatusSince && (
                    <span
                      className="workflow-current-status-since"
                      data-testid="workflow-current-status-since"
                    >
                      {t("workflow_current_status_since", {
                        when: formatDateTime(currentStatusSince),
                      })}
                    </span>
                  )}
                  {!isCustomerUser(me?.role) &&
                    ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                    ticket.actions?.can_override_customer_decision ===
                      false && (
                      <p
                        className="muted small workflow-current-status-note"
                        data-testid="workflow-wca-no-provider-decision"
                      >
                        {t("workflow_wca_no_provider_decision")}
                      </p>
                    )}
                </div>
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

                  {/* W13 §5 — the paragraph is DELETED, not moved.
                      "Please upload a photo of the completed work if
                      possible..." sat between the status and the
                      buttons, which is where the reader is deciding
                      what to press, not where a photo is wanted. The
                      completion modal already states the same rule at
                      the moment it applies
                      (`ticket_staff_complete.note_label_or_photo` and
                      `note_or_photo_hint`), and the server enforces it
                      there, so this was a third copy of one fact in
                      the place it helped least. */}

                  {/* W5 fix 3 — the billing-cutoff notice, above the
                      customer's approve / reject buttons.

                      Wave 1 built it and mounted it on the invoice list
                      and the melding list, and handed off that it also
                      belongs at the decision itself. This is that
                      placement: the "before" variant answers exactly the
                      question a customer has with these two buttons in
                      front of them — what happens to this work if I do
                      not answer before my billing date. Same rule as the
                      approval e-mail carries, at the moment it applies.

                      Customer-side only, and only on the step where the
                      decision is theirs: a provider driving the same
                      transition under override is not the audience. */}
                  {isCustomerUser(me?.role) &&
                    ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                    (visibleNextStatuses.includes("APPROVED") ||
                      visibleNextStatuses.includes("REJECTED")) && (
                      <BillingCutoffNotice />
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
                    // Sprint 190 §3 — `data-tone` / `data-emphasis` are
                    // emitted ONLY for the primary variant. The
                    // correction actions behind "show correction
                    // actions" stay deliberately colourless: they are
                    // the admin escape hatch, not the step to take, and
                    // that list can contain REJECTED alongside six
                    // forward moves. Leaving the attribute off is what
                    // keeps the tone CSS from ever reaching them —
                    // cleaner than out-specifying it afterwards.
                    //
                    // `emphasis` is the hierarchy: the first forward
                    // action is the solid one. IN_PROGRESS offers two
                    // forward moves (manager review, closed) and two
                    // equally solid green buttons would say they are
                    // equally the next step. PRIMARY_TRANSITIONS already
                    // orders them; this renders that order.
                    // W11 §1 — THE REASON PROMPT BELONGS TO WHICHEVER
                    // BUTTON ASKED FOR IT.
                    //
                    // It rendered under the WCA Approve / Reject pair
                    // and nowhere else, because that pair was the one
                    // case the page armed BEFORE posting. Every other
                    // override arrives the other way round: the click
                    // posts, Sprint 184 §2 refuses it with
                    // `override_reason_required`, and `changeStatus`
                    // arms the very same state — which had nothing on
                    // screen to draw it. So a SUPER_ADMIN pressing the
                    // undo button got no error, no field and no move:
                    // a button that did nothing at all.
                    //
                    // One prompt, rendered under the button that armed
                    // it, whichever button that is. That also retires
                    // the separate override-button renderer, so the
                    // Approve / Reject pair is no longer a second copy
                    // of the transition button kept in step by hand.
                    const submitLabel = (status: TicketStatus): string => {
                      if (isCustomerDecisionOverride(status)) {
                        return status === "APPROVED"
                          ? t("override_modal_submit_approve")
                          : t("override_modal_submit_reject");
                      }
                      return t("override_modal_submit_generic", {
                        status: tStatus(status),
                      });
                    };
                    const renderReasonPrompt = (status: TicketStatus) => (
                      <div
                        className="workflow-override-inline"
                        data-testid="ticket-override-modal"
                      >
                        {/* The sentence that stood here said the move
                            overrides the customer and is recorded in the
                            status history. The submit button says where
                            the ticket goes and that it is an override,
                            and a required Reason field says the rest by
                            existing. It was one fact written twice. */}
                        <form onSubmit={submitOverride}>
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
                              disabled={overrideBusy || !overrideReason.trim()}
                              data-testid="ticket-override-submit"
                            >
                              {overrideBusy
                                ? t("updating")
                                : submitLabel(status)}
                            </button>
                          </div>
                        </form>
                      </div>
                    );
                    let advanceSeen = false;
                    const renderTransitionButton = (
                      status: TicketStatus,
                      variant: "primary" | "secondary" | "correction",
                    ) => {
                      // W9 §2 — a correction carries its OWN tone, so
                      // the amber is a property of what the button does
                      // rather than of which list it sits in.
                      const tone =
                        variant === "correction"
                          ? "correct"
                          : WORKFLOW_TONE[status];
                      let emphasis: "solid" | "outline" = "outline";
                      if (variant === "primary" && tone === "advance") {
                        emphasis = advanceSeen ? "outline" : "solid";
                        advanceSeen = true;
                      }
                      const isArmed = overrideDecision === status;
                      return (
                        <div key={status} className="workflow-override-target">
                          <button
                            type="button"
                            className={
                              variant === "secondary"
                                ? "status-btn status-btn-secondary"
                                : "status-btn"
                            }
                            data-tone={
                              variant === "secondary" ? undefined : tone
                            }
                            data-emphasis={
                              variant === "primary" ? emphasis : undefined
                            }
                            disabled={
                              statusBusy !== null ||
                              overrideBusy ||
                              evidenceMissing
                            }
                            data-testid={`workflow-move-${status}`}
                            aria-expanded={isArmed || undefined}
                            onClick={() => void openTransition(status)}
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
                                {/* W9 §2 — the WORDING follows the move, not
                                    the list. It reads "Move back to" with a
                                    left arrow wherever it lands; the amber is
                                    what the correction slot adds on top. */}
                                {/* W13 §4 — A BUTTON IS A VERB.
                                    It used to read "Move to <status
                                    name>", so the owner's father met
                                    "Move to Scheduled, not started",
                                    which is neither a state nor an
                                    action. The status name says where
                                    the work IS; the button says what
                                    pressing it DOES, and they are
                                    never the same words.
                                    A correction keeps naming its
                                    destination: undoing is the one case
                                    where "where does this put it back
                                    to" is the question. */}
                                {isCorrection(ticket.status, status)
                                  ? t("workflow_move_back_to", {
                                      status: tStatus(status),
                                    })
                                  : t(`workflow_action.${status}`)}
                                <span className="status-btn-arrow">
                                  {isCorrection(ticket.status, status)
                                    ? "←"
                                    : "→"}
                                </span>
                              </>
                            )}
                          </button>
                          {isArmed && renderReasonPrompt(status)}
                        </div>
                      );
                    };
                    // Sprint 7B (frontend) — NEVER render
                    // CONVERTED_TO_EXTRA_WORK as a raw status-transition
                    // button. That hop would flip the status WITHOUT
                    // creating the ExtraWorkRequest; conversion now runs
                    // through the dedicated convert endpoint + dialog
                    // (the prominent header "Convert to Extra Work"
                    // button). Drop it from both render groups so it can
                    // never POST to /status/.
                    //
                    // W11 §1 — the APPROVED / REJECTED pair is no longer
                    // pulled out of these two lists for a provider on
                    // WAITING_CUSTOMER_APPROVAL. It used to be, so that a
                    // separate renderer could redraw it with the arming
                    // form attached; every transition button now carries
                    // that form, so the pair renders where it belongs —
                    // as the forward action of the step it is on.
                    const primaryForRender = primaryNextStatuses.filter(
                      (s) => s !== "CONVERTED_TO_EXTRA_WORK",
                    );
                    const secondaryForRender = secondaryNextStatuses.filter(
                      (s) => s !== "CONVERTED_TO_EXTRA_WORK",
                    );
                    // W10 §5 — CONTEXTUAL, NOT PERMANENT. The only
                    // correction offered on its own is the one that
                    // undoes the step just taken, and only while the
                    // backend still permits it.
                    //
                    // W11 §1 — and only when that step went FORWARD.
                    // `isCorrection` is what says so: it compares where
                    // the ticket came from against where it stands, so
                    // an undo that has itself just been undone offers no
                    // second undo. There is nothing left to take back.
                    const correctionTarget =
                      previousStatus !== null &&
                      previousStatus !== ticket.status &&
                      // `some`, not `includes`: `secondaryForRender` is
                      // narrowed by its own filter and would refuse the
                      // full union as an argument. A cast would silence
                      // that rather than answer it.
                      secondaryForRender.some((st) => st === previousStatus) &&
                      isCorrection(ticket.status, previousStatus)
                        ? previousStatus
                        : null;
                    const correctionForRender =
                      correctionTarget === null ? [] : [correctionTarget];
                    const otherSecondaryForRender = secondaryForRender.filter(
                      (st) => st !== correctionTarget,
                    );
                    return (
                      <>
                        {primaryForRender.length > 0 && (
                          <div className="status-actions">
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
                        {/* W9 §2 — THE UNDO IS VISIBLE, AND IT IS
                            SEPARATE. Its buttons carry
                            `data-tone="correct"` — an amber outline that
                            belongs to no forward action on the card, so
                            muscle memory aimed at the green button
                            cannot land here. */}
                        {correctionForRender.length > 0 && (
                          <div
                            className="workflow-correction-group"
                            data-testid="workflow-correction-group"
                          >
                            <div className="workflow-correction-head">
                              <Undo2 size={13} strokeWidth={2.4} aria-hidden="true" />
                              {t("workflow_correction_heading")}
                            </div>
                            {correctionForRender.map((status) =>
                              renderTransitionButton(status, "correction"),
                            )}
                          </div>
                        )}
                        {/* W11 §1 — EVERY OTHER BACKWARD OR SIDEWAYS
                            MOVE THE BACKEND PERMITS, BEHIND A CLOSED
                            DOOR, AND NOT BUILT UNTIL THE DOOR OPENS.
                            The list is not hidden with CSS: collapsed,
                            it does not exist in the document. A
                            SUPER_ADMIN's is every remaining status, and
                            seven ways to hand-type a ticket somewhere
                            else is not what the card is for.
                            The toggle itself is absent when the list
                            behind it is empty — a customer with one
                            decision to make is never shown a door onto
                            nothing. */}
                        {otherSecondaryForRender.length > 0 && (
                          <div className="workflow-corrections">
                            <button
                              type="button"
                              className="workflow-corrections-toggle"
                              aria-expanded={correctionsOpen}
                              onClick={() => {
                                // Closing the door takes the half-typed
                                // reason with it. Leaving an armed
                                // prompt alive behind a collapsed list
                                // would mean a target the operator can
                                // no longer see is still the one a
                                // submit would send.
                                if (correctionsOpen) cancelOverride();
                                setCorrectionsOpenFor(
                                  correctionsOpen ? null : (id ?? null),
                                );
                              }}
                              data-testid="workflow-corrections-toggle"
                            >
                              {correctionsOpen ? (
                                <ChevronDown
                                  size={13}
                                  strokeWidth={2.6}
                                  aria-hidden="true"
                                />
                              ) : (
                                <ChevronRight
                                  size={13}
                                  strokeWidth={2.6}
                                  aria-hidden="true"
                                />
                              )}
                              {correctionsOpen
                                ? t("workflow_corrections_hide")
                                : t("workflow_corrections_show")}
                            </button>
                            {correctionsOpen && (
                              <div
                                className="workflow-secondary-list"
                                data-testid="workflow-secondary-list"
                              >
                                {otherSecondaryForRender.map((status) =>
                                  renderTransitionButton(status, "secondary"),
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    );
                  })()}
                </>
              )}
            </div>
          </CollapsibleCard>

          )}
          {ticketTab === "people" && (
          <>
          {/* #7 Part B — Responsible managers (M:N), distinct from the
              primary "Assigned" field in the Assignment card BELOW.
              Self-gates to provider-management roles and hides on a LIST
              403. onChanged reloads the ticket so the activity timeline
              picks up the audit row. */}
          <ResponsibleManagersSection
            key={ticket.id}
            ticketId={ticket.id}
            canManage={isStaff}
            assignableManagers={assignableManagers}
            onChanged={() => {
              void loadTicket();
            }}
          />

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
          {/* #109 Part I — right-column cards default COLLAPSED per
              mount (no persistKey; the ticket-keyed wrapper above
              remounts them so nothing leaks across tickets). */}
          <CollapsibleCard
            title={t("card_assignment_title")}
            meta={t("side_summary_assignment", {
              count: ticket.assigned_staff?.length ?? 0,
            })}
            // W-PLAN2 Task 2 — open by default; only Details and the
            // Activity drawer stay collapsed.
            defaultOpen
            testId="side-card-assignment"
          >

            {/* W13 — the second manager control is GONE.

                This subsection was a dropdown writing `ticket.assigned_to`
                (the "head manager"), sitting directly above a separate
                "Responsible managers" card writing the M:N. The owner:
                "Why is there a head manager AND a responsible manager?
                There is no permission difference. It is cosmetic."
                Verified before removing -- neither field appears in
                `accounts/scoping.py`, eligibility for both is identical,
                and `TicketFilter.my_managed` is already their union. One
                Managers section now, and it is the one that can hold more
                than one person. */}
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
            {/* W14 — for a PROVIDER MANAGER this heading and the list
                under it are gone. They render the same people as the
                assignment table below, one card apart, under a second
                name -- two of the four headings the owner counted for
                the single idea "put people on this job". The card's own
                title is the name now, and the table below is the list.

                Customer-side and STAFF viewers keep it: it is the ONLY
                staffing surface they have (they never get the manager
                section), it is the one that carries the anonymised
                "{{company}} staff" entry and the resolver-gated
                credential summaries, and it is read-only for them. */}
            <div
              data-testid="assigned-staff-card"
              style={
                isStaff
                  ? undefined
                  : {
                      marginTop: 14,
                      paddingTop: 14,
                      borderTop: "1px solid var(--border)",
                    }
              }
            >
              {!isStaff && (
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
              )}
              <div className="assign-body">
              {isStaff ? null : ticket.assigned_staff.length === 0 ? (
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
                            {/* W-N1 §4 — a redacted team member still
                                says what they are QUALIFIED for. The
                                types only, joined with the same middot
                                the named row uses for its own meta line:
                                a certificate is a fact about the work,
                                not about the person, so it survives the
                                redaction that removes their name. The
                                server decides which ones appear — this
                                renders whatever came back and asks no
                                questions of its own. */}
                            {(entry.credentials ?? []).length > 0 && (
                              <span
                                className="muted small"
                                style={{ fontSize: 11 }}
                                data-testid="assigned-staff-anon-credentials"
                              >
                                {(entry.credentials ?? [])
                                  .map((credential) =>
                                    tCred(`type.${credential.type}`),
                                  )
                                  .join(" · ")}
                              </span>
                            )}
                          </div>
                        </li>
                      );
                    }
                    const named = entry as AssignedStaffNamedEntry;
                    const displayName =
                      named.full_name ||
                      (named.email ? named.email.split("@")[0] : "—");
                    // M2 P5 — resolver-gated credential / property
                    // summaries. Present ONLY for CUSTOMER_USER viewers
                    // with per-customer grants; provider viewers (and
                    // ungranted customers) get no arrays and render a
                    // byte-identical block.
                    const credentials = named.credentials ?? [];
                    const properties = named.properties ?? [];
                    const hasShared =
                      credentials.length > 0 || properties.length > 0;
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
                          {hasShared && (
                            <div
                              data-testid="assigned-staff-credentials"
                              style={{
                                marginTop: 6,
                                display: "flex",
                                flexDirection: "column",
                                gap: 4,
                              }}
                            >
                              {credentials.length > 0 && (
                                <span
                                  className="muted small"
                                  style={{
                                    fontSize: 10,
                                    textTransform: "uppercase",
                                    letterSpacing: 0.4,
                                  }}
                                >
                                  {tCred("customer.credentials_title")}
                                </span>
                              )}
                              {credentials.map((credential, credIndex) => (
                                <div
                                  key={`cred-${credIndex}`}
                                  className="muted small"
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    flexWrap: "wrap",
                                  }}
                                  data-testid="assigned-staff-credential-row"
                                >
                                  <span style={{ fontWeight: 600 }}>
                                    {tCred(`type.${credential.type}`)}
                                  </span>
                                  {credential.permit_number && (
                                    <span>{credential.permit_number}</span>
                                  )}
                                  {credential.expiry_date && (
                                    <span>
                                      {tCred("customer.expires_label", {
                                        date: credential.expiry_date,
                                      })}
                                    </span>
                                  )}
                                  {/* W-UX1-B — LOOK, DO NOT KEEP. The
                                      document opens in the app's own
                                      preview with `withDownload={false}`,
                                      the same shape the invoice preview
                                      uses; there is no download anywhere
                                      on this block any more, for the
                                      customer view or the provider one.

                                      The URL's AUTHORIZATION is
                                      untouched and deliberately so:
                                      `credential_document_visible_to_user`
                                      (accounts/visibility.py:160) stays
                                      the only gate, it is strictly
                                      narrower than field visibility, and
                                      a credential whose fields are
                                      visible can still have no
                                      `document_url` at all. Showing a
                                      document in a viewer instead of a
                                      file changes what the browser does
                                      with the bytes, not who may fetch
                                      them. */}
                                  {credential.document_url && (
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-sm"
                                      style={{ padding: "1px 6px", fontSize: 11 }}
                                      onClick={() =>
                                        openDocumentPreview(
                                          credential.document_url ?? "",
                                          `${credential.type.toLowerCase()}.pdf`,
                                        )
                                      }
                                      data-testid="assigned-staff-credential-preview"
                                    >
                                      <Eye size={12} strokeWidth={2} />
                                      {tCred("customer.view_document")}
                                    </button>
                                  )}
                                </div>
                              ))}
                              {properties.length > 0 && (
                                <span
                                  className="muted small"
                                  style={{
                                    fontSize: 10,
                                    textTransform: "uppercase",
                                    letterSpacing: 0.4,
                                    marginTop: credentials.length > 0 ? 4 : 0,
                                  }}
                                >
                                  {tCred("customer.properties_title")}
                                </span>
                              )}
                              {properties.map((property, propIndex) => (
                                <div
                                  key={`prop-${propIndex}`}
                                  className="muted small"
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    flexWrap: "wrap",
                                  }}
                                  data-testid="assigned-staff-property-row"
                                >
                                  <span style={{ fontWeight: 600 }}>
                                    {property.name}:
                                  </span>
                                  <span>{property.value}</span>
                                  {/* W-UX1-B — the properties block is the
                                      credential block's sibling: same
                                      row, same handler, same key. Left
                                      as a download it would sit beside a
                                      credential that only previews, and
                                      the shared i18n key could not be
                                      retired. Same dialog, same
                                      `withDownload={false}`. */}
                                  {property.document_url && (
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-sm"
                                      style={{ padding: "1px 6px", fontSize: 11 }}
                                      onClick={() =>
                                        openDocumentPreview(
                                          property.document_url ?? "",
                                          `${property.name}.pdf`,
                                        )
                                      }
                                      data-testid="assigned-staff-property-preview"
                                    >
                                      <Eye size={12} strokeWidth={2} />
                                      {tCred("customer.view_document")}
                                    </button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}

              {/* W14 — ONE named thing, ONE table, ONE button. The
                  read-only staff list ABOVE is hidden for this viewer
                  (see there): it and this table are the same people, and
                  the owner counted the duplicate as one of the four
                  headings he was reading for a single idea. */}
              {isStaff && (
                <StaffAssignmentSection
                  // Key by ticket id so the section REMOUNTS on an A->B
                  // ticket change and its useState(autoCompleteOnSubtasks)-
                  // seeded autoFlag re-seeds from the new ticket. A
                  // same-ticket reload keeps the key, so local state is
                  // correctly preserved.
                  key={ticket.id}
                  ticketId={ticket.id}
                  onChanged={() => {
                    void loadTicket();
                  }}
                  autoCompleteOnSubtasks={ticket.auto_complete_on_subtasks}
                  canSetAutoCompleteFlag={isProviderAdmin(me?.role)}
                  ticketStatus={ticket.status}
                  customerWantedDate={ticket.customer_wanted_date}
                  credentialsByUserId={credentialsByUserId}
                  reloadNonce={assignmentReloadNonce}
                  onPreviewDocument={(url, filename) =>
                    openDocumentPreview(url, filename)
                  }
                />
              )}

              {/* W4-M §4b — PER-TICKET PHOTO PERMISSION, per assigned
                  person.

                  There are TWO controls in this product that decide
                  whether a named person's photos reach the customer, and
                  the owner asked in as many words that a manager never
                  has to guess which one they just flipped:

                    * chat P's screen, on the person's own admin page —
                      THIS PERSON, ON EVERY TICKET;
                    * this one — THIS PERSON, ON THIS TICKET ONLY.

                  So the scope is in the heading, in the helper line, in
                  every option label of every row, and in the sentence
                  that points at the other control. It is not in a
                  tooltip, because a tooltip is not read by the person
                  who already thinks they know what the switch does.

                  Three states, not two: "not set" lets the standing
                  permission answer, and it is a different thing from an
                  explicit "no" that overrules the standing permission
                  here. A toggle cannot say that. */}
              {uploadGrants !== null && uploadGrants.people.length > 0 && (
                <div
                  className="upload-grants"
                  data-testid="ticket-upload-grants"
                >
                  <div
                    className="upload-grants-heading"
                    data-testid="ticket-upload-grants-heading"
                  >
                    {t("upload_grant_section_heading")}
                  </div>
                  {/* W-T3 §3 — three sentences of explanation
                      deleted; the heading and each row's state say it. */}
                  <BoundedList
                    size="sm"
                    count={uploadGrants.people.length}
                    ariaLabel={t("upload_grant_section_heading")}
                    testIdPrefix="ticket-upload-grants"
                  >
                    <ul className="upload-grants-list">
                      {uploadGrants.people.map((person) => {
                        const displayName =
                          person.user_full_name?.trim() ||
                          person.user_email.split("@")[0];
                        const visible =
                          person.effective_visibility === "CUSTOMER";
                        return (
                          <li
                            key={person.user_id}
                            className="upload-grants-row"
                            /* W-FIX5 — ONE COMPACT ROW: name, then a
                               short select, side by side. The class in
                               index.css stacks them in a column and
                               stretches the select to 100%, which is
                               what made a long label truncate; that file
                               is not this wave's, so the row is turned
                               horizontal here. Inline beats the class on
                               specificity and touches nothing else that
                               uses it. */
                            style={{
                              flexDirection: "row",
                              alignItems: "center",
                              flexWrap: "wrap",
                              gap: 10,
                            }}
                            data-testid="ticket-upload-grant-row"
                            data-user-id={person.user_id}
                            data-effective={person.effective_visibility}
                          >
                            <span className="upload-grants-name">
                              {displayName}
                            </span>
                            {/* W-T3 §1 — this row's own failure. The
                                list can be long, so a refusal reported
                                at the top of the page belonged to no
                                visible person. */}
                            {actionErrorNode(
                              `grant:${person.user_id}`,
                              "ticket-upload-grant-error",
                            )}
                            <select
                              className="field-input upload-grants-select"
                              /* Auto width, capped. With the labels
                                 shortened it no longer needs the full
                                 row to show its longest option. */
                              style={{ width: "auto", maxWidth: 260 }}
                              aria-label={t("upload_grant_select_aria", {
                                name: displayName,
                              })}
                              value={grantChoiceOf(
                                person.uploads_customer_visible,
                              )}
                              disabled={
                                uploadGrantBusyUserId === person.user_id
                              }
                              onChange={(event) =>
                                void setUploadGrant(
                                  person.user_id,
                                  event.target.value as UploadGrantChoice,
                                )
                              }
                              data-testid="ticket-upload-grant-select"
                            >
                              <option value="INHERIT">
                                {t("upload_grant_choice_inherit")}
                              </option>
                              <option value="GRANT">
                                {t("upload_grant_choice_grant")}
                              </option>
                              <option value="REFUSE">
                                {t("upload_grant_choice_refuse")}
                              </option>
                            </select>
                            {/* W-FIX5 — AT MOST ONE LINE, and only when
                                there is something to say. The row used
                                to carry two sentences on every person:
                                what happens next, and which rule decided
                                it. The default is internal, so "Next
                                photo: internal. Nobody has decided, so
                                it stays internal." was two sentences
                                announcing that nothing had happened.
                                The line now appears only when the
                                outcome DIFFERS from that default. */}
                            {visible && (
                              <span
                                className="upload-grants-effect"
                                data-testid="ticket-upload-grant-effect"
                              >
                                {t("upload_grant_state_customer")}
                              </span>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </BoundedList>
                </div>
              )}


              {/* Sprint 5 — read-only sub-tasks for NON-manager viewers.
                  STAFF (provider-side) see full detail; customer-side
                  viewers get a PII-safe summary (no staff identity/notes).
                  Only renders once a manager has created sub-tasks, so a
                  ticket with none is unchanged for these roles.

                  NOTE the flag's name: `isStaff` is
                  `isProviderManagementRole` (SA/CA/BM). This branch
                  therefore excludes MANAGERS -- who get
                  `StaffAssignmentSection` instead -- and not STAFF. A
                  CUSTOMER_USER reaches it but never renders, because
                  `sub_tasks` is emptied for that role server-side
                  (serializers.py:840).

                  W26.4 — a STAFF viewer who is ON one or more parts gets
                  `MyPartsPanel` in its place: their OWN parts, each with
                  the action that finishes it. `MyPartsPanel` returns
                  null when none of the parts are theirs, and the
                  read-only view below is what they fall back to, so a
                  staff member on the job but on no part still sees how
                  the job is split. */}
              {!isStaff && ticket.sub_tasks.length > 0 && (
                myPartCount > 0 ? (
                  <MyPartsPanel
                    ticketId={ticket.id}
                    subTasks={ticket.sub_tasks}
                    myUserId={me?.id ?? -1}
                    autoCompleteOnSubtasks={ticket.auto_complete_on_subtasks}
                    onChanged={() => void loadTicket()}
                  />
                ) : (
                  <SubTaskReadOnly
                    subTasks={ticket.sub_tasks}
                    autoCompleteOnSubtasks={ticket.auto_complete_on_subtasks}
                    showStaffDetails={me?.role === "STAFF"}
                  />
                )
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
          </CollapsibleCard>


          </>
          )}
          {ticketTab === "plan" && (
          <>
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

          {/* W17 §2 — the Extra Work card group, on a ticket born from
              one. PROVIDER-ONLY and the gate sits on the MOUNT, not the
              render: the component's first act is
              `GET /api/extra-work/<id>/`, which is a hard 404 for STAFF
              (`scope_extra_work_for` -> `.none()`), and customers keep
              their existing surfaces (worked hours only on hourly-priced
              work — not widened here). `canAccessExtraWork` is the same
              predicate the nav and ExtraWorkRoute use, so the card and
              the sidebar cannot disagree; the role check on top of it is
              what keeps CUSTOMER_USER (who passes that predicate) out of
              provider money. The origin pill in the header stays the
              door to the full Extra Work page. */}
          {/* W-PLAN Task 2 — the Plan action for One-off work. Same
              viewer gate as the card group below: provider management
              with extra-work access; the dialog itself is mounted at
              the end of the page. */}
          {ticket.extra_work_origin &&
            isProviderManagementRole(me?.role) &&
            canAccessExtraWork(me?.role) && (
              <div className="card" data-testid="ticket-ew-plan-card">
                <div className="form-section">
                  <div className="form-section-title">
                    {t("ew_plan_summary_title")}
                  </div>
                  {ewPlanDetail &&
                  (ewPlanDetail.planned_hours ?? []).length > 0 ? (
                    <ul
                      className="muted small"
                      style={{ margin: "0 0 10px", paddingLeft: 18 }}
                      data-testid="ticket-ew-plan-summary"
                    >
                      {(ewPlanDetail.planned_hours ?? []).map((row, i) => (
                        <li key={i} data-testid="ticket-ew-plan-summary-row">
                          {row.user_full_name || row.user_email}
                          {" \u00b7 "}
                          {row.date ?? t("ew_plan_summary_no_day")}
                          {row.hour_type_name ? ` \u00b7 ${row.hour_type_name}` : ""}
                          {" \u00b7 "}
                          {row.hours}h
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p
                      className="muted small"
                      style={{ marginTop: 0 }}
                      data-testid="ticket-ew-plan-summary-empty"
                    >
                      {t("ew_plan_summary_empty")}
                    </p>
                  )}
                </div>
              </div>
            )}
          </>
          )}
          {ticketTab === "money" &&
            ticket.extra_work_origin &&
            isProviderManagementRole(me?.role) &&
            canAccessExtraWork(me?.role) && (
              <TicketExtraWorkCards
                key={ticket.extra_work_origin.extra_work_request_id}
                extraWorkId={ticket.extra_work_origin.extra_work_request_id}
                currentTicketId={ticket.id}
                onChanged={() => {
                  void loadTicket();
                }}
              />
            )}

          {ticketTab === "overview" && (
          <>
          {/* Sprint 30 Batch 30.1.1 — consolidated Details card. Merges
              the prior Ticket details, Customer Contacts, and SLA cards
              into ONE card with subtle subsection separators. Contacts
              are hidden entirely when the list is empty (no "No
              contacts on file." line). The Delete affordance lives at
              the card footer as a small text link; the confirmation
              dialog is unchanged. */}
          <CollapsibleCard
            title={t("card_details_title")}
            defaultOpen={false}
            testId="side-card-details"
          >
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
                {/* W13 — ONE category row.
                    There were two: `details_category`, which printed the
                    raw `ticket.type` enum value, and a second row for
                    the Sprint 185 work-category catalog. Between them a
                    reader saw the word "category" twice with different
                    vocabularies underneath. `type` is superseded and no
                    longer shown anywhere.

                    Editable in place for provider operators — the
                    dedicated action endpoint, since the ticket viewset
                    has no PATCH — and read-only for everyone else.

                    §4 — this picker offers the WHOLE active catalog,
                    including "Ongegrond", which the create forms leave
                    out. That is not an inconsistency, it is the point:
                    unfounded is a verdict reached by reading the
                    melding, and this is the screen where somebody reads
                    it. */}
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("details_category")}
                  </span>
                  <span className="detail-kv-val">
                    {isProviderManagementRole(me?.role) ? (
                      <>
                      <select
                        className="field-select"
                        value={ticket.category ?? ""}
                        disabled={categoryBusy}
                        data-testid="ticket-detail-category"
                        onChange={(event) => {
                          const raw = event.target.value;
                          void saveCategory(raw === "" ? null : Number(raw));
                        }}
                      >
                        <option value="">
                          {t("common:ticket_categories.none")}
                        </option>
                        {/* An ARCHIVED category stays offerable when the
                            melding already carries it: otherwise opening
                            an old melding and touching anything would
                            silently retag it. */}
                        {categories
                          .filter(
                            (row) =>
                              row.is_active || row.id === ticket.category,
                          )
                          .map((row) => (
                            <option key={row.id} value={row.id}>
                              {row.label}
                            </option>
                          ))}
                      </select>
                      {actionErrorNode("category", "ticket-category-error")}
                      </>
                    ) : (
                      ticket.category_name || "—"
                    )}
                  </span>
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

            {/* W7 DESIGN 2 — ONE statement, then what it is measured
                against.

                What was here: a heading, a coloured pill, the SAME words
                repeated as prose beside the pill, and a four-row
                label/value grid of raw timestamps. Six fragments for one
                idea — the owner's "paragraph wearing chips" — and not
                one of them said where the deadline came from, so there
                was no way to tell whether "1h 37m over" was a scandal or
                a rounding error.

                Now: the sentence ("Late by 1h 37m"), the date it had to
                be done by, and one line of plain English saying how that
                date is worked out. Late is said ONCE, with the amount.

                The timestamps that only meant something to somebody who
                already understood the engine (started at / first
                breached at / paused since) are off the screen. The
                status history below is where this ticket's chronology
                lives and it was already telling that story. */}
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
              </div>
              {/* The deadline as a date a person can put in a diary, and
                  only while there is still one to meet: on a finished
                  ticket the date is history, and repeating it invites
                  the reader to check arithmetic that no longer decides
                  anything. */}
              <p
                className="sla-detail-explainer"
                data-testid="ticket-deadline-basis"
              >
                {ticket.sla_display_state === "HISTORICAL" ||
                !ticket.sla_due_at ? (
                  t("common:sla.no_deadline_explain")
                ) : (
                  /* W-T3 §3 — `sla.basis` deleted: three sentences of
                     working-hours arithmetic that never changed and
                     never decided anything on this page. The DUE DATE
                     is the value and stays. */
                  ticket.sla_display_state !== "COMPLETED" && (
                    <strong className="sla-detail-explainer-due">
                      {t("common:sla.due_on", {
                        when: formatDateTime(ticket.sla_due_at),
                      })}
                    </strong>
                  )
                )}
              </p>
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
          </CollapsibleCard>

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
          </>
          )}
        </div>
      </div>

      {/* Sprint 7B (frontend) — Convert-to-Extra-Work dialog. Posts to
          the dedicated convert endpoint and, on success, navigates to
          the freshly-created ExtraWorkRequest detail page. */}
      {/* W-H §1 — RULE 4: EVERY ACTION ANSWERS. The toast says what
          changed in words ("Archived. It has left the working list."),
          the header chip changes, and the button becomes its opposite.
          A person who presses it is never left wondering what it did. */}
      {archiveMode && ticket && (
        <TicketArchiveDialog
          ticketId={ticket.id}
          mode={archiveMode}
          onCancel={() => setArchiveMode(null)}
          onDone={(updated, mode) => {
            setTicket(updated);
            setArchiveMode(null);
            toast.push({
              variant: "success",
              title: t(
                mode === "archive"
                  ? "common:archive.done"
                  : "common:archive.unarchive_done",
              ),
            });
          }}
        />
      )}
      {/* W13-FIX §1 — the transition modal. Mounted only while a move is
          armed; nothing has been posted at this point. `changeStatus`
          runs from its onConfirm and closes it on success, and a
          refusal keeps it open with the reason inside so the answers
          already typed survive. */}
      {transitionTarget !== null && (
        <TicketTransitionModal
          // Keyed by the step, so switching moves gives a fresh form
          // instead of carrying one step's answers into another.
          key={transitionTarget}
          actionLabel={
            isCorrection(ticket.status, transitionTarget)
              ? t("workflow_move_back_to", {
                  status: tStatus(transitionTarget),
                })
              : t(`workflow_action.${transitionTarget}`)
          }
          fromStatusLabel={tStatus(ticket.status)}
          toStatusLabel={tStatus(transitionTarget)}
          requirements={transitionReqs}
          loading={transitionLoading}
          staff={transitionStaff}
          // R2 — what the step ALREADY has, so the modal shows it as the
          // default rather than asking for it again. `assigned_staff` is
          // the ticket's own roster, which is also where an extra-work
          // spawn's CARRIED-OVER workers land
          // (`extra_work/assignment_carryover.py::carry_workers_to_ticket`
          // writes `TicketStaffAssignment` rows) — so carried people
          // arrive prefilled without the modal knowing they were carried.
          currentAssignees={currentAssignees}
          currentScheduledStartAt={currentScheduledStartLocal}
          busy={statusBusy !== null}
          error={transitionError}
          // W-FIX2 — the proof photo, through the ticket's own attachment
          // endpoint. The gate reads non-hidden `TicketAttachment` rows
          // (`_ticket_has_visible_attachment`), so an ordinary upload
          // satisfies it and the transition endpoint needed no change.
          // `is_hidden` false explicitly: a hidden file is not evidence.
          onUploadProof={async (file: File) => {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("is_hidden", "false");
            await api.post(`/tickets/${id}/attachments/`, formData, {
              headers: { "Content-Type": "multipart/form-data" },
            });
            // The requirements are re-read so the server, not the modal,
            // decides the gate is satisfied.
            await loadTicket();
          }}
          onCancel={() => {
            setTransitionTarget(null);
            setTransitionReqs(null);
            setTransitionError("");
          }}
          onConfirm={(answers) => {
            void changeStatus(transitionTarget, answers);
          }}
        />
      )}

      {convertOpen && (
        <ConvertToExtraWorkDialog
          ticketId={ticket.id}
          // Sprint 143 §5 — the ticket already knows its customer, so
          // the dialog is always the "customer chosen" case: it can
          // offer that customer's price folders beside the company's
          // categories without asking for anything.
          customerId={ticket.customer}
          // Sprint 187 §6b — and its provider company, which scopes the
          // service + category pickers to the catalog this ticket's
          // customer can actually be charged from.
          companyId={ticket.company}
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

      {/* RF-5 — in-app attachment preview. Renders the file inline (PDF in an
          iframe, images in an img) over the authenticated blob object URL;
          unsupported types (e.g. HEIC/HEIF) fall back to a download notice.
          An explicit Download stays available for everything. */}
      <dialog
        ref={previewDialogRef}
        className="att-preview-dialog"
        onClose={handlePreviewClosed}
        aria-label={
          previewItem ? previewItem.original_filename : t("preview_title")
        }
      >
        <div className="att-preview-head">
          <div className="att-preview-head-info">
            <span className="att-thumb-ext">
              {previewItem
                ? getFileExtension(previewItem.original_filename)
                : "FILE"}
            </span>
            <span className="att-preview-name">
              {previewItem?.original_filename ?? t("preview_title")}
            </span>
          </div>
          <div className="att-preview-head-actions">
            {previewItem && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => downloadAttachment(previewItem)}
                disabled={downloadingAttachmentId === previewItem.id}
              >
                <Download size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>
                  {downloadingAttachmentId === previewItem.id
                    ? t("downloading")
                    : t("download")}
                </span>
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={requestPreviewClose}
            >
              {t("preview_close")}
            </button>
          </div>
        </div>
        <div className="att-preview-body">
          {previewLoading ? (
            <div className="att-preview-status">{t("preview_loading")}</div>
          ) : previewError ? (
            <div className="att-preview-status att-preview-status-error">
              {previewError}
            </div>
          ) : previewUrl && previewItem ? (
            attachmentPreviewKind(previewItem.mime_type) === "pdf" ? (
              <iframe
                className="att-preview-frame"
                src={previewUrl}
                title={previewItem.original_filename}
                data-testid="attachment-preview-pdf"
              />
            ) : attachmentPreviewKind(previewItem.mime_type) === "image" ? (
              <img
                className="att-preview-image"
                src={previewUrl}
                alt={previewItem.original_filename}
                data-testid="attachment-preview-image"
              />
            ) : (
              <div className="att-preview-status">
                {t("preview_unsupported")}
              </div>
            )
          ) : null}
        </div>
      </dialog>

      {/* W-UX1-B — the credential / property document viewer. Mounted
          unconditionally and driven through its ref: a native <dialog>
          behind a condition is an invisible dialog and a dead-looking
          button. `withDownload={false}` is the whole point — it drops
          the button AND asks the browser's PDF viewer to hide its own
          toolbar. */}
      <PdfPreviewDialog ref={credentialPreviewRef} withDownload={false} />
      {/* W-PLAN Task 2 — the SAME plan dialog the Extra Work page
          mounts, keyed by the stored plan so a save re-seeds it. A
          non-native overlay, conditionally mounted — the
          render-it-unconditionally rule is about native <dialog>. */}
      {ewPlanOpen && ewPlanDetail && (
        <PlanWorkDialog
          key={`ticket-plan-${ewPlanDetail.id}-${
            ewPlanDetail.planned_hours_total ?? ""
          }`}
          ew={ewPlanDetail}
          assignments={ewPlanAssignments}
          assignmentsLoading={ewPlanLoading}
          candidates={[]}
          candidatesLoading={false}
          assignBusy={false}
          assignError=""
          onAssign={() => undefined}
          busy={ewPlanBusy}
          error={ewPlanError}
          onCancel={() => {
            setEwPlanOpen(false);
            setEwPlanDetail(null);
          }}
          onSubmit={(payload) => void submitEwPlan(payload)}
          postSpawn
        />
      )}
    </div>
  );
}

