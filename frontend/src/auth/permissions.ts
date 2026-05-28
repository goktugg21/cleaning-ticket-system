// Frontend permissions layer — single source of truth for UI gating.
//
// The backend remains the security boundary. This file's job is to make
// the SPA's role-based UI decisions consistent with backend reality and
// to centralise the role + access-role + note-tier vocabulary so it does
// not drift across screens.
//
// Source of truth on the backend:
//   - backend/accounts/models.py            (UserRole enum)
//   - backend/accounts/permissions.py       (is_provider_management_role, is_staff_role)
//   - backend/accounts/effective_actions.py (derived "can_X" actions)
//   - backend/tickets/models.py             (TicketMessageType four-tier taxonomy, B7)
//   - backend/customers/models.py           (CustomerUserBuildingAccess.access_role)
//
// The five global User roles below are the ONLY values that appear in
// `Me.role` on `/api/auth/me/`. The three customer-side access roles
// (CCA / CLM / CU access_role) live on per-(user, customer, building)
// access rows and never appear as `Me.role`.
//
// One important architectural constraint:
//
//   The backend endpoint GET /api/users/<id>/effective-permissions/
//   uses `CanManageUser` which admits only SUPER_ADMIN and COMPANY_ADMIN.
//   BUILDING_MANAGER, STAFF, and CUSTOMER_USER cannot call it for any
//   user — not even themselves. That endpoint therefore drives the
//   admin permission-overview screens (Customer Permissions page,
//   Customer Users tab, User detail page). Runtime self-gating for a
//   BM / STAFF / customer viewer has to derive from `me.role` + scope
//   ids; the predicates below cover those decisions.

import type { Role } from "../api/types";

// ---------------------------------------------------------------------------
// Global roles (mirrors backend UserRole)
// ---------------------------------------------------------------------------
export const USER_ROLES = [
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "STAFF",
  "CUSTOMER_USER",
] as const;
export type UserRoleValue = (typeof USER_ROLES)[number];

// ---------------------------------------------------------------------------
// Customer-side per-building access roles (CustomerUserBuildingAccess.access_role).
// These are NOT global User.role values — they appear only on per-building
// access rows under a Customer. A user with global role CUSTOMER_USER may
// hold different access_role values on different buildings of the same
// customer (e.g. CUSTOMER_USER on Building A and CUSTOMER_LOCATION_MANAGER
// on Building B).
// ---------------------------------------------------------------------------
export const CUSTOMER_ACCESS_ROLES = [
  "CUSTOMER_USER",
  "CUSTOMER_LOCATION_MANAGER",
  "CUSTOMER_COMPANY_ADMIN",
] as const;
export type CustomerAccessRoleValue = (typeof CUSTOMER_ACCESS_ROLES)[number];

// ---------------------------------------------------------------------------
// i18n label-key map. Covers every role value the UI may render, so a
// future seventh role does not silently fall through to "roles.fallback".
// Both nl/common.json and en/common.json carry every key listed here.
// ---------------------------------------------------------------------------
export const ROLE_LABEL_KEY: Record<UserRoleValue, string> = {
  SUPER_ADMIN: "roles.super_admin",
  COMPANY_ADMIN: "roles.company_admin",
  BUILDING_MANAGER: "roles.building_manager",
  STAFF: "roles.staff",
  CUSTOMER_USER: "roles.customer_user",
};

export const CUSTOMER_ACCESS_ROLE_LABEL_KEY: Record<
  CustomerAccessRoleValue,
  string
> = {
  CUSTOMER_USER: "access_role.customer_user",
  CUSTOMER_LOCATION_MANAGER: "access_role.customer_location_manager",
  CUSTOMER_COMPANY_ADMIN: "access_role.customer_company_admin",
};

// Returns the bare i18n key (e.g. "roles.super_admin"). Use inside a
// `useTranslation("common")` context where the default namespace is
// already common.
export function roleLabelKey(role: Role | null | undefined): string {
  if (!role) return "roles.fallback";
  return ROLE_LABEL_KEY[role as UserRoleValue] ?? "roles.fallback";
}

// Returns the namespace-qualified i18n key (e.g. "common:roles.super_admin").
// Use from a `useTranslation()` call site whose default namespace is NOT
// common, so the lookup works regardless of context.
export function roleLabelKeyNs(role: Role | null | undefined): string {
  return `common:${roleLabelKey(role)}`;
}

// ---------------------------------------------------------------------------
// Role-set predicates. Mirror the backend helpers of the same name.
// Each one takes the live `Role | null | undefined` so callers don't
// duplicate the null-check on every site.
// ---------------------------------------------------------------------------

// Backend: `accounts.permissions.is_provider_management_role`. The three
// roles that may see + author PROVIDER_INTERNAL (INTERNAL_NOTE) ticket
// messages. STAFF is deliberately excluded.
export function isProviderManagementRole(role: Role | null | undefined): boolean {
  return (
    role === "SUPER_ADMIN" ||
    role === "COMPANY_ADMIN" ||
    role === "BUILDING_MANAGER"
  );
}

// Backend: `accounts.permissions.is_staff_role`. Provider-side actors —
// management trio PLUS STAFF (field workers). Drives staff-only
// behaviours like ticket completion-evidence stamping.
export function isStaffRole(role: Role | null | undefined): boolean {
  return isProviderManagementRole(role) || role === "STAFF";
}

