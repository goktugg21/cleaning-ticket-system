# Osius — Role → navigation visibility matrix

**Created:** 2026-07-20 (Sprint #111). **Re-derived:** 2026-08-29 (FE-7,
the closing sprint of the Addendum D frontend redesign) from the code as
it stands on `feat/fe-7-final-audit`: the nav in
[`frontend/src/layout/AppShell.tsx`](../../frontend/src/layout/AppShell.tsx),
the gate predicates in
[`frontend/src/auth/permissions.ts`](../../frontend/src/auth/permissions.ts),
the route guards in [`frontend/src/App.tsx`](../../frontend/src/App.tsx)
and the customer-page tabs in
[`frontend/src/pages/admin/customer/CustomerSubPageHeader.tsx`](../../frontend/src/pages/admin/customer/CustomerSubPageHeader.tsx).
**Status:** reference. Every cell is sourced from that code, not from a
sprint report. The frontend gate only decides whether an entry is drawn;
the backend is the security boundary and 403s / scopes every request
regardless (the enforcing function per surface is listed in §3).

The per-entry ROLE GATES are the ones Sprint #111 recorded: FE-1 moved
and renamed entries, FE-6 merged five of them into two, and neither
widened or narrowed a gate. What changed is the shape: three navigations
(one per audience) instead of one list with role-swapped rows.

---

## 1. The two role axes (unchanged)

Osius has **two independent role axes**. Do not conflate them:

1. **Provider global role** — `User.role` (`SUPER_ADMIN`, `COMPANY_ADMIN`,
   `BUILDING_MANAGER`, `STAFF`, `CUSTOMER_USER`). The ONLY value in
   `Me.role` on `/api/auth/me/`, and what every nav gate keys off.
2. **Per-building customer access role** —
   `CustomerUserBuildingAccess.access_role` (`CUSTOMER_USER` /
   `CUSTOMER_LOCATION_MANAGER` / `CUSTOMER_COMPANY_ADMIN`) plus the
   company-wide `CustomerUserMembership.is_company_admin` flag. These live
   on per-(user, customer, building) rows and never appear as `Me.role`.

A customer-side admin (CCA) or location manager (CLM) still has global
role `CUSTOMER_USER`, so the **customer portal nav is identical for all
three**; their elevated rights change what they can do *inside* Meerwerk
(approve a price, approve completion) and Instellingen (permissions), not
which entries appear.

Legend: **✓** shown · **—** hidden · **(addr)** hidden from the nav but
reachable by address for that role · **(badge)** shown only while there
is something to review.

---

## 2. The three navigations

### 2.1 Provider console — SUPER_ADMIN (SA), COMPANY_ADMIN (CA), BUILDING_MANAGER (BM)

Four groups, rendered in this order. A group heading renders only when
the role sees at least one entry under it.

| Group | Entry (nl / en) | Route | SA | CA | BM | Gate (`permissions.ts`) |
|---|---|---|---|---|---|---|
| Werk | Dashboard / Dashboard | `/` | ✓ | ✓ | ✓ | none (all provider roles) |
| Werk | Nieuw / New | `/new` | ✓ | ✓ | ✓ | none |
| Werk | Tickets / Tickets | `/tickets` | ✓ | ✓ | ✓ | none (a CUSTOMER_USER reaching it is redirected to `/my/meldingen`) |
| Werk | Werkplanning / My schedule | `/agenda` | ✓ | ✓ | ✓ | `canAccessAgenda` = STAFF, BM, SA, CA |
| Werk | Meerwerk / Extra work | `/extra-work` | ✓ | ✓ | ✓ | `canAccessExtraWork` = SA, CA, BM, CUSTOMER_USER (not STAFF) |
| Werk | Terugkerend werk / Recurring work | `/planned-work` | ✓ | ✓ | ✓ | `canAccessPlannedWork` = `isProviderManagementRole` |
| Werk | Notificaties / Notifications | `/notifications` | ✓ | ✓ | ✓ | none |
| Werk | Berichten / Messages | `/inbox` | ✓ | ✓ | ✓ | none |
| Financieel | Facturen / Invoices | `/invoices` | ✓ | ✓ | ✓ read-only | `canAccessBilling` = `isProviderManagementRole` |
| Financieel | Contracten / Contracts | `/admin/contracts` | ✓ | ✓ | ✓ | `canAccessContracts` = SA, CA, BM (writes: `canManageContracts` = SA, CA) |
| Financieel | Uren / Hours | `/admin/hours` | ✓ | ✓ | — | `canManageTimesheets` = SA, CA |
| Financieel | Mijn uren / My hours | `/my-hours` | — | ✓ | ✓ | `canAccessTimesheets` = STAFF, BM, CA (an SA holds no hours of their own) |
| Financieel | Rapporten / Reports | `/reports` | ✓ | ✓ | ✓ | `canAccessReports` = `isProviderManagementRole` |
| Klanten & mensen | Klanten / Customers | `/admin/customers` | ✓ | ✓ | (addr) | nav: `canAccessAdminArea` = SA, CA; route: `CustomerReadRoute` = `canReadCustomerArea` (SA, CA, BM) — a BM reads the list and three customer tabs, see §2.4 |
| Klanten & mensen | Gebouwen / Buildings | `/admin/buildings` | ✓ | ✓ | — | `canAccessAdminArea` |
| Klanten & mensen | Mensen / People | `/admin/people/:tab` | ✓ | ✓ | ✓ employees tab only | nav: `canAccessAdminArea` or `isBuildingManager`; each tab keeps its own gate (users + invitations: `canAccessAdminArea`; employees: provider management) |
| Klanten & mensen | Medewerker-aanvragen / Staff requests | `/admin/staff-assignment-requests` | (badge) | (badge) | (badge) | `canAccessStaffRequestReview` = `isProviderManagementRole`, drawn only while a PENDING request exists (count on the badge) |
| Systeem | Diensten & catalogi / Services & catalogs | `/admin/services-catalogs/:tab` | ✓ | ✓ | — | `canAccessAdminArea` |
| Systeem | Bedrijven / Companies | `/admin/companies` | ✓ | ✓ | — | `canAccessAdminArea` (create/reactivate: SA only, enforced server-side) |
| Systeem | Auditlog / Audit log | `/admin/audit-logs` | ✓ | — | — | `canAccessAuditLogs` = `isSuperAdmin` |
| Systeem | Waarschuwingen / Warnings | `/admin/sla-warnings` | ✓ | ✓ | — | `canManageSlaWarnings` = SA, CA |
| Systeem | Instellingen / Settings | `/settings` | ✓ | ✓ | ✓ | none |

