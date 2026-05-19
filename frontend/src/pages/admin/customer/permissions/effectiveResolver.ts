/**
 * Sprint 28 Batch 15.2 — effective-permission resolver (display-only).
 *
 * Mirrors the precedence in backend/customers/permissions.py:
 *   1. access.is_active === false        -> deny
 *   2. permission_overrides[key] explicit -> that value wins
 *   3. CustomerCompanyPolicy denies key   -> deny
 *   4. role default for sub-role + key
 *
 * Used by the override drawer to render the "Effective: ..." hint
 * next to each key. The backend remains the source of truth at
 * save time; this resolver only previews what the value WILL be
 * once the operator presses save.
 *
 * The role-default sets here are mirrored from
 * `_TICKET_ROLE_DEFAULTS` in backend/customers/permissions.py. If
 * the backend table changes, update these sets too (verified at
 * sprint time — there is no runtime sync).
 */
import type {
  CustomerAccessRole,
  CustomerCompanyPolicyAdmin,
  CustomerPermissionKey,
} from "../../../../api/types";

export type OverrideDraftValue = "inherit" | "allow" | "deny";

export type EffectiveSource =
  | { effective: "allow"; reason: "role_default" | "override_grant" }
  | {
      effective: "deny";
      reason: "inactive" | "policy" | "override_revoke" | "role_default_deny";
    };

const POLICY_DENIES: Record<
  keyof Pick<
    CustomerCompanyPolicyAdmin,
    | "customer_users_can_create_tickets"
    | "customer_users_can_approve_ticket_completion"
    | "customer_users_can_create_extra_work"
    | "customer_users_can_approve_extra_work_pricing"
  >,
  ReadonlyArray<CustomerPermissionKey>
> = {
  customer_users_can_create_tickets: ["customer.ticket.create"],
  customer_users_can_approve_ticket_completion: [
    "customer.ticket.approve_own",
    "customer.ticket.approve_location",
  ],
  customer_users_can_create_extra_work: ["customer.extra_work.create"],
  customer_users_can_approve_extra_work_pricing: [
    "customer.extra_work.approve_own",
    "customer.extra_work.approve_location",
  ],
};

function policyDeniesKey(
  policy: CustomerCompanyPolicyAdmin,
  key: CustomerPermissionKey,
): boolean {
  for (const [field, keys] of Object.entries(POLICY_DENIES) as Array<
    [keyof typeof POLICY_DENIES, ReadonlyArray<CustomerPermissionKey>]
  >) {
    if (policy[field] === false && keys.includes(key)) {
      return true;
    }
  }
  return false;
}

// Mirror of backend/customers/permissions.py::_TICKET_ROLE_DEFAULTS.
// Keep in lockstep with the backend; the drift between this table
// and the backend is the only way the inline "effective" hint can
// lie.
const ROLE_DEFAULTS: Record<
  CustomerAccessRole,
  ReadonlySet<CustomerPermissionKey>
> = {
  CUSTOMER_USER: new Set<CustomerPermissionKey>([
    "customer.ticket.create",
    "customer.ticket.view_own",
    "customer.ticket.approve_own",
    "customer.extra_work.create",
    "customer.extra_work.view_own",
    "customer.extra_work.approve_own",
  ]),
  CUSTOMER_LOCATION_MANAGER: new Set<CustomerPermissionKey>([
    "customer.ticket.create",
    "customer.ticket.view_own",
    "customer.ticket.view_location",
    "customer.ticket.approve_own",
    "customer.ticket.approve_location",
    "customer.extra_work.create",
    "customer.extra_work.view_own",
    "customer.extra_work.view_location",
    "customer.extra_work.approve_own",
    "customer.extra_work.approve_location",
    "customer.users.assign_location_role",
  ]),
  CUSTOMER_COMPANY_ADMIN: new Set<CustomerPermissionKey>([
    "customer.ticket.create",
    "customer.ticket.view_own",
    "customer.ticket.view_location",
    "customer.ticket.view_company",
    "customer.ticket.approve_own",
    "customer.ticket.approve_location",
    "customer.extra_work.create",
    "customer.extra_work.view_own",
    "customer.extra_work.view_location",
    "customer.extra_work.view_company",
    "customer.extra_work.approve_own",
    "customer.extra_work.approve_location",
    "customer.users.invite",
    "customer.users.manage",
    "customer.users.assign_location_role",
    "customer.users.manage_permissions",
  ]),
};

