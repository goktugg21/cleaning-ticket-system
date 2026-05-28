/**
 * Sprint 28 Batch 15.1 — central enum-label resolver.
 *
 * Backend enum values (UserRole, TicketStatus, ExtraWorkStatus,
 * AccessRole, BuildingStaffVisibility.VisibilityLevel, ...) are
 * UPPER_SNAKE strings. The frontend SHOULD NOT render them raw — but
 * historically several spots either (a) printed `row.status` directly,
 * or (b) baked the raw value into a translated string (e.g.
 * `"Decides whether CUSTOMER_USER accounts see..."`).
 *
 * The fix is one resolver every page goes through. New code calls
 * `t(rolesLabelKey(role))` instead of writing the i18n key by hand.
 * Old code that still prints the raw value can be funnelled through
 * `prettyEnum(value)` as a defensive fallback (no i18n needed; just
 * turns CUSTOMER_USER into "Customer user").
 *
 * The classification helpers (`isProviderRole`, `isCustomerRole`)
 * power the new `<RoleBadge>` component so the Users page can show
 * provider-side roles in shell-green and customer-side roles in
 * teal-mint, instead of every role looking identical.
 */
import type {
  ExtraWorkStatusValue,
  Role,
  TicketStatus,
} from "../api/types";

// ---------------------------------------------------------------------------
// Generic fallback — turns "CUSTOMER_LOCATION_MANAGER" into
// "Customer location manager". Used when a value reaches the UI that
// isn't in any of the typed maps below; safer than printing the raw
// value. Avoid for anything the user sees regularly — translate it.
// ---------------------------------------------------------------------------
export function prettyEnum(value: string | null | undefined): string {
  if (!value) return "—";
  const lower = String(value).toLowerCase().replace(/_/g, " ");
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

// ---------------------------------------------------------------------------
// Role / access-role
// ---------------------------------------------------------------------------

/** All five global UserRole enum values, classified by side. */
const PROVIDER_ROLES: ReadonlySet<Role> = new Set<Role>([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "STAFF",
]);

const CUSTOMER_ROLES: ReadonlySet<Role> = new Set<Role>(["CUSTOMER_USER"]);

export function isProviderRole(role: Role | null | undefined): boolean {
  return role !== null && role !== undefined && PROVIDER_ROLES.has(role);
}

export function isCustomerRole(role: Role | null | undefined): boolean {
  return role !== null && role !== undefined && CUSTOMER_ROLES.has(role);
}

/**
 * i18n key for a global UserRole. The values live under `roles.*`
 * in `i18n/{en,nl}/common.json`.
 */
export function roleLabelKey(role: Role | null | undefined): string {
  switch (role) {
    case "SUPER_ADMIN":
      return "roles.super_admin";
    case "COMPANY_ADMIN":
      return "roles.company_admin";
    case "BUILDING_MANAGER":
      return "roles.building_manager";
    case "STAFF":
      return "roles.staff";
    case "CUSTOMER_USER":
      return "roles.customer_user";
    default:
      return "roles.fallback";
  }
}

/**
 * Customer-side per-building access role (from
 * `CustomerUserBuildingAccess.AccessRole`). Separate from the
 * global UserRole — every row here is on the customer side.
 */
export type AccessRoleValue =
  | "CUSTOMER_USER"
  | "CUSTOMER_LOCATION_MANAGER"
  | "CUSTOMER_COMPANY_ADMIN";

export function accessRoleLabelKey(value: AccessRoleValue | string): string {
  switch (value) {
    case "CUSTOMER_USER":
      return "access_role.customer_user";
    case "CUSTOMER_LOCATION_MANAGER":
      return "access_role.customer_location_manager";
    case "CUSTOMER_COMPANY_ADMIN":
      return "access_role.customer_company_admin";
    default:
      return "access_role.fallback";
  }
}

// ---------------------------------------------------------------------------
// Building staff visibility level
// ---------------------------------------------------------------------------

export type VisibilityLevelValue =
  | "ASSIGNED_ONLY"
  | "BUILDING_READ"
  | "BUILDING_READ_AND_ASSIGN";

export function visibilityLevelLabelKey(
  value: VisibilityLevelValue | string,
): string {
  switch (value) {
    case "ASSIGNED_ONLY":
      return "visibility_level.assigned_only";
    case "BUILDING_READ":
      return "visibility_level.building_read";
    case "BUILDING_READ_AND_ASSIGN":
      return "visibility_level.building_read_and_assign";
    default:
      return "visibility_level.fallback";
  }
}

// ---------------------------------------------------------------------------
// Ticket status
// ---------------------------------------------------------------------------

export function ticketStatusLabelKey(status: TicketStatus | string): string {
  switch (status) {
    case "OPEN":
      return "ticket_status.open";
    case "IN_PROGRESS":
      return "ticket_status.in_progress";
    case "WAITING_MANAGER_REVIEW":
      return "ticket_status.waiting_manager_review";
    case "WAITING_CUSTOMER_APPROVAL":
      return "ticket_status.waiting_customer_approval";
    case "APPROVED":
      return "ticket_status.approved";
    case "REJECTED":
      return "ticket_status.rejected";
    case "CLOSED":
      return "ticket_status.closed";
    case "REOPENED_BY_ADMIN":
      return "ticket_status.reopened_by_admin";
    default:
      return "ticket_status.fallback";
  }
}

/**
 * Semantic tone for a ticket status — drives badge color.
 */
export type StatusTone =
  | "open"
  | "progress"
  | "waiting"
  | "approved"
  | "rejected"
  | "closed"
  | "reopened"
  | "neutral";

export function ticketStatusTone(status: TicketStatus | string): StatusTone {
  switch (status) {
    case "OPEN":
      return "open";
    case "IN_PROGRESS":
      return "progress";
    case "WAITING_MANAGER_REVIEW":
    case "WAITING_CUSTOMER_APPROVAL":
      return "waiting";
    case "APPROVED":
      return "approved";
    case "REJECTED":
      return "rejected";
    case "CLOSED":
      return "closed";
    case "REOPENED_BY_ADMIN":
      return "reopened";
    default:
      return "neutral";
  }
}

// ---------------------------------------------------------------------------
// Extra Work status
// ---------------------------------------------------------------------------

export function extraWorkStatusLabelKey(
  status: ExtraWorkStatusValue | string,
): string {
  switch (status) {
    case "REQUESTED":
      return "extra_work_status.requested";
    case "UNDER_REVIEW":
      return "extra_work_status.under_review";
    case "PRICING_PROPOSED":
      return "extra_work_status.pricing_proposed";
    case "CUSTOMER_APPROVED":
      return "extra_work_status.customer_approved";
    case "IN_PROGRESS":
      return "extra_work_status.in_progress";
    case "COMPLETED":
      return "extra_work_status.completed";
    case "CUSTOMER_REJECTED":
      return "extra_work_status.customer_rejected";
    case "CANCELLED":
      return "extra_work_status.cancelled";
    default:
      return "extra_work_status.fallback";
  }
}

export function extraWorkStatusTone(
  status: ExtraWorkStatusValue | string,
): StatusTone {
  switch (status) {
    case "REQUESTED":
      return "open";
    case "UNDER_REVIEW":
      return "progress";
    case "PRICING_PROPOSED":
      return "waiting";
    case "CUSTOMER_APPROVED":
      return "approved";
    // Sprint 29 Batch 29.8 — IN_PROGRESS reuses the ticket-side
    // "progress" tone (orange/yellow). COMPLETED reuses the "approved"
    // green; success-completion mirrors the customer-approved tone.
    case "IN_PROGRESS":
      return "progress";
    case "COMPLETED":
      return "approved";
    case "CUSTOMER_REJECTED":
      return "rejected";
    case "CANCELLED":
      return "closed";
    default:
      return "neutral";
  }
}

// ---------------------------------------------------------------------------
// Priority / urgency (shared shape across Ticket + Extra Work)
// ---------------------------------------------------------------------------

export type PriorityValue = "NORMAL" | "HIGH" | "URGENT" | string;

export function priorityLabelKey(value: PriorityValue): string {
  switch (value) {
    case "NORMAL":
      return "priority.normal";
    case "HIGH":
      return "priority.high";
    case "URGENT":
      return "priority.urgent";
    default:
      return "priority.fallback";
  }
}

export function priorityTone(value: PriorityValue): StatusTone {
  switch (value) {
    case "URGENT":
      return "rejected";
    case "HIGH":
      return "waiting";
    case "NORMAL":
    default:
      return "neutral";
  }
}