Old addresses still resolve: `/admin/users`, `/admin/employees`,
`/admin/invitations` redirect to the matching Mensen tab; `/admin/services`
and `/admin/catalogs` to the matching Diensten & catalogi tab;
`/tickets/chargeable` to the tickets list with the meerwerk work filter;
`/extra-work/request-quote` to `/extra-work/new`. The "Chargeable work"
entries and the customer "Beperkt tot" sidebar swap no longer exist.

### 2.2 Staff — STAFF

Four entries, fixed order. `/` redirects to Werkplanning
(`HomeRoute` in `App.tsx`).

| Entry (nl / en) | Route | Gate |
|---|---|---|
| Werkplanning / My schedule | `/agenda` | `canAccessAgenda` |
| Mijn uren / My hours | `/my-hours` | `canAccessTimesheets` |
| Berichten / Messages | `/inbox` (the bell feed is the `?tab=notifications` tab of the same page) | none |
| Instellingen / Settings | `/settings` | none |

Hidden for STAFF by gate, not by omission: Meerwerk (`canAccessExtraWork`
excludes STAFF; `scope_extra_work_for` returns `.none()`), Terugkerend
werk, Rapporten, Facturen, Contracten, Uren (admin), every admin surface.
A direct address renders the role-guard empty state.

### 2.3 Customer portal — CUSTOMER_USER (CU / CLM / CCA)

Six entries, fixed order; the sixth is a fold. `/` renders Start
(`StartPage`).

| Entry (nl / en) | Route | Gate |
|---|---|---|
| Start / Start | `/` | none |
| Melding maken / New report | `/tickets/new` | none (`MeldingCreatePage` for this role) |
| Mijn meldingen / My reports | `/my/meldingen` | none (REPORT-type tickets, scoped) |
| Meerwerk / Extra work | `/extra-work` (request: `/extra-work/new`; one object per request: `/extra-work/:id`) | `canAccessExtraWork` |
| Facturen / Invoices | `/my/facturen` | `CustomerRoute` |
| Meer / More (fold) → Berichten `/inbox`, Notificaties `/notifications`, Medewerkers `/my/employees`, Documenten `/my/documents` (only when `me.can_manage_documents`), Instellingen `/settings` | | `CustomerRoute` for documents; none for the rest |