// Provider-admin pair (SA + COMPANY_ADMIN). The backend `CanManageUser`
// admit set; also the admit set for customer/company/building writes,
// the audit-log feed (SA only, narrower — see `isSuperAdmin`), and the
// override-customer-decision flow on tickets.
export function isProviderAdmin(role: Role | null | undefined): boolean {
  return role === "SUPER_ADMIN" || role === "COMPANY_ADMIN";
}

export function isSuperAdmin(role: Role | null | undefined): boolean {
  return role === "SUPER_ADMIN";
}

export function isBuildingManager(role: Role | null | undefined): boolean {
  return role === "BUILDING_MANAGER";
}

export function isStaff(role: Role | null | undefined): boolean {
  return role === "STAFF";
}

export function isCustomerUser(role: Role | null | undefined): boolean {
  return role === "CUSTOMER_USER";
}

// ---------------------------------------------------------------------------
// Nav / route gating predicates. These are derived from the backend rules
// for "can this role even reach this screen". They are NOT a substitute
// for backend enforcement — the backend still 403s on every request.
// ---------------------------------------------------------------------------

// "Admin area" — the top-level admin nav group (Companies, Buildings,
// Customers, Services, Users, Invitations). Backend: provider-admin pair.
export const canAccessAdminArea = isProviderAdmin;

// `/admin/audit-logs` — backend `audit/views.py::IsSuperAdmin`.
export const canAccessAuditLogs = isSuperAdmin;

// `/extra-work` — backend `scope_extra_work_for`:
//   - SA / COMPANY_ADMIN: full provider scope.
//   - BUILDING_MANAGER: scoped to assigned buildings.
//   - CUSTOMER_USER: scoped to access rows.
//   - STAFF: returns `.none()` (post-P0 staff-privacy revert). STAFF
//     must NOT see the nav; their view of EW-spawned tickets is via
//     the normal ticket list (Ticket.extra_work_origin metadata).
export function canAccessExtraWork(role: Role | null | undefined): boolean {
  return (
    role === "SUPER_ADMIN" ||
    role === "COMPANY_ADMIN" ||
    role === "BUILDING_MANAGER" ||
    role === "CUSTOMER_USER"
  );
}

// `/reports` — provider-side reporting surface. Backend gates everywhere.
export function canAccessReports(role: Role | null | undefined): boolean {
  return isProviderManagementRole(role);
}

// `/admin/staff-assignment-requests` — backend admits the BM for the
// queue covering their assigned buildings, on top of the provider-admin
// pair. STAFF requests assignment via the ticket-detail button instead.
export function canAccessStaffRequestReview(
  role: Role | null | undefined,
): boolean {
  return isProviderManagementRole(role);
}

// Read-only customer surfaces under `/admin/customers/...` (Overview +
// Contacts). Backend: `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer`.
export function canReadCustomerArea(role: Role | null | undefined): boolean {
  return isProviderManagementRole(role);
}

// Customer-contacts panel — backend `IsSuperAdminOrCompanyAdminForCompany`.
// BM is NOT admitted (the assigned-staff visibility flags do not extend
// to contact-list reads). STAFF / CUSTOMER_USER never see this panel.
export const canViewCustomerContacts = isProviderAdmin;

// ---------------------------------------------------------------------------
// Note tier (B7 four-tier taxonomy on TicketMessage.message_type)
// ---------------------------------------------------------------------------
export const TICKET_MESSAGE_TIERS = [
  "PUBLIC_REPLY",
  "INTERNAL_NOTE",
  "STAFF_OPERATIONAL",
  "STAFF_COMPLETION",
] as const;
export type TicketMessageTier = (typeof TICKET_MESSAGE_TIERS)[number];

// Backend: `tickets.views.TicketMessageViewSet.get_queryset` + the
// write-side validation in `tickets.serializers`. Mirrors those rules
// so the SPA can render the composer + per-bubble badge consistently.
//
// The customer-side access roles (CCA / CLM / CU access_role) are NOT
// `Me.role` values — for the composer we only need the current viewer's
// global role; backend filters customer-side users at the queryset level.

export function canReadTicketMessageTier(
  role: Role | null | undefined,
  tier: TicketMessageTier,
): boolean {
  if (isProviderManagementRole(role)) return true;
  if (role === "STAFF") {
    // STAFF: PUBLIC_REPLY + STAFF_OPERATIONAL + STAFF_COMPLETION.
    return tier !== "INTERNAL_NOTE";
  }
  if (role === "CUSTOMER_USER") {
    // Customer-side: PUBLIC_REPLY + STAFF_COMPLETION.
    return tier === "PUBLIC_REPLY" || tier === "STAFF_COMPLETION";
  }
  return false;
}

export function canWriteTicketMessageTier(
  role: Role | null | undefined,
  tier: TicketMessageTier,
): boolean {
  if (isProviderManagementRole(role)) return true;
  if (role === "STAFF") {
    // STAFF may compose STAFF_OPERATIONAL and STAFF_COMPLETION only.
    return tier === "STAFF_OPERATIONAL" || tier === "STAFF_COMPLETION";
  }
  if (role === "CUSTOMER_USER") {
    // Customer-side may only post PUBLIC_REPLY.
    return tier === "PUBLIC_REPLY";
  }
  return false;
}

// What tier values the composer should offer to this viewer, in display
// order. Used by TicketDetailPage to render the tier-picker tabs.
export function composerTiersForRole(
  role: Role | null | undefined,
): TicketMessageTier[] {
  return TICKET_MESSAGE_TIERS.filter((tier) =>
    canWriteTicketMessageTier(role, tier),
  );
}