export function resolveEffective(args: {
  key: CustomerPermissionKey;
  draftValue: OverrideDraftValue;
  isActive: boolean;
  policy: CustomerCompanyPolicyAdmin | null;
  accessRole: CustomerAccessRole;
}): EffectiveSource {
  if (!args.isActive) {
    return { effective: "deny", reason: "inactive" };
  }
  if (args.draftValue === "allow") {
    return { effective: "allow", reason: "override_grant" };
  }
  if (args.draftValue === "deny") {
    return { effective: "deny", reason: "override_revoke" };
  }
  // "inherit" — fall through to policy then role default.
  if (args.policy && policyDeniesKey(args.policy, args.key)) {
    return { effective: "deny", reason: "policy" };
  }
  if (ROLE_DEFAULTS[args.accessRole].has(args.key)) {
    return { effective: "allow", reason: "role_default" };
  }
  return { effective: "deny", reason: "role_default_deny" };
}

/**
 * Maps an EffectiveSource to its i18n key under
 * `customer_permissions.overrides_drawer.effective.*`.
 */
export function effectiveLabelKey(source: EffectiveSource): string {
  if (source.effective === "allow") {
    return source.reason === "override_grant"
      ? "customer_permissions.overrides_drawer.effective.allow_override_grant"
      : "customer_permissions.overrides_drawer.effective.allow_role_default";
  }
  switch (source.reason) {
    case "inactive":
      return "customer_permissions.overrides_drawer.effective.deny_inactive";
    case "policy":
      return "customer_permissions.overrides_drawer.effective.deny_policy";
    case "override_revoke":
      return "customer_permissions.overrides_drawer.effective.deny_override_revoke";
    case "role_default_deny":
    default:
      return "customer_permissions.overrides_drawer.effective.deny_role_default";
  }
}

/**
 * Maps a draft "inherit | allow | deny" plus the existing override
 * map to the wire shape that PATCH /access expects: a record of
 * `{ key: true | false }` containing ONLY the keys that the operator
 * explicitly set to allow/deny. Inherit removes the key from the map.
 */
export function buildOverridesPayload(
  draft: Record<CustomerPermissionKey, OverrideDraftValue>,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value === "allow") out[key] = true;
    else if (value === "deny") out[key] = false;
  }
  return out;
}

/**
 * Reads a single key out of an existing `permission_overrides`
 * record (the wire shape) into the tri-state draft value.
 */
export function draftValueFromOverride(
  overrides: Record<string, boolean>,
  key: CustomerPermissionKey,
): OverrideDraftValue {
  if (!(key in overrides)) return "inherit";
  return overrides[key] ? "allow" : "deny";
}

// Sprint 29 Batch 29.8.5 — read-only resolution for the inline
// AccessPermissionsPanel. Returns both the boolean effective value
// AND one of five distinct reasons so the panel can render a
// per-row "why" hint without recomputing the precedence tree.
//
// The mapping intentionally collapses `inactive` and `policy` into
// `policy_denied` (visually identical user-facing meaning: "denied
// because of an upstream constraint, not a permission decision");
// the OverrideDrawer keeps the full 6-reason vocabulary because
// the operator there is actively editing and needs the finer
// distinction (Sprint 27E UX).
export type PanelReason =
  | "override_granted"
  | "override_denied"
  | "policy_denied"
  | "role_default_granted"
  | "role_default_denied";

export interface PanelResolution {
  granted: boolean;
  reason: PanelReason;
}

export function resolvePanelValue(args: {
  key: CustomerPermissionKey;
  overrides: Record<string, boolean>;
  isActive: boolean;
  policy: CustomerCompanyPolicyAdmin | null;
  accessRole: CustomerAccessRole;
}): PanelResolution {
  const draftValue = draftValueFromOverride(args.overrides, args.key);
  const effective = resolveEffective({
    key: args.key,
    draftValue,
    isActive: args.isActive,
    policy: args.policy,
    accessRole: args.accessRole,
  });
  if (effective.effective === "allow") {
    return {
      granted: true,
      reason:
        effective.reason === "override_grant"
          ? "override_granted"
          : "role_default_granted",
    };
  }
  // deny variants:
  switch (effective.reason) {
    case "override_revoke":
      return { granted: false, reason: "override_denied" };
    case "inactive":
    case "policy":
      return { granted: false, reason: "policy_denied" };
    case "role_default_deny":
    default:
      return { granted: false, reason: "role_default_denied" };
  }
}

export function panelReasonLabelKey(reason: PanelReason): string {
  return `customer_permissions.access_panel.reason_${reason}`;
}

