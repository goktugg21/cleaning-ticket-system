// Typed client for GET /api/users/<id>/effective-permissions/.
//
// Backend: backend/accounts/views_users.py::UserViewSet.effective_permissions
//          backend/accounts/effective_actions.py (compute_* helpers)
//
// IMPORTANT — caller-authorization constraint:
//   The endpoint is gated by `CanManageUser`. That admits only
//   SUPER_ADMIN and COMPANY_ADMIN as callers. BUILDING_MANAGER, STAFF,
//   and CUSTOMER_USER will receive 403 on every call (including for
//   their own user id). This client is therefore for admin permission-
//   overview screens — Customer Permissions, Customer Users tab, User
//   detail page. Runtime self-introspection for non-admin viewers must
//   derive from `Me.role` + scope ids; see frontend/src/auth/permissions.ts.

import { api } from "./client";
import type { CustomerAccessRole, CustomerPermissionKey, Role } from "./types";

// The set of keys returned in `effective_actions`. Every key the backend
// emits MUST be listed here; missing names would silently drop to
// `undefined` at consumer call sites. Source: enumerate
// backend/accounts/effective_actions.py::compute_effective_actions.
export const EFFECTIVE_ACTION_KEYS = [
  "can_view_customer",
  "can_view_building",
  "can_view_tickets",
  "can_create_ticket",
  "can_change_ticket_status",
  "can_override_customer_decision",
  "can_view_extra_work",
  "can_create_extra_work",
  "can_use_contract_price_direct_order",
  "can_request_non_contract_extra_work",
  "can_prepare_extra_work_proposal",
  "can_view_proposal_prices",
  "can_manage_customer_users",
  "can_manage_customer_permissions",
  "can_manage_customer_company_admins",
  "can_view_provider_internal_notes",
  "can_view_staff_operational_notes",
] as const;
export type EffectiveActionKey = (typeof EFFECTIVE_ACTION_KEYS)[number];

export type EffectiveActions = Record<EffectiveActionKey, boolean>;

// The full response shape returned by the endpoint.
export interface EffectivePermissionsResponse {
  user: {
    id: number;
    email: string;
    role: Role;
    is_active: boolean;
  };
  context: {
    customer_id: number;
    building_id: number | null;
    company_id: number;
  };
  scope: {
    in_scope: boolean;
    reason: string;
  };
  role_defaults: {
    role: Role;
    access_role: CustomerAccessRole | null;
    default_permission_keys: CustomerPermissionKey[];
  };
  overrides: Array<{
    building_id: number;
    building_name: string | null;
    access_role: CustomerAccessRole;
    is_active: boolean;
    permission_overrides: Record<CustomerPermissionKey, boolean>;
  }>;
  effective_permissions: Record<CustomerPermissionKey, boolean>;
  effective_actions: EffectiveActions;
  notes: string[];
}

export interface FetchEffectivePermissionsArgs {
  userId: number;
  customerId: number;
  buildingId?: number | null;
  signal?: AbortSignal;
}

export async function fetchEffectivePermissions(
  args: FetchEffectivePermissionsArgs,
): Promise<EffectivePermissionsResponse> {
  const params: Record<string, string> = {
    customer_id: String(args.customerId),
  };
  if (args.buildingId != null) {
    params.building_id = String(args.buildingId);
  }
  const response = await api.get<EffectivePermissionsResponse>(
    `/users/${args.userId}/effective-permissions/`,
    { params, signal: args.signal },
  );
  return response.data;
}
