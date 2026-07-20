# Osius — Role → left-nav visibility matrix

**Created:** 2026-07-20 (Sprint #111). **Status:** reference. Every cell
below is sourced from code — the frontend nav gate in
[`frontend/src/auth/permissions.ts`](../../frontend/src/auth/permissions.ts)
(rendered in [`frontend/src/layout/AppShell.tsx`](../../frontend/src/layout/AppShell.tsx))
**and** the backend permission/scoping function that actually enforces
access. The frontend gate only decides whether a nav entry is drawn; the
backend is the security boundary and 403s / scopes every request
regardless.

---

## Preamble — the two role axes

Osius has **two independent role axes**. Do not conflate them:

1. **Provider global role** — `User.role` (the `UserRole` enum:
   `SUPER_ADMIN`, `COMPANY_ADMIN`, `BUILDING_MANAGER`, `STAFF`,
   `CUSTOMER_USER`). This is the ONLY value that appears in `Me.role` on
   `/api/auth/me/`, and it is what every left-nav gate in `permissions.ts`
   keys off.

2. **Per-building customer access role** —
   `CustomerUserBuildingAccess.access_role`
   (`CUSTOMER_USER` / `CUSTOMER_LOCATION_MANAGER` /
   `CUSTOMER_COMPANY_ADMIN`, plus the company-wide
   `CustomerUserMembership.is_company_admin` flag). These live on
   per-(user, customer, building) rows and **never** appear as `Me.role`.

**Key consequence for this matrix:** a customer-side admin (CCA) or
location manager (CLM) still has **provider global role `CUSTOMER_USER`**.
So every provider-axis nav gate treats CCA and CLM exactly like a plain
`CUSTOMER_USER` — their elevated customer-side rights change what they can
do *inside* the customer-scoped surfaces (Extra Work approval, per-building
permissions), not which left-nav entries appear. The matrix rows are the
five **provider** roles; the customer access-role axis is out of scope for
left-nav visibility.

Legend: **✓** shown · **—** hidden · a word = the entry is *relabelled*
for that role (see footnotes).

---

## Matrix — provider role (rows) × left-nav surface (columns)

| Provider role | Dashboard | Tickets¹ | My Work | Notifications | Inbox | Extra Work | Recurring work | Reports | Invoices | Settings | Admin group | Employees | Audit log | Staff requests | My reports¹ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SUPER_ADMIN** (SA)      | ✓ | Tickets | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| **COMPANY_ADMIN** (CA)    | ✓ | Tickets | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | — |
| **BUILDING_MANAGER** (BM) | ✓ | Tickets | ✓ *(tickets)* | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ *(read-only)* | ✓ | — | ✓ | — | ✓ | — |
| **STAFF**                 | ✓ | Tickets | ✓ *(slots)* | ✓ | ✓ | — | — | — | — | ✓ | — | — | — | — | — |
| **CUSTOMER_USER** (CU)    | ✓ | New report | — | ✓ | ✓ | ✓ | — | — | — | ✓ | — | ✓ *(own)* | — | — | ✓ |

¹ **Customer relabels (not the provider surfaces).** For `CUSTOMER_USER`
the "Tickets" entry is replaced by **New report** (`nav.new_melding` →
`/tickets/new`; nl "Nieuwe melding" / en "New report") — the melding-create
fast path, NOT the provider Tickets list (`nav.tickets` → `/tickets`). The
customer's *list* surface is **My reports** (`nav.my_meldingen` →
`/my/meldingen`; nl "Mijn meldingen" / en "My reports"), which is a
REPORT-type ticket list — it is **NOT** the provider **Reports**
(`nav.reports` → `/reports`, hidden for `CUSTOMER_USER`). The **Employees**
entry for `CUSTOMER_USER` is the own-customer directory `/my/employees`
(`isCustomerUser` branch), distinct from the provider `/admin/employees`.
"Inbox" renders as **Messages** (`nav.inbox`); "Recurring work" is
`nav.planned_work`.

---

## Enforcing gate per surface (FE helper + backend function)

The nav gate is the same across roles for a given surface, so it is listed
once here rather than repeated in every cell above.

