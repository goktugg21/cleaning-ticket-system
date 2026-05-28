/**
 * Sprint 29 Batch 29.8.5 — shared permission-key-label table.
 *
 * Extracted from `OverrideDrawer.tsx` so the new
 * `AccessPermissionsPanel` can render the exact same 16-row layout
 * grouped by domain without duplicating the key list or the per-key
 * i18n label / description keys.
 *
 * The labels and descriptions themselves still live in the i18n
 * bundles under `customer_permissions.permission_keys.<key>.label`
 * and `.description` — this module only owns the (key, group)
 * pairing + the per-group i18n key.
 */
import type { CustomerPermissionKey } from "../../../../api/types";

export type PermissionGroup = "tickets" | "extra_work" | "users";

export interface PermissionKeyRow {
  key: CustomerPermissionKey;
  group: PermissionGroup;
}

export const PERMISSION_KEY_ROWS: ReadonlyArray<PermissionKeyRow> = [
  // Tickets (6)
  { key: "customer.ticket.create", group: "tickets" },
  { key: "customer.ticket.view_own", group: "tickets" },
  { key: "customer.ticket.view_location", group: "tickets" },
  { key: "customer.ticket.view_company", group: "tickets" },
  { key: "customer.ticket.approve_own", group: "tickets" },
  { key: "customer.ticket.approve_location", group: "tickets" },
  // Extra Work (6)
  { key: "customer.extra_work.create", group: "extra_work" },
  { key: "customer.extra_work.view_own", group: "extra_work" },
  { key: "customer.extra_work.view_location", group: "extra_work" },
  { key: "customer.extra_work.view_company", group: "extra_work" },
  { key: "customer.extra_work.approve_own", group: "extra_work" },
  { key: "customer.extra_work.approve_location", group: "extra_work" },
  // Users (4)
  { key: "customer.users.invite", group: "users" },
  { key: "customer.users.manage", group: "users" },
  { key: "customer.users.assign_location_role", group: "users" },
  { key: "customer.users.manage_permissions", group: "users" },
];

export const PERMISSION_GROUP_LABEL_KEY: Record<PermissionGroup, string> = {
  tickets: "customer_permissions.permission_groups.tickets",
  extra_work: "customer_permissions.permission_groups.extra_work",
  users: "customer_permissions.permission_groups.users",
};

export function permissionKeyLabelKey(key: CustomerPermissionKey): string {
  return `customer_permissions.permission_keys.${key}.label`;
}

export function permissionKeyDescriptionKey(
  key: CustomerPermissionKey,
): string {
  return `customer_permissions.permission_keys.${key}.description`;
}