There is no Tickets entry and no Dashboard for this role by design
(#106 RF-3, Addendum D §D.3.1): the provider Tickets list redirects a
customer to Mijn meldingen; single-ticket deep links (`/tickets/:id`)
keep working within `scope_tickets_for`.

### 2.4 Customer page tabs (provider roles, FE-6)

A customer is a page with one row of tabs. Each tab keeps the gate its
route always had; a tab is drawn only for a role its gate admits.

| Tab (nl / en) | Route | SA / CA | BM | Gate |
|---|---|---|---|---|
| Overzicht / Overview | `/admin/customers/:id` | ✓ | ✓ | `canReadCustomerArea` |
| Gebouwen / Buildings | `…/buildings` | ✓ | — | `canAccessAdminArea` |
| Mensen / People → Gebruikers | `…/users` | ✓ | — | `canAccessAdminArea` |
| Mensen / People → Contactpersonen | `…/contacts` | ✓ | ✓ | `canReadCustomerArea` |
| Permissies / Permissions | `…/permissions` | ✓ | — | `canAccessAdminArea` |
| Prijzen / Prices | `…/pricing` | ✓ | — | `canAccessAdminArea` |
| Contracten / Contracts | `…/contracts` | ✓ | — | `canAccessAdminArea` and `canAccessContracts` |
| Werk / Work → Tickets, Meerwerk | `…/tickets`, `…/extra-work` | ✓ | — | `canAccessAdminArea` |
| Facturen / Invoices → Facturen, Rapport | `…/invoices`, `…/reports` | ✓ | — | `canAccessAdminArea` |
| Documenten / Documents | `…/documents` | ✓ | — | `canAccessAdminArea` |
| Instellingen / Settings → Instellingen | `…/settings` | ✓ | — | `canAccessAdminArea` |
| Instellingen / Settings → Labels | `…/labels` | ✓ | ✓ | `canReadCustomerArea` |

So a BUILDING_MANAGER sees exactly three: Overzicht, Contactpersonen,
Labels — the same three pages the pre-FE-6 submenu gave them.

---

## 3. Enforcing gate per surface (FE helper + backend function)

| Surface (route) | FE gate — admits | Backend enforcement |
|---|---|---|
| Dashboard (`/`) / Start | none | every KPI / list endpoint scoped per role: `scope_tickets_for`, `scope_extra_work_for`, notification recipient scope |
| Tickets (`/tickets`), ticket detail, melding create | none; customer role redirected to `/my/meldingen` on the list | `accounts.scoping.scope_tickets_for` in every `get_queryset`; melding create through the ticket-create endpoint |
| Werkplanning (`/agenda`) | `canAccessAgenda` | STAFF → `tickets.views_staff_assignments.StaffAssignmentSlotAgendaView` (own slots) and the work-plan endpoint (`tickets/work_plan.py`); management roles → `?scope=company` through `scope_tickets_for` / `scope_extra_work_for` |
| Meerwerk (`/extra-work*`) | `canAccessExtraWork` | `extra_work.scoping.scope_extra_work_for` (STAFF → `.none()`); customer-side actions through `customers.permissions.user_can` |
| Terugkerend werk (`/planned-work*`) | `canAccessPlannedWork` | `planned_work.permissions.IsProviderManager` (403s STAFF and CUSTOMER_USER on every route) |
| Rapporten (`/reports*`) | `canAccessReports` | provider-management gate on every `/api/reports/*` view |
| Facturen (`/invoices*`) | `canAccessBilling` (BM read-only) | invoicing views: reads for provider management, mutations for `isProviderAdmin` |
| Klant-facturen (`/my/facturen*`), Documenten (`/my/documents`) | `CustomerRoute` | customer-scoped invoice / document endpoints |
| Contracten (`/admin/contracts*`) | `canAccessContracts`; writes `canManageContracts` | contracts views: provider management reads, provider admin writes |
| Uren (`/admin/hours`) | `canManageTimesheets` | timesheet admin endpoints gated to provider admin |
| Mijn uren (`/my-hours`) | `canAccessTimesheets` | own-entries scoping on `/api/timesheets/entries/` |
| Klanten (`/admin/customers*`) | list + read tabs `canReadCustomerArea`; write tabs `canAccessAdminArea` | customer viewsets: provider-admin write gates; BM scoped to assigned buildings on reads |
| Gebouwen, Bedrijven, Diensten & catalogi | `canAccessAdminArea` | admin viewsets gated by provider-admin permission classes (company create / reactivate SA only) |
| Mensen (`/admin/people/:tab`) | tab gates (users + invitations `canAccessAdminArea`; employees provider management) | `CanManageUser` on user writes; employees directory scoped to the caller's company |
| Medewerker-aanvragen | `canAccessStaffRequestReview` | review viewset: SA / CA everywhere, BM scoped to assigned buildings |
| Auditlog | `canAccessAuditLogs` | `audit/views.py::IsSuperAdmin` |
| Waarschuwingen (`/admin/sla-warnings`) | `canManageSlaWarnings` | company-scoped threshold endpoints, provider admin only |
| Berichten (`/inbox`), Notificaties | none | `tickets.permissions.filter_messages_visible_to`; notifications recipient-scoped |
| Instellingen (`/settings`) | none | self-scoped |

---

## 4. Werkplanning note (Sprint #111, still true)

`/agenda` is one route whose surface is role-adaptive. STAFF see their own
dated slots (`TicketStaffAssignment` — only STAFF can hold a slot; the
assign endpoint rejects any other role). BUILDING_MANAGER, COMPANY_ADMIN
and SUPER_ADMIN see the team week (`agendaShowsTeamWeek` =
`isProviderManagementRole`; the server has admitted `?scope=company` for
all three since Sprint 170 §1). Three distinct concepts, not to be
conflated: a staff **slot** (`TicketStaffAssignment`), a ticket's
**assigned manager** (`Ticket.assigned_to`) and a **responsible manager**
(`TicketManagerAssignment`, M:N); the BM `?my_managed=1` filter is the
union of the last two.