| Surface (route) | FE gate (`permissions.ts`) — admits | Backend enforcement |
|---|---|---|
| **Dashboard** (`/`) | *(no gate — rendered for all roles)* | Each KPI/list endpoint scoped per-role: `scope_tickets_for`, `scope_extra_work_for`, notification recipient scope. |
| **Tickets** (`/tickets`) / **New report** (`/tickets/new`) | all roles; `isCustomerUser` swaps the label to New report | `accounts.scoping.scope_tickets_for` (view `get_queryset`); ticket-create endpoint for melding. |
| **My Work** (`/agenda`) | `canAccessAgenda` = `STAFF` \|\| `BUILDING_MANAGER` (Sprint 111) | STAFF → `tickets.views_staff_assignments.StaffAssignmentSlotAgendaView` (`GET /api/tickets/my-slots/`, caller `TicketStaffAssignment`). BM → `tickets.filters.TicketFilter.filter_my_managed` on top of `scope_tickets_for`. |
| **Notifications** (`/notifications`) | *(no gate — all roles)* | Notifications feed is recipient-scoped (`notifications` app / `listNotifications`). |
| **Inbox / Messages** (`/inbox`) | *(no gate — all roles)* | Aggregation computed per-viewer through the canonical `tickets.permissions.filter_messages_visible_to` chokepoint. |
| **Extra Work** (`/extra-work`, `/extra-work/request-quote`) | `canAccessExtraWork` = SA / CA / BM / CUSTOMER_USER (NOT STAFF) | `extra_work.scoping.scope_extra_work_for` (STAFF → `.none()`). |
| **Recurring work** (`/planned-work`) | `canAccessPlannedWork` = `isProviderManagementRole` (SA / CA / BM) | `planned_work.permissions.IsProviderManager` (403s STAFF + CUSTOMER_USER on every route incl. reads). |
| **Reports** (`/reports`) | `canAccessReports` = `isProviderManagementRole` (SA / CA / BM) | Provider reporting endpoints gated to provider-management. |
| **Invoices / Facturen** (`/invoices`) | `canAccessBilling` = `isProviderManagementRole` (SA / CA / BM; BM read-only) | `extra_work/billing.py` endpoints; mark/clear-invoiced additionally gated to `isProviderAdmin` (SA / CA). |
| **Settings** (`/settings`) | *(no gate — all roles)* | Self-scoped (own notification preferences). |
| **Admin group** (`/admin/companies`, `/buildings`, `/customers`, `/services`, `/users`, `/invitations`) | `canAccessAdminArea` = `isProviderAdmin` (SA / CA) | Admin viewsets gated by provider-admin permission classes (`CanManageUser`, customer/company/building write gates). |
| **Employees** (`/admin/employees`; CU: `/my/employees`) | admin group for SA / CA; `isBuildingManager` for the BM entry; `isCustomerUser` for `/my/employees` | Employees directory endpoints scoped to the caller's provider/customer scope. |
| **Audit log** (`/admin/audit-logs`) | `canAccessAuditLogs` = `isSuperAdmin` (SA only) | `audit/views.py::IsSuperAdmin`. |
| **Staff requests** (`/admin/staff-assignment-requests`) | `canAccessStaffRequestReview` = `isProviderManagementRole` (SA / CA / BM) | Staff-assignment-request review viewset (SA / CA + BM scoped to assigned buildings; empty for CUSTOMER_USER). |
| **My reports** (`/my/meldingen`) | `me.role === "CUSTOMER_USER"` | `scope_tickets_for` + `type=REPORT` filter. |

---

## My Work / agenda note (Sprint #111)

`/agenda` is a single route (auth-gated only) whose surface is
**role-adaptive**; `AgendaPage` dispatches on `me.role`:

- **STAFF → the dated slot agenda.** Each row is a
  `TicketStaffAssignment` **slot** (a *dated work block on a ticket*, one
  per staff member), fetched from the caller-scoped
  `GET /api/tickets/my-slots/`
  (`StaffAssignmentSlotAgendaView.get_queryset` filters
  `TicketStaffAssignment.objects.filter(user=request.user)`). Only STAFF
  can ever hold a slot: the staff-assign endpoint
  (`tickets/views_staff_assignments.py::_validate_target_staff`, ~line
  351) rejects any assignee whose `role != STAFF`.

- **BUILDING_MANAGER → their assigned tickets.** Fetched via the ticket
  list with the new opt-in `?my_managed=1` filter
  (`tickets.filters.TicketFilter.filter_my_managed`), which narrows to the
  **union** of two DISTINCT relations:
  - `Ticket.assigned_to` — the legacy single **primary-manager** FK; and
  - `TicketManagerAssignment` — the M:N **responsible-manager** table
    (reverse relation `manager_assignments`, `.user` FK).
  The filter runs on top of `scope_tickets_for`, so it can only narrow
  within the BM's own building scope (no cross-tenant surface).

- **SUPER_ADMIN + COMPANY_ADMIN → hidden.** Owner decision (Sprint #111):
  SA/CA hold neither personal slots nor a per-manager ticket relation
  worth a dedicated surface. `canAccessAgenda` excludes them, so the nav
  entry is absent; a direct `/agenda` URL renders the standard role-guard
  empty state, not the staff-slot copy.

**Three distinct concepts — do not conflate:**

| Concept | Table / field | Who holds it | Surfaced on My Work as |
|---|---|---|---|
| Staff **slot** | `TicketStaffAssignment` (dated) | STAFF only | the STAFF slot agenda |
| Ticket's **assigned manager** | `Ticket.assigned_to` (single FK) | a BM (legacy primary) | a BM "My tickets" row |
| **Responsible manager** (M:N) | `TicketManagerAssignment` | one or more BMs | a BM "My tickets" row |

`?my_managed=1` is the **union of the last two**; the STAFF `my_jobs`
filter keys off the **first** (`TicketStaffAssignment`) and is unchanged.

---

## customer-user surfaces audit (2026-07, from #110)

`CUSTOMER_USER` (provider-axis) sees a deliberately narrow left-nav, all
backend-scoped/gated with no leak, matching SoT §2.7:

- **Dashboard** — customer-scoped KPIs.
- **New report / My reports** — melding create (`/tickets/new`) + list
  (`/my/meldingen`, REPORT-type tickets).
- **Extra Work** — `scope_extra_work_for` narrows to the caller's own
  access-row buildings only.
- **Settings** — self-scoped notification preferences.
- **Employees** — `/my/employees`, own-customer directory only.

There is **no** left-nav Tickets item for `CUSTOMER_USER` by design
(#106 RF-3): the provider Tickets list is replaced by the New report
fast-path, and the customer's list is My reports. Provider-only surfaces
(Reports, Invoices, Recurring work, Admin group, Audit log, Staff
requests, My Work) are all hidden.
