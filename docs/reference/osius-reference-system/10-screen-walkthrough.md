# 10 — Screen walkthrough of the Osius reference system

**What this is.** Every screen in the reference system (`crm-web`), in nav order,
described as *behaviour a user sees*: what the page is for, what a person does
there, what each list shows and how it is filtered when you land on it, what
each modal asks for, and what the server actually does when the button is
pressed.

**Why it exists.** Files `00`–`09` were written to answer specific questions
(the EW ↔ invoice spine, hours, pricing, permissions). They are organised by
*subsystem*. Fourteen waves later we were still finding whole behaviours by
accident, because nobody had ever enumerated the *screens*. This file is that
enumeration. It is written from the route table down, not by clicking around,
so it cannot miss a screen the way clicking can.

**This file prescribes nothing.** It ranks nothing, proposes nothing and
recommends nothing. The `**Ours:**` line under each screen is a factual
statement of what our system does or does not have, and — where it is possible
to say factually — what turns on the difference. Deciding what to build from
that is the owner's and the architect's job, not this document's.

---

## 0. Method and rules of evidence

Two reference repositories were cloned fresh on 2026-08-22:

| Repo | Role |
| --- | --- |
| `goktugyilx200/crm-web` | The React SPA. **This is the authority for what a screen is.** |
| `goktugyilx200/crm-acl_srv-v1.1-review` | The Laravel API. Read **only** to answer "what happens when you press the button". |

Order of work, deliberately: `src/routes/router.jsx` and `src/routes/sitemap.js`
were read **first** and every mounted route enumerated (Appendix A) before any
page file was opened.

The live dev system (`https://dev-api.osius.nl/api`) was used **GET-only**, to
confirm what a screen shows with real data. Every live figure in this document
is a response actually received today; no POST/PUT/PATCH/DELETE was issued.
Endpoints touched are listed in Appendix B.

Claims are anchored one of three ways:

- `path/to/file.jsx:LINE` — read from source.
- `GET /endpoint → …` — quoted from a live response today.
- Neither → it is marked as an inference and says so.

**The `Ours:` lines were checked against our code, not against CLAUDE.md.**
That distinction is not pedantry. My first pass wrote the `Ours:` column from
the project doc and the route list, and it was **wrong in nine places** — every
one of them in the same direction, claiming we lack something we have. The
corrected list is in §12.4. Every `Ours:` line below now carries a file or a
route from `feat/ew-gap-closing` @ `94d5605`.

**Template noise warning.** `crm-web` is built on a purchased MUI admin template
(Aurora-family). `src/pages/` still contains the template's demo pages — kanban,
e-commerce, CRM deals, social, pricing tables, calendar. Almost all of those
routes are commented out in `router.jsx`. Section 6.4 lists the survivors so
nobody mistakes a template leftover for a designed screen.

---

## 1. The shape of the application

There is **one SPA and one component set**, mounted three times behind three
different guards (`src/routes/router.jsx:424`, `:811`, `:906`):

| Area | Guard | Roles allowed | Source |
| --- | --- | --- | --- |
| `/admin/*` | `AdminGuard` | `admin` | `components/guard/AdminGuard.jsx:9` |
| `/portal/*` | `CustomerGuard` | `customer`, `admin` | `components/guard/CustomerGuard.jsx:9` |
| `/work/*` | `EmployeeGuard` | `employee`, `admin` | `components/guard/EmployeeGuard.jsx` |

`RoleGuard` (`components/guard/RoleGuard.jsx:48`) is a flat
`allowedRoles.includes(userRole)` test; failure is `<Navigate to="/" replace />`,
i.e. bounce to the dashboard, never a 403 screen.

The same component renders in all three areas. Which of the three you are in is
derived **from the URL**, not from the session:
`location.pathname.startsWith('/admin/') ? '/admin' : …`
(`pages/finalosius/extra-works/index.jsx:36-45`). Every "back" and "open detail"
navigation is rebuilt with that prefix.

**Eight roles exist on the server, three are routed on the web.**
`GET /admin/roles` today returns 8: `admin`, `customer`, `customer_employee`,
`employee`, `location_manager`, `location_chef`, `customer_manager`,
`contact_person`. The API has a dashboard endpoint for each
(`routes/api.php:246-278`: `/customer/dashboard`, `/customer-employee/dashboard`,
`/location-manager/dashboard`, `/location-chef/dashboard`,
`/customer-manager/dashboard`, `/employee/dashboard`,
`/contact-person/dashboard`). The web guards only recognise three of them.
Reading `MenuProvider.jsx:92` and the guards together, a `location_manager` user
would get a nav whose links are prefixed `/portal` (the fallback prefix for an
unrecognised role) and every one of those links would then be refused by
`CustomerGuard` and bounce to `/`. **Inference from source; not verified live** —
no non-admin credential was available.

`GET /admin/role-types` returns only 4 rows (`admin`, `customer`, `management`,
`contact`), so `role_types` and `roles` are two different tables with different
contents on the dev box.

**Ours:** we have one area, not three; role and scope decide what renders, and
the URL is the same for everyone. We have no role whose links resolve to a
guard that refuses them.

---

## 2. Chrome present on every screen

`layouts/main-layout/` — sidenav (or topnav, user-switchable) + app bar.
The app-bar right-hand cluster is exactly four things
(`layouts/main-layout/common/AppbarActionItems.jsx:19-21`):

1. **Language menu** — the app is multilingual at the *data* level, not just the
   UI: lookup rows carry `label_tr/label_en/label_bg/label_nl`
   (`GET /admin/role-types` shows all four), and list endpoints take
   `?language=nl`.
2. **Notification centre** — a websocket-live dropdown with a connected/offline
   chip and **five tabs**: All, Unread, Personal, General, System
   (`components/socket/NotificationCenter.jsx:282-286`).
3. **Profile menu** — avatar upload inline (5 MB cap,
   `ProfileMenu.jsx:92`), Preferences, Account settings, Help centre, Sign out.
4. **Theme toggler.**

There is no global search box in the app bar.

**Ours:** we have a notification bell and a profile menu. Language is also
switchable in-app, but from Settings rather than the app bar —
`SettingsPage.tsx:95-101` offers nl/en and saves it with
`PATCH /auth/me/ {language}` (`:194`). We have no websocket notifications and no
avatar upload.

---

## 3. The nav, exactly as coded

For **admin**, the nav is the hardcoded `routes/sitemap.js`
(`providers/MenuProvider.jsx:148-151`). Two sections, 20 items:

**Administration (11)** — Buildings · Customers · Contracts · Extra Works ·
Meldings · Invoices · **Services** (route `/admin/products`) · Users ·
**Schedule** (work-plan) · Reports · **Grades** (opens in a new browser tab,
badged "App").

**System (9)** — Employees · Contacts · Email · Lookup Tables ·
Product Categories · Product Units · Overtime Types · App Versions ·
Data Exports.

Seven further items are present but commented out in `sitemap.js`: Projects,
Weekly Projects, Project Planner (Projects/Tasks/Templates), Departments,
Customer Works, Extra Works V2, Invoices V2, Chat, Medewerker Hours,
Customer Products. **Their routes are still mounted** — see §6.

For **every non-admin role**, the nav is generated from the permission payload
returned by `/api/me` (`MenuProvider.jsx:39-115`). A module appears in the nav
**only if** `module.has_page && module.menu_visible && (can_list || can_view)`
(`:52-58`). That is Rule 6 ("if a role cannot use it, that role does not see
it") implemented once, centrally, from server data. Note that this only removes
*nav entries*; the route itself stays mounted and is still guarded by the
three-role `RoleGuard`.

Two nav items carry a second path for the portal (`portalPath`, consumed at
`sidenav/NavItem.jsx:49`): **Schedule** and **Reports**. Those are the only two
nav entries designed to be shared between admin and customer.

**Ours:** our nav is gated by permission keys in
`frontend/src/auth/` and hides what a role cannot use, which is the same
principle. We do not drive nav from a server-sent module list, so a new module
needs a frontend change as well as a backend one.

---

## 4. Screen by screen — Administration

### 4.1 `/` — Dashboard

`pages/finalosius/dashboard/index.jsx` (1315 lines).

One page: a **collapsible filter panel**, a row of **four stat cards**, then
**six charts**. Single data call: `GET /admin/meldings/dashboard`
(`:1079`).

The filter panel has nine fields in a fixed order (`:56-66`): start date, end
date, day-range, status, priority, type, category, department, reporter user.
Six of them are multi-selects (`:68-75`). Nothing applies until **Apply** is
pressed (`:738`); there is a **Reset** (`:720`) and an "Active filters (n)"
count with removable chips (`:1233`). All filters start empty.

The four stat cards (`:451-469`): **Total meldings**, **My queue**,
**Unassigned**, **Archived**.

The six charts (`:1179-1184`): tickets over time · by status · by priority ·
by department **and** status (stacked) · by category · by type trend.

Live today, `GET /admin/meldings/dashboard` returns
`{"type":2,"type_name":"Melding","total":6,"total_archived":1,"my_queue":0,"unassigned":6,…}`
— **the dashboard is scoped to Meldings (type 2) by the server**, not to all
work. There is no type switch on the page.

**Ours:** `DashboardPage.tsx` is a role-dependent landing page with counts and
recent items. We have no filter panel, no chart set, and no "my queue /
unassigned" split.

### 4.2 Buildings

**List** — `/admin/buildings`, `pages/finalosius/buildings/components/BuildingDataGrid.jsx`
(951 lines). A statistics strip (`GET /admin/buildings/statistics`, `:122`)
over a DataGrid (`GET /admin/buildings`, `:182`), page size 25.

Columns (`:381-585`): ID · Name · Address · City · Status · Type · Customers ·
Actions.

Filters (`:50-55`), **all empty on landing**: free-text search, city, type,
status, customer.

Toolbar: a single square **+** button; three further buttons appear **only when
rows are ticked** (`:645`, `:671`, `:697`) — **Bulk delete (n)**,
**Bulk assign customer (n)**, **Bulk email (n)**. Row click opens the detail
page; clicks on a checkbox, button or link are swallowed (`:622-637`).

**Detail** — `/admin/buildings/:id`, seven tabs (`detail.jsx:403-435`):
Overview · Rooms · Contracts · Customers · **Machine Planning** · Workers ·
Cost Distribution.

**Machine Planning** is the largest single feature in the reference system —
`buildings/modules/machine-planning/` is 30 files, the two biggest being 5487
and 5046 lines. The model is a four-level tree — **Machine → Ruimte (area) →
Onderdeel (part) → Taak (task)** — laid out over a **52-week** plan. It carries
its own **plan versions** (create/edit/select/summary modals), a weekly view, a
monthly view, a week-calendar view, a year calendar, an Excel-style table view,
an **import** modal, a **price matching** modal, an **auto-plan** modal and a
bulk-plan modal. This is his recurring-work engine, and it lives inside a
building, not as a top-level screen.

**Ours:** `BuildingsAdminPage` + `BuildingDetailPage` cover the list and the
detail. Our recurring work is `planned_work/` reached from `/planned-work`, a
top-level screen with a rule-based recurrence, not a per-building 52-week
machine/area/part/task tree with versioned plans. There is no equivalent to
plan versions, price matching, or the Excel import on our side.

### 4.3 Customers

**List** — `/admin/customers`, `customers/components/CustomerDataGrid.jsx`.
Filters (`:49-54`) all empty on landing: search, city, status, building.
Page size 25.

**Detail** — `/admin/customers/:id`, **eleven tabs** (`detail.jsx:387-439`):
Overview · Departments · Works Types · Locations · Contacts · Services ·
Contracts · Projects · Machines · Extra Works · Documents.

Two of those are structures we do not have as first-class objects:
**Departments** (`customer_department_id`) and **Works Types**
(`customer_works_type_id`). Both appear again as filters on the Extra Works
list, as grouping keys when raising invoices, and as report dimensions. They
are the customer's own internal breakdown, and they travel all the way to the
invoice.

**Sub-screens:** `/admin/customers/:id/profile` (a separate profile page with
its own header and tab set) and
`/admin/customers/:customerId/locations/:locationId` (a location detail page,
also mounted in `/portal`).

**Nav side-effect:** when you are inside a customer, the sidenav's *Customers*
item auto-expands and grows sub-items for that customer's locations
(`sidenav/SidenavDrawerContent.jsx:48-73`, `providers/DynamicSitemapProvider`).
The nav is context-sensitive to where you are.

**Ours:** `/admin/customers/:id` has 14 sub-routes (buildings, contacts,
contracts, documents, invoices, labels, meldingen, permissions, pricing,
quote-requests, reports, settings, tickets, users, chargeable, extra-work) —
comparable breadth, arranged as routes rather than tabs.

We **do** have the department and works-type axis, and it reaches the same three
places his does. Sprints 127/128 added them as per-customer label lists
(`types.ts:2505-2519`, `Department = WorkType = CustomerLabel`), managed at
`/admin/customers/:id/labels` (`CustomerLabelsPage.tsx:6`); they are filters on
the Extra Work list (`ExtraWorkListPage.tsx:508-509`, `:1525`, server-side);
Sprint 132 added the invoice granularity `PER_BUILDING_DEPARTMENT_WORK_TYPE`
(`types.ts:3333-3341`), which explicitly gives untagged work its own invoice
rather than dropping it; and `backend/reports/urls.py:304-316` serves
`extra-work-by-department/` with CSV and PDF exports. The difference is shape,
not presence: his are first-class customer sub-objects with their own status
lookups, ours are "pure labels — no state machine, no permissions of their own"
(`types.ts:2509`).

### 4.4 Contracts

**List** — `/admin/contracts`, `contracts/components/ContractDataGrid.jsx`
(1886 lines). Filters (`:61-67`) all empty: search, status, type, customer,
building. Two view toggles that are not filters: **monthly / yearly** (`:70`)
and **prices / hours** (`:73`) — the same grid re-expressed as money or as
labour.

**Detail** — `/admin/contracts/:id`, four tabs (`detail.jsx:365-386`):
Information · Projects · **Billing** · **Revisions**.

The **Billing** tab (`modules/ContractBillingTabPanel.jsx`) does not list
invoices. It **projects** them: from `billing_period`
(`monthly | quarterly | yearly | one_time`, `:363-365`), `billing_day`
(`:64`) and `billing_type` (`advance | arrears`, `:216`), it computes a table of
future invoice dates and period ranges, every row chipped **"planned"**
(`:322`). A person opens this tab to answer "when will this customer be
invoiced, and for what period".

The **Revisions** tab is a change history of the contract itself.

There is also `/admin/contracts/:contractId/projects/:projectId` and a
`ContractPlanningModal` (1789 lines) with its own monthly Excel view and bulk
plan modal.

**Ours:** `/admin/contracts` and `/admin/contracts/:contractId` exist, with
hours tabs (`ContractHoursTab`, `ContractHoursApprovalTab`). We store the same
three inputs — `billing_period` and `billing_day` on the contract
(`backend/contracts/models.py:310`, `:315`) — and the detail page renders them
as fields plus a derived hours-per-year figure
(`ContractDetailPage.tsx:407-417`, `:596-600`). What we do not render is his
**projection**: a table of the next n invoice dates with their period ranges,
each chipped "planned". Nothing in our UI answers "when is the next invoice for
this contract due, and for which period".

### 4.5 Extra Works — the centre of the system

`/admin/extra-works` and `/admin/meldings` render **the same component**
(`router.jsx:634` and `:673` both mount `V2ExtraWorks`). The only difference is
derived from the URL: `location.pathname.includes('/meldings') ? 2 : 1`
(`extra-works/index.jsx:31`). Everything below is one screen serving two
business objects.

#### 4.5.1 The list

`components/ExtraWorkDataGrid.jsx` (1890 lines).

**A statistics bar of six buckets sits above the grid and IS the primary
filter.** Clicking a bucket sets `status_filter`; clicking the active one clears
it (`:346`). `GET /admin/extra-works/statistics?type=1&context=customer&language=nl`
returned today:

| Bucket | `filter_value` | Label (nl) | Count (type=1) |
| --- | --- | --- | --- |
| new | 1 | Nieuw | 16 |
| in progress | 2 | In behandeling | 5 |
| resolved | 3 | Interne goedkeuring | 1 |
| closed | 4 | Goedkeuring door de klant | 2 |
| archived | 8 | Voltooid | 8 |
| invoiced | 9 | Invoiced | 37 |

**The default is not "everything".** `getInitialFilters()` sets
`status_filter: 1` — "New status (1)" (`:108`). Measured today on the same
endpoint the grid calls:

```
GET /admin/extra-works?type=1&statuses=1  → total = 16   ← what you see on landing
GET /admin/extra-works?type=1             → total = 32
```

Half the list is hidden by a default the page does not announce beyond the
highlighted bucket.

**The grid is not one grid.** It renders three different things depending on
the active bucket:

- buckets 1–4 → the DataGrid (`:1631`);
- bucket **8 (Voltooid)** → `ExtraWorkCompletedGroupedView` (`:1596`) — rows
  collapsed into groups by customer / department / works-type, each group
  header showing item count and total hours and carrying its own
  **"Factureren"** button (`CompletedGroupedView:171-193`), plus an
  invoice-everything action across groups;
- bucket **9 (Invoiced)** → `ExtraWorkInvoiceGroupedView` (`:1587`) — rows
  grouped **by invoice number**, each header chipped with the invoice status
  (Concept / Verzonden / Betaald / Geannuleerd,
  `InvoiceGroupedView:47-51`) and offering "add another extra work to this
  invoice" (`POST /admin/invoices/{id}/items`, `:182`).

The columns also change with the bucket. The **date column re-labels and
re-sources itself** per bucket (`:921-966`): created_at for bucket 1,
planned start for 2/3, approved_at for 4, archive_approved_at for 8. On bucket
9 four extra columns appear (`:1051-1146`): invoice number, invoice status,
invoice date, invoice notes. Selection is disabled on bucket 9 (`:1631`,
`:1703`) — an invoiced row cannot be bulk-acted on.

Base columns: expand-toggle · ID · Status+Priority · Title (with unread-comment
badge) · Group · Category · Dept/Works-type · Customer · Building · Created by ·
date column · Pricing (incl. BTW).

Secondary filters (`components/ExtraWorkFilters.jsx`): search, customer,
building, category, department, works type, and a start/end date pair with an
"archive filters active" indicator.

**Grouping is visible in the list.** Rows can be group parents that expand to
child rows (`:423-430`, `:651-665`); children are not selectable. A group is the
unit a repeating extra work is created as (see 4.5.3).

**Two view modes** — Grid and Kanban — via `ViewSwitcher`, but the switcher is
hidden on buckets 8 and 9 (`:1369`).

**Row click is polymorphic:** on an invoiced row (`status_id == 9` with an
invoice) it navigates to the **invoice**, not the extra work (`:1202-1204`).

**Ours:** `ExtraWorkListPage` and `/tickets` are separate pages for separate
objects, each with its own filters. We have no statistics-bar-as-filter, no
grouped-by-invoice view, no per-bucket column set, and no default that hides
half the rows. We also have no Kanban.

#### 4.5.2 The Kanban view

`components/ExtraWorkKanbanView.jsx`. Status columns (New, In Progress, Pending
Approval, Completed, Archived), drag-and-drop between them, with **client-side
transition validation** (`:495-518`):

- 2 → 3 requires `hours_worked > 0`, plus `completion_notes` if
  `notes_is_required`, plus at least one attachment if `upload_is_required`;
- 1 → 2 requires planned start and end dates;
- 3 → 4 is explicitly free, "no validation needed";
- 4 → anything lower opens a **rejection modal** and routes through the
  `archive/reject` endpoint (`:561-577`).

When validation fails, the drop is not refused — a modal opens listing the
missing fields **and lets you fill them in place** (`KanbanValidationModal`),
then completes the move. That is the same shape as Rule 3, implemented on the
client.

#### 4.5.3 Creating one — `/admin/extra-works/add` and `/admin/meldings/add`

`extra-works/add.jsx` (2258 lines). One long form, not a wizard.

Initial state (`:92-116`): priority 1 (Low), status 1 (New),
`customer_start_date` **and** `deadline_at` both defaulted to **today**.

Required (`:830-885`): customer; building (once a customer is picked);
priority; **category — for Meldings only**; title.

Type-conditional fields: Extra Work gets `customer_department_id`,
`customer_works_type_id` and customer products; Melding gets `category_id`,
`user_department_id` and an **`is_customer_work`** checkbox (`:1362`) —
marking the melding as work the customer will do themselves.

The form has **two entry modes** for Extra Work (`:855`): `single` and
`multiple`. In `multiple` you pick days on a schedule grid, each day can hold
several time slots, and each slot can be individually customised with its own
title, description and product list (`dayCustomizations`, `:167`). Submitting
posts to `POST /admin/extra-works/batch` (`:1021`) and creates a **group**;
`single` posts to `POST /admin/extra-works` (`:1090`). Validation refuses to
submit if any time slot lacks an effective title (`:857-877`) or if `multiple`
is chosen with no days selected (`:880`).

Attachments: up to 8 files, plus images extracted out of the rich-text
description and uploaded separately (`:118-122`).

**Ours:** `CreateExtraWorkPage` has the same two-mode shape — `entryMode`
`SINGLE` / `MULTIPLE` with a `slots` array and a `batchCreateExtraWork` call
returning a `group` (`CreateExtraWorkPage.tsx:34`, `:342-345`, `:1322`), and it
refuses to submit `MULTIPLE` with zero slots exactly as his does. What we do not
have is his **per-slot override** of title, description and product list
(`dayCustomizations`), and we have no "the customer will do this themselves"
flag (`is_customer_work`).

#### 4.5.4 The detail page

`extra-works/detail.jsx` (1961 lines). A header card, a tab strip, and a
**sticky action bar pinned to the bottom of the viewport**
(`components/WorkflowActionsBar.jsx:517`).

Tabs, in order (`:1305-1390`): **Information · Files · Comments · Timeline**,
then conditionally **Financials** (Extra Work only), **Employee Hours**
(Extra Work only, hidden from customers), **User Assignments** (Melding only,
hidden when `is_customer_work`), **Customer & Building** (Melding only, admin
only, hidden when `is_customer_work`). The Comments tab carries an unread badge.

**The bottom bar is a state machine rendered as buttons** — the closest thing in
his system to Rule 5 ("a state is a sentence about the work, a button is a
verb"). By `status_id` (`WorkflowActionsBar.jsx:70-292`):

| Status | Extra Work shows | Melding shows |
| --- | --- | --- |
| 1 New | **Plan work** | **Start work** |
| 2 In progress | **Complete work** + Revert status | **Approve work** + Revert status |
| 3 Pending approval | **Approve & complete** + Revert status | same |
| 4 Completed | sentence "Work completed" + **Archive & approve** + **Reject archive** + Revert status | same |
| 5 Archive rejected | sentence "Archive rejected" + **Retry archive** + Revert to completed | same |
| 8 Archived | sentence "Work archived", **no buttons** | same |

Every button is `disabled={isCustomer}` — a customer sees the buttons greyed,
not absent. When `is_customer_work` is set on a Melding, the whole bar is
replaced by one sentence: "customer work pending" (`:58-68`).

Secondary actions on the right of the bar (`:389-460`): **Convert to Extra
Work** / **Convert to Melding** (each direction available from the other type),
**Link to project** (Melding only), and **Delete** — which exists **only at
status 1** (`:452`).

If the item belongs to a group, a third row appears (`:325-386`): one button per
actionable status in the group's distribution, e.g. "Plannen (4)",
"Voltooien (2)", which moves every group member at that status one step
forward.

**Ours:** `ExtraWorkDetailPage` / `TicketDetailPage` show transitions as buttons
too, and our `TicketTransitionModal` asks for what a transition needs.

We **do** have backward transitions, but as named pairs in the table rather than
a generic "revert one step": `PRICING_PROPOSED → UNDER_REVIEW`,
`CUSTOMER_REJECTED → UNDER_REVIEW`, and `COMPLETED → IN_PROGRESS`, the last of
which is provider-only and **requires an `override_reason`**
(`backend/extra_work/state_machine.py:91`, `:93`, `:108-111`). His "Revert
status" is one button available at four statuses that asks only for
confirmation.

We do not have: the **type-conversion pair** (`grep -ri "convert_to"` over our
backend returns nothing), or the **group bulk-advance row** — we create groups
but the detail page has no "move every group member at status X forward"
control. File classification we do have (see 8.4).

#### 4.5.5 `/admin/extra-works/dashboard`

A second, smaller dashboard scoped to extra works
(`GET /admin/extra-works/dashboard`, `dashboard.jsx:161`): four stat cards
(Total / My queue / Unassigned / Archived) and charts, with an Extra Work ↔
Melding toggle (`:352-357`). Mounted in **all three** areas
(`router.jsx:638`, `:855`, `:950`) but reachable only by URL — no nav entry.

### 4.6 Invoices

**List** — `/admin/invoices`, `invoices/index.jsx` (724 lines). **Two tabs**
(`:347-348`): **Facturen** and **Factureerbare Items**.

*Facturen* is a DataGrid: invoice number · customer · building · invoice date ·
subtotal · tax · total · notes · status · actions
(`components/InvoicesTable.jsx:389-525`).

*Factureerbare Items* is the unbilled pool: `GET /admin/invoiceable-items`
(`:176`) filtered by customer, **customer department**, **works type**, status
and type. Live today a row looks like:

```
{"id":562,"type":"project","entity_id":65,"customer_id":2054,"building_id":3022,
 "customer_department_id":58,"customer_works_type_id":null,"title":"bina projesi",
 "quantity":"1.00","unit_price":"400.00","subtotal":"400.00","tax_rate":"21.00",
 "tax_amount":"84.00","total":"484.00","status":"draft","invoice_id":null,
 "notes":"auto_generated_from_task", …}
```

So `invoiceable_items` is a **generic billable-line pool**, not an extra-work
list — this row's `type` is `project` and its note says
`auto_generated_from_task`. Only rows with status `draft`, `ready` or
`invoice_draft` are selectable (`:241`).

Raising invoices asks four things (`:292-297`): the selected item ids, a
**grouping** (`per_department | per_customer | per_project | manual`), an
invoice date, and a due date defaulting to **today + 30 days** (`:303`). The
modal shows a **live preview of how many invoices will result** for the chosen
grouping (`:262-281`) before you commit. `POST /admin/invoices/from-invoiceable-items`.

**Detail** — `/admin/invoices/:id`. Lifecycle and actions
(`components/InvoiceDetailActions.jsx`): statuses are
`draft → sent → paid | cancelled` (`:25-28`). Buttons are status-conditional:
**Send** and **Preview PDF** only on draft (`:284`, `:304`); **Download PDF** on
sent/paid/cancelled (`:318`); an overflow menu on sent/paid with
**Regenerate PDF**, **Revert to draft**, **Mark as paid**, **Mark as cancelled**
(`:359-380`).

**Ours:** `/invoices`, `/invoices/:id`, `FacturenPage`, `MyInvoicesPage`. Our
lifecycle is `DRAFT → ISSUED → SENT` with numbering assigned at send and
correction by reversal — a stricter model than `draft → sent → paid` with a
**revert-to-draft** available on a sent invoice.

We **do** have a grouping choice: `InvoiceGranularity` is
`CUSTOMER | PER_BUILDING | PER_BUILDING_DEPARTMENT_WORK_TYPE`
(`types.ts:3337-3341`), held as a per-customer default and applied on the
Facturen page (`FacturenPage.tsx:448-454`). Two real differences remain: his
grouping is chosen **per run** in the modal, ours is a **customer setting** the
run reads; and his modal shows a live count of the resulting invoices before you
commit (`invoices/index.jsx:262-281`), which we do not.

Our unbilled pool is extra-work-only. His is a generic billable-line pool fed by
projects and tasks as well — the live row quoted above has `type: "project"` and
`notes: "auto_generated_from_task"`.

### 4.7 Services — `/admin/products`

`products/index.jsx`. A deliberate **two-step screen** (`:12`): step 1 is a
table of **product categories** that have at least one product
(`:39`, categories with `products_count === 0` are filtered out); clicking one
opens step 2, the product list for that category. You cannot see all products at
once.

**Ours:** `/admin/services` is a single route exposing **both** the category
list and the service list as two tabs (`ServicesAdminPage.tsx:43`, `:157`), so
categories are a sibling view, not a gate you must pass through — and an empty
category stays visible. `/admin/catalogs` holds six further lookup tabs.

### 4.8 Users

**List** — `/admin/users`, `users/components/UserDataGrid.jsx`. One primary
button: **+ Add user** (`index.jsx:61`).

**The default filter here is the sharpest in the system**
(`UserDataGrid.jsx:65-71`):

```js
search: '', sourceType: 'contact', role: '', status: 1, department: ''
```

Measured today against the endpoint the grid calls:

```
GET /admin/users?source_type=contact&status=1  → total = 6   ← what you see on landing
GET /admin/users                               → total = 19
GET /admin/users?source_type=employee          → total = 13
```

**The Users page opens showing 6 of 19 users**, and the 13 it hides are exactly
the employees. Nothing on the page says so except the two dropdowns.

That default only makes sense once you know the next fact:

**A user is created *from* an existing employee or contact.** `+ Add user` opens
`UserCreationWizard` (`users/modules/UserCreationWizard.jsx`), a **seven-step
modal** (`:94-116`):

1. **User type** — employee or contact.
2. **Source selection** — pick the existing employee/contact record.
3. **Role selection.**
4. **Permission customisation** — a module × permission-bit matrix where you
   click cells to override the role's defaults; the header counts
   "n Overrides" and offers a reset (`Step3.5_PermissionMatrix.jsx:121-129`).
   The bits are `View, List, Create, Update, Delete, Restore, Export, Manage`
   (`users/modules/UserInfo.jsx:121`) — a bitmask per module.
5. **Password & settings.**
6. **Customer & building permissions (UCB)** — explicitly optional and
   skippable, with the text "You can skip this step and assign permissions later
   from the user profile" (`Step6_UCBPermissions.jsx:237`).
7. **Review & confirm.**

So identity (who this person is) and account (how they log in) are two separate
records, and the account is grafted onto the identity.

**Detail** — `/admin/users/:id` (3044 lines), **seven tabs**
(`detail.jsx:1422-1428`): Permission List · Melding Assignments · Extra Work
Assignments · Accessible Extra Works · **Assigned Buildings** (employees) /
**Customer Access** (contacts) · Activities · Granular Permissions.
The page carries an "Unsaved Changes" chip (`:1437`) and an "Override" marker
per row (`:1462`); Activities is a filterable audit view (activity type, from
date, to date, page size — `:2460-2501`).

**Ours:** `/admin/users`, `/admin/users/:id`, `/admin/users/:id/edit`,
`/admin/invitations`. We create a user directly and invite by email; there is no
employee/contact record that a login is attached to, so we have no equivalent of
the `source_type` axis — and no list that silently shows a third of its rows.
Our permission editor is a grouped key list (`PERMISSION_GROUPS`), not a
module × 8-bit matrix.

### 4.9 Schedule — `/admin/work-plan` (portal: `/portal/work-plan`)

`work-plan/index.jsx` (907 lines). A **week view** of everything due, one of the
two screens shared with the customer portal.

`GET /work-plan/weekly?week=YYYY-Www` (`:69`). Prev / Next / **This week**
(`:100-102`). Live today `?week=2026-W35` returned `weekDays` (seven days, each
with `date`, `dayName`, `dayShort`, `dayNumber`, `isToday`) and `workItems`
whose **first key is `overdue`** — the server, not the client, computes the
overdue bucket.

The page shows six count chips (`:288-346`): Total · **Overdue** · New ·
In progress · Completed · Archived, and three filters: type
(all / Melding / Extra Work), status, and free-text search across title,
customer label and building label (`:154`, `:215`). Overdue items also get their
own modal (`:59`).

**Ours:** `AgendaPage` at `/agenda`, and it **does** carry overdue: a count in
the overview line (`AgendaPage.tsx:488`, `:550-551`) and a dedicated overdue
panel opened from the page (`:328`, `:617`), with overdue items pulled into the
current week (`:26`). Two differences: his overdue bucket is computed **by the
server** and arrives in the payload, ours is derived alongside the week; and his
Schedule is one of only two screens deliberately shared with the customer
portal, whereas our agenda is a provider-side screen.

### 4.10 Reports — `/admin/reports` (portal: `/portal/reports`)

`reports/index.jsx`. A **catalogue**, not a report: searchable cards in three
categories (`:24-118`).

| Category | Report | Opens |
| --- | --- | --- |
| HR | Weekly employee hours | filter modal (`group_by=week`) |
| HR | Employee hours — extra works | filter modal (`group_by=employee`) |
| HR | Employee hours by building | full page `/admin/reports/employee-hours/by-building` |
| Operations | Extra works summary | filter modal |
| Operations | Extra works by building | filter modal |
| Operations | Extra works by department | filter modal |
| Meldings | Meldings by category & status | filter modal |
| Meldings | Meldings flat | filter modal |

Eight reports, six of them going through **one shared filter modal**
(`ReportFilterModal.jsx`). That modal asks (`:38-45`): date preset, **date from
(required)**, **date to (required)**, customer, building, **status (required
for Extra Works reports only)**, PDF page orientation (department report only),
and a checkbox **"exclude €0 items", ticked by default** (`:45`).

The status dropdown is hardcoded to two values (`:106-113`): **8 — "Wacht op
Factuur"** and **9 — "Gefactureerd"**, and **8 is preselected** (`:120-123`).
So the Extra Works reports are, by construction, invoicing reports: they ask
"what is waiting to be billed" or "what was billed", nothing else.

Each report produces **both PDF and Excel** — every entry has a paired
`/excel` endpoint (`:196-225`).

There are also three routed report pages not in the catalogue's modal flow:
`/admin/reports/employee-hours/weekly`, `/…/extra-works`, `/…/by-building`, and
a `/admin/reports/melding` page (`MeldingReport.jsx`, 1339 lines) reachable from
both `/admin` and `/portal`.

**Ours:** `/reports` and `/reports/hours-comparison`. We **do** have a report
catalogue — `REPORT_CARDS` at `ReportsPage.tsx:129`, rendered as cards at `:710`
— and we **do** have PDF output: `backend/reports/urls.py` registers
`export.csv` **and** `export.pdf` for the report families. Our catalogue is the
larger of the two: 24 report families under `backend/reports/urls.py`
(tickets over time / by building / by customer / by origin / by type, status
distribution, age buckets, SLA distribution, SLA breach rate over time, manager
throughput, meldingen by category, extra-work, extra-work by department,
extra-work revenue, extra-work revenue by building, employee hours weekly / by
building / by extra-work, employee hourly rates, hour sources, worker hours,
hours comparison, period report summaries, ticket report) against his 8.

Real differences: he funnels six of his eight through **one shared filter
modal** with the same fields every time; and that modal's two defaults —
status preselected to **8 "Wacht op Factuur"** and **"exclude €0 items" ticked**
— have no counterpart on our side.

### 4.11 Grades — a separate application

The nav entry opens `/grades` **in a new browser tab**, badged "App"
(`sitemap.js`, `openInNewTab: true`). It is a full cleaning-quality inspection
system with its own layout (`layouts/grades-layout`) and is *also* mounted under
`/admin/grades/*`.

**Dashboard** (`grades/dashboard/index.jsx`, 1349 lines) — three parallel calls
(`:90-92`): inspection statistics, the 10 most recent inspections, and the 10
next `scheduled` plans. Scores are banded **≥80 Goed / ≥60 Voldoende /
else Onvoldoende** (`:52-54`), and findings are typed into four categories:
**Vuil · Methode · Periodiek · Overig** (`:59-62`).

**Templates** — reusable inspection checklists with categories
(`GradesTemplateFormModal`, `GradesTemplateCategoryModal`).

**Plans** (`plans/index.jsx`, 939 lines) — a **building × month matrix**. Each
cell is a planned inspection; clicking an empty cell creates one, clicking a
filled one edits or deletes it (`:258`, `:265`, `:297`), and a plan can be
turned into a live inspection on the spot (`POST /admin/grades/inspections`,
`:315`). Status per cell is `draft | scheduled | completed | cancelled`, with
**`overdue` computed client-side** from the date when the stored status is
neither completed nor cancelled (`:105-120`).

**Inspections** (`inspections/index.jsx`, `detail.jsx` 1838 lines) — statuses
`planned | started | in_progress | completed | cancelled` (`:50-54`). Filters
default to `status: 'all'` and **`year: current year`** (`:81-89`) — the only
list in the system that defaults to a time window. The detail page walks rooms:
toggle a room into the inspection, mark it reviewed, add **findings** with
photos, then `PUT status: 'completed'` (`:521`). There is a VSR-DKS grid view
and a fullscreen mode.

There is a **mobile-only** Grades API (`routes/api.php:2522-2536`) letting an
inspector list buildings and templates, **create their own plan** (self-assign),
delete their own plan, reschedule an inspection, and view a building's annual
plan. The inspector's primary client is the phone.

**Ours:** nothing. We have no inspection, quality-scoring or finding concept at
all — no template, no plan matrix, no room walk, no score.

---

## 5. Screen by screen — the System section

| Screen | What it is | Ours |
| --- | --- | --- |
| **Employees** `/admin/employees` | List + detail with six tabs: Employee Information · Documents · Contracts · **User Accounts** · **Hourly Rates** · Assigned Buildings (`employees/detail.jsx:195-220`). Documents have types and an upload modal; hourly rates are per employee over time. | `/admin/employees` exists (`EmployeesAdminPage`), and we have labour rates (`LabourRatesTab`) and staff credentials (`StaffCredentialsSection`). Our `documents/` app is **customer-scoped** — `Document.customer` and `DocumentFolder` (`backend/documents/models.py:183-195`) — so there is no per-employee document shelf. There is no employee→user-account tab because we have no separate employee record: a user *is* the person. |
| **Contacts** `/admin/contacts` | List + detail with two tabs: Information · **User Accounts** (`contacts/detail.jsx:204-209`). A contact is a customer-side person; the account is grafted on. | We have customer contacts under `/admin/customers/:id/contacts`, not a top-level directory. |
| **Email** `/email` | A real mailbox, not a log. Three sections (`data/email.jsx`): **Inbox** (inbox, unread, important, archived, deleted), **Logs** (sent, failed, pending, sent-important, sent-archived, sent-deleted), **Templates** (general, contact, employee, user, auth). Backed by `mail/`, `mail-templates/`, `mail-groups/`, `mail-logs/` (`routes/api.php:1211-1336`) including IMAP **fetch-now** (`:1335`), template preview/duplicate/variables, and mail groups with member import. | `NotificationsPage` and `backend/notifications/` send mail and keep a `NotificationLog`. We have no inbox, no IMAP, no editable templates in the UI, and no mailing groups. |
| **Lookup Tables** `/admin/lookup-tables` | An index of **18** editable lookup tables (`lookup-tables/index.jsx:55-192`), colour-grouped into Building / Employee / Customer / Contact / Room / Contract / General. Each is its own route and CRUD page: building types, statuses, floors; employee statuses, document types, contract types; customer statuses, department statuses, works-type statuses; contact email statuses; room statuses, user types, section types; floor types; role types; ticket categories; service line types; service types. | `/admin/catalogs` covers a smaller set (ticket categories, work types, building types, hour types, labour rates). Most of his 18 have no counterpart because the underlying object does not exist on our side. |
| **Product Categories** `/admin/product-categories` | CRUD. | Part of `/admin/services`. |
| **Product Units** `/admin/product-units` | CRUD — the unit a priced line is measured in. | We have `unit_type` on a priced line (`backend/extra_work/models.py:983`), but as a field on the line, not as an admin-managed catalogue. |
| **Overtime Types** `/admin/overtime-types` | CRUD, each with a **multiplier** shown as e.g. `1.5×` (`worker-hours/index.jsx:1125`). Every hour entry carries an `overtime_type_id`. | `HourTypesTab` under `/admin/catalogs`. |
| **App Versions** `/admin/app-versions` | Version control for the **mobile apps** — per platform, with a `latest/{platform}` endpoint (`routes/api.php:1866`). Its presence is the plainest evidence that a phone app is a first-class client. | Nothing. We have no mobile app. |
| **Data Exports** `/admin/data-exports` | **GDPR subject-access requests with admin approval.** A request has a status; `pending_approval` rows get **Approve** and **Reject** buttons (`data-exports/index.jsx:382-400`), any row can be **previewed as JSON** or **downloaded as PDF** by an admin regardless of status (`:363-380`), and an admin can raise an export *for* a user (`POST /admin/data-exports/create`). Statistics strip, status filter, expiry date column. | Nothing. We have no subject-access-request flow at all. |

---

## 6. Mounted but not in the nav

These routes exist and render. Nothing in the sidenav leads to them; you reach
them by URL or by a link from another screen.

### 6.1 Commented out of the nav, still routed

| Route | What it is |
| --- | --- |
| `/admin/departments` | Provider-side departments list. |
| `/admin/customer-works` | Customer works list. |
| `/admin/customer-products` | Per-customer price list, with a **version manager** modal (`customer-products/modals/CustomerProductVersionManager.jsx`, 1204 lines) and an add modal (1077 lines). Also mounted in `/portal` and `/work`. |
| `/admin/extra-works-v2` (+ `/add`, `/:id`, `/continuous/:id`) | A **second, parallel extra-work system**, schedule-first. Its list has three view modes — **Grid · Agenda · Doorlopend (continuous)** (`extra-works-v2/index.jsx:445-455`) — and per-status count columns (New / Planned / Completed / Approval / Invoiced) on each row. Its detail has seven tabs: Informatie · **Schedules** · Medewerkers · Financieel · Bestanden · Opmerkingen · Tijdlijn (`detail.jsx:701-739`). |
| `/admin/extra-works-v2/continuous/:id` | Continuous (ongoing) work, split into **periods**. Adding a worker asks for: which employees, **which weeks (all, or a chosen subset)**, **working days**, **daily hours** (default 8) and **overtime type**, and posts `auto_add_to_periods: selectedWeeks === 'all'` (`ContinuousWorkersTab.jsx:246-258`). That flag is the "fill every period automatically" switch. |
| `/admin/invoices-v2` (+ `/:id`) | The invoice system for Extra Works V2: `/admin/extra-work-v2-invoices`, with its own send and **duplicate** actions (`invoices-v2/index.jsx:189`, `:217`) and its own Invoices / Invoiceable Items tab pair. |
| `/admin/worker-hours` and `/admin/worker-hours/approval` | See 6.2. |

### 6.2 Worker Hours — the hours approval screens

`worker-hours/index.jsx` (1770 lines) — an **employee × week** grid.
`GET /admin/worker-hours/employee-overview` for a chosen ISO year + week
(`:134`), defaulting to the current week (`:82-83`). Filters: worker, status,
overtime type, building.

Summary chips (`:994-997`): *n medewerkers · n u totaal · n goedgekeurd ·
n concept*. Rows expand to per-source detail; hours are edited in a modal as
**overtime type × day-of-week** cells (`:107-110`).

Actions: approve all sources for an employee
(`POST /admin/worker-hours/approve-employee-all-sources`, `:475`), revert them
(`:504`), approve or revert a single source (`:763`, `:882`), update source
hours (`:669`). **Reverting asks for a reason** — the approval page's field is
literally labelled `"Correction Reason (required)"` (`approval.jsx:605`).

`worker-hours/approval.jsx` is the second view: a **pending summary** across
sources (`GET /admin/worker-hours/pending-summary`, `:116`) with per-week
approve / submit / revert (`:194`, `:220`, `:246`) and a
Draft / Submitted / Approved / Rejected count strip (`:391-398`).

So the hours lifecycle is **draft → submitted → approved**, per employee, per
week, per source, with a reasoned revert.

**Ours:** `/admin/hours` (`HoursAdminPage` with overview, charts, filter row)
and `/my-hours`. We **do** have a three-state review with a submit step, but on
a different object: `ContractHoursStatus` is `DRAFT → SAVED → APPROVED`
(`backend/timesheets/models.py:515-551`), with `SAVED → DRAFT` ("send back for a
correction") and `APPROVED → SAVED` ("reopen, clears the approval") —
`ContractHoursApprovalTab.tsx:101-104`. That is the lifecycle of a **standing
agreement**, not of a week of worked hours. His grid reviews the actual worked
hours, per employee, per ISO week, per **source**, and requires a
`Correction Reason` to revert (`approval.jsx:605`). We have no per-week,
per-source approve/revert over worked time and no required correction reason.

### 6.3 The PRJ module and Projects

Two separate project systems are mounted:

- **Projects** — `/admin/projects`, `/create`, `/:id`, `/:id/edit`. Building-
  based project/budget tracking, with a `POST /admin/projects/{id}/refresh`
  (`detail-project.jsx:112`).
- **PRJ (Project Planner)** — `/admin/prj-projects` (+ `/:id`),
  `/prj-projects/weekly-planning`, `/monthly-planning`, `/week-plan`,
  `/weekly-projects`, `/admin/prj-tasks` (+ `/:id`),
  `/admin/prj-task-templates` (+ `/:id`). Centralised cross-project 52-week
  planning; the project detail carries planning, plan-groups, plan-assignments
  and a financial tab (`prj-projects/tabs/`, 3293 + 2890 + 2554 lines).

**Ours:** no project object at any level.

### 6.4 Template leftovers still mounted

`/pages/notifications`, `/pricing/column`, `/pricing/table`, `/coming-soon`,
`/faq`, `/faq/:category`, `/email/*`, `/admin/file-manager`, `/health`,
`/healthz`, `/health.json`. Everything else from the template (kanban, boards,
CRM deals/leads, social, calendar, scheduler, e-commerce) is commented out in
`router.jsx`. **Do not read these as designed screens.**

---

## 7. The customer portal and the employee area

Both are the same components behind a different guard, with **no portal-specific
screen anywhere**.

**`/portal/*` — 13 routes** (`router.jsx:811-903`): buildings (+ detail),
customers (+ detail, + location detail), contacts (+ detail), extra-works
(+ dashboard, + add, + detail), meldings (+ add, + detail), products,
customer-products, reports (+ reports/melding), work-plan.

**`/work/*` — 11 routes** (`router.jsx:906-983`): the same minus reports and
work-plan.

What the portal does **not** have: invoices, users, employees, contracts,
grades, worker hours, lookup tables, data exports.

How a customer's experience differs, mechanically:

- **Nav** — generated from their permission payload; a module without
  `menu_visible` or without `can_list`/`can_view` simply is not there
  (`MenuProvider.jsx:52-58`).
- **Tabs** — Employee Hours and Customer & Building are not rendered for
  `isCustomer` (`extra-works/detail.jsx:1360`, `:1379`).
- **Actions** — every workflow button in the bottom bar is rendered but
  `disabled` for a customer (`WorkflowActionsBar.jsx:88`, `:120`, `:139`, …).
  Rule 6 is followed for tabs and nav, and **not** followed for the action bar:
  a customer sees greyed-out verbs they can never use.
- **Raising work** — a customer *can* reach `/portal/meldings/add` and create a
  melding; the `is_customer_work` checkbox is on that form.

**There is no customer decision surface.** There is no endpoint a customer can
call to approve or reject an extra work: the EW route block
(`routes/api.php:700-785`) has no customer-approval action, and every write is
`ucb.permission:extra_works,update`. Status 4's label on the dev box is
"Goedkeuring door de klant" (customer approval), but nothing in the UI or API
lets a customer give it — it is approved by staff on the customer's behalf.

**Ours:** we have one area with role-scoped rendering, customer users with
`customer.*` permissions, and H-5 as a hard invariant — STAFF **cannot** take
customer-side decisions. That is the single largest behavioural difference
between the two systems, and it runs in the opposite direction from his.

---

## 8. Modal inventory — what is asked, and when

### 8.1 Extra Work / Melding workflow modals

`extra-works/modals/` holds **19** modal components, 11 043 lines. The ones a
person meets in the normal flow:

| Modal | Appears | Asks for | Required |
| --- | --- | --- | --- |
| **Plan work** (`ExtraWorkPlanModal.jsx`, 678 ln) | status 1 → 2, Extra Work | Start date, end date, **budget hours**, coordinators (multi), workers (multi), and two checkboxes under "Completion requirements": **file upload required** and **completion notes required** | start + end date (`:148`) |
| — its confirm step | after Plan | a second confirmation modal before submit (`:57`, `:657`) | — |
| **Start work** (`ExtraWorkStartModal.jsx`, 277 ln) | status 1 → 2, Melding | confirmation only; `PUT /admin/extra-works/{id}` (`:36`) | — |
| **Complete work** (`ExtraWorkCompletionModal.jsx`, 871 ln) | status 2 → 3 | completion notes, up to 4 images in slots, plus a shown summary of employee hours | **hours worked always**; notes if `notes_is_required`; upload if `upload_is_required` (`:59-60`) |
| **Approve & complete** (`ExtraWorkApprovalModal.jsx`, 981 ln) | status 3 → 4 | approval notes, budget hours, and an **editable financials table** — add/edit/delete product lines with live subtotal/VAT/total, then everything is saved on approval | **approval notes always** — "Approval notes are required" (`:154`) |
| **Archive & approve** | status 4 → 8 | archive approval notes | optional (`ExtraWorkBulkArchiveApproveModal.jsx:8`) |
| **Reject archive** | status 4 → back | **archive rejection reason** | **required, client and server** (`ExtraWorkBulkArchiveRejectModal.jsx:73`) |
| **Revert status** | statuses 2/3/4/5 | plain confirmation (`detail.jsx:1516`) | — |
| **Convert to Extra Work / Melding** | any | plain confirmation (`detail.jsx:1860`, `:1875`) | — |
| **Delete** | status 1 only | plain confirmation (`detail.jsx:1845`) | — |
| **Group edit / Group bulk edit** | grouped items | `GroupEditModal` (468 ln), `GroupBulkEditModal` (1259 ln) | — |

Plus bulk variants of nearly all of the above, each an **Excel-like horizontal
table with one row per selected work** and a per-row input: bulk plan, bulk
complete, bulk approve, bulk archive-approve, bulk archive-reject, bulk invoice,
bulk all-invoice, bulk delete, bulk convert-to-melding. The reject variant
validates a reason **per row** (`:73`).

Also: `ScheduleDaysModal` (610 ln), `EditDayModal`, `EditProductModal`
(770 ln), `EmployeeHoursDistributionModal` (922 ln).

### 8.2 What the server actually enforces

This is where his system and Rule 3 part company.

**`PUT /api/admin/extra-works/{id}/status`** (`ExtraWorksController.php:3621`)
validates exactly this:

```php
'status_id' => 'required|exists:t_ticket_status,id',
'note'      => 'nullable|string|max:1000',
'images'    => 'nullable|array',
```

**Any status may be set from any status.** There is no allowed-transition table.
`hours_worked`, `completion_notes` and attachments are **not** checked, even
when `upload_is_required` / `notes_is_required` are set on the row. The
completion requirements are a **client-side contract only** — enforced by the
completion modal and by the Kanban validator, and bypassable by any other
caller, including the mobile app.

The **one** server-enforced workflow requirement in the extra-work lifecycle is
the archive rejection reason. `POST /admin/extra-works/{id}/archive/reject`
(`:2716`) requires `status_id` and returns **HTTP 400 "Rejection reason is
required"** when the reason is empty (`:2729-2735`). It also **appends** every
rejection rather than replacing, stamping each as
`[YYYY-MM-DD HH:MM:SS] #n reason` (`:2745-2753`), and clears the archive-approval
fields.

A status change fans out a Firebase push to every user with a UCB permission on
the item's customer-buildings plus every assigned user (`:3658-3682`).

The comment on `rejectArchive` also records a design decision worth quoting:
*"'Rejected' status is NO LONGER USED — rejection tracked via
`archive_rejected_by` / `archive_rejected_at` / `archive_rejection_reason`.
Status must be explicitly provided."* Rejection is a **flag set plus a status you
choose**, not a state.

**Ours:** `backend/tickets/state_machine.py` `ALLOWED_TRANSITIONS` is the
authority, every mutation writes a `*StatusHistory` row inside the same
transaction, and a provider-driven customer-side transition returns HTTP 400
`override_reason_required`. Our server refuses; his mostly does not.

### 8.3 Modals elsewhere

- **Buildings:** building form, bulk assign customer, **bulk email** (1641 ln),
  bulk project, project detail, add project line — plus the entire
  machine-planning modal set (plan version create/edit/summary, machine import,
  price matching, quick machine add, quick task add, bulk area/part/task/machine
  add, bulk edit tasks, auto-plan, bulk plan, delete-all).
- **Contracts:** contract modal, **contract planning** (1789 ln), project add,
  project line add, contract bulk plan.
- **Users:** the 7-step creation wizard, plus `Modals.jsx` (1248 ln) including a
  set-password dialog with a live rule checklist.
- **Grades:** template form, template category, plan form, room selection, add
  room, **finding** (photo + category + note), room-category mapping, VSR-DKS
  fullscreen.
- **Reports:** the one shared `ReportFilterModal`.
- **Invoices:** edit invoice, edit item, and the create-invoices modal with its
  grouping preview.
- **Data exports:** detail, preview (JSON), reject (with reason).

### 8.4 One detail worth isolating: file classification

Attachments on an extra work are classified three ways and rendered in three
separate sections (`modules/ExtraWorkFilesTab.jsx:399-402`, chip at `:121`):

- **PRE-FILE** (`is_pre_file = 1`) — attached when the work was raised;
- **POST-FILE** (`is_pre_file = 0`) — uploaded after work started (`:321`);
- **DRAFT** (`is_draft`) — staged, not yet committed.

The counter reads `Draft: n • Pre: n • Post: n` (`:426`). The client sends
`files: [{id, is_pre_file}]` and the server honours it
(`ExtraWorksController.php:735-756`).

**Ours:** we **do** classify. `AttachmentPhase` is
`UNSPECIFIED | BEFORE | AFTER` (`backend/tickets/models.py:875-886`), and its
docstring is explicit that it is "a label, and only a label: no queryset filters
on it, no permission reads it". His is `is_pre_file` + `is_draft`, and it does
drive layout — three separate sections and a `Draft: n • Pre: n • Post: n`
counter. The concept is shared; the DRAFT (staged, uncommitted) third state and
the sectioned rendering are his alone.

---

## 9. What each list shows when you land on it

The single most under-documented behaviour in his system. Measured from source;
totals from live GETs today.

| Screen | Default filter as coded | Effect |
| --- | --- | --- |
| **Extra Works / Meldings** | `status_filter: 1` (New) (`ExtraWorkDataGrid.jsx:108`) | 16 of 32 rows for type 1 |
| **Users** | `source_type: 'contact'`, `status: 1` (`UserDataGrid.jsx:65-71`) | **6 of 19 rows** — all 13 employees hidden |
| **Buildings** | all five filters empty (`BuildingDataGrid.jsx:50-55`) | everything, 25/page |
| **Customers** | all four filters empty (`CustomerDataGrid.jsx:49-54`) | everything, 25/page |
| **Contracts** | all five filters empty (`ContractDataGrid.jsx:61-67`); view mode **monthly**, values **prices** | everything, 25/page |
| **Invoices** | tab **Facturen**; Invoiceable Items tab unfiltered | everything |
| **Grades — inspections** | `status: 'all'`, **`year: current year`** (`inspections/index.jsx:81-89`) | this year only |
| **Grades — plans** | matrix for the year in context | — |
| **Worker Hours** | **current ISO year + week** (`worker-hours/index.jsx:82-83`) | this week only |
| **Schedule (work plan)** | **current week**, type `all`, status `all` (`work-plan/index.jsx:53-57`) | this week only |
| **Dashboard** | no filters applied; server scopes to type 2 | Meldings only |
| **Reports filter modal** | status **8 "Wacht op Factuur"** preselected; **"exclude €0 items" ticked** (`ReportFilterModal.jsx:45`, `:120-123`) | uninvoiced, non-zero |
| **Services (products)** | categories with `products_count > 0` only (`products/index.jsx:39`) | empty categories invisible |

Three shapes of default are in use, and they are not applied consistently:
**"everything"** (the master-data lists), **"the current time window"**
(anything week- or year-shaped), and **"the bucket you probably want"** (Extra
Works, Users, the reports modal). The third kind is the one that hides rows
without saying so.

**Ours:** our Extra Work list defaults to **ALL**, and the code says why in as
many words: *"a FILTER, never a mode. Default ALL, and it is visible and
clearable: the owner was explicit that planned extra work must still be findable
if he changes his mind about planning it, so nothing may hide rows with no way
back"* (`ExtraWorkListPage.tsx:495-502`). The two places worth comparing
directly are therefore Extra Works and Users, where his defaults hide half and
two-thirds of the rows respectively, and ours hide none.

---

## 10. Questions his system asks that we do not

Stated as questions, with the screen that asks them. No judgement attached.

1. **"How should these hours be split across these workers?"** — the Plan modal
   takes budget hours plus a worker list and, on submit, writes one
   `hours/worker` record per worker at `hours ÷ workers` on the start date
   (`ExtraWorkPlanModal.jsx:180-198`). We ask for `budget_hours`
   (`backend/extra_work/models.py:628`) but never distribute it; ours is
   explicitly "a planning and control number ONLY: it reaches no price
   anywhere" (`:620-627`).
2. **"Is this melding work the customer will do themselves?"** —
   `is_customer_work` (`add.jsx:1362`). When set, the whole action bar collapses
   to one sentence and two tabs disappear.
3. **"What is the title, description and product list for *this* time slot?"** —
   in `multiple` mode each slot can be individually customised
   (`dayCustomizations`, `add.jsx:167`), and submission is refused if any slot
   lacks an effective title (`:857-877`). We have the same two-mode batch
   creation; we do not have the per-slot override.
4. **"Why are you rejecting this archive?"** — required, and **appended never
   replaced**, each entry timestamped and numbered
   `[YYYY-MM-DD HH:MM:SS] #n reason` (`ExtraWorksController.php:2745-2753`), so
   a work rejected four times carries all four reasons.
5. **"Why are you reverting these approved hours?"** — `Correction Reason
   (required)` (`worker-hours/approval.jsx:605`), on worked hours per week per
   source.
6. **"How many invoices will this produce?"** — the grouping choice itself we
   have; the live count of resulting invoices shown before you commit
   (`invoices/index.jsx:262-281`) we do not.
7. **"Which existing employee or contact is this login for?"** — step 2 of the
   user wizard. Identity first, account second. It is also what makes the Users
   page's `source_type` default possible.
8. **"Which of this role's default permissions do you want to override for
   this person?"** — step 4, a module × 8-bit matrix with an override count and
   a reset. We have per-user overrides too, over grouped permission keys rather
   than a bitmask.
9. **"Which customer-buildings may this user see?"** — step 6 (UCB), and it is
   explicitly **skippable** with "you can skip this step and assign permissions
   later" (`Step6_UCBPermissions.jsx:237`), i.e. a user may exist with no scope
   at all.
10. **"When is the next invoice due for this contract, and for which period?"** —
    the contract Billing tab's projected schedule. We hold the same inputs and
    do not project them.
11. **"Is this file staged or committed?"** — his `is_draft` third state; our
    `AttachmentPhase` has BEFORE/AFTER but no draft.
12. **"Which weeks should this worker be added to — all of them, or these?"**,
    together with working days, daily hours and overtime type — the
    continuous-work worker dialog and `auto_add_to_periods`
    (`ContinuousWorkersTab.jsx:246-258`).
13. **"Is this building clean, by which template, scored how, with what
    findings?"** — the entire Grades application. Nothing on our side.
14. **"Do you approve this user's request for their own data?"** — Data Exports.
    Nothing on our side; `grep -ri "gdpr\|data_export\|subject_access" backend/`
    returns no files.
15. **"Should this Melding become an Extra Work, or the reverse?"** — the
    convert pair (`routes/api.php:776-777`). `grep -ri "convert_to"` over our
    backend returns nothing: a ticket and an extra work are different objects
    for us and neither becomes the other.
16. **"Landscape or portrait?"** — asked before generating the
    extra-works-by-department PDF (`ReportFilterModal.jsx:529`).
17. **"Which machine, in which room, on which part, needs which task, in which
    of the next 52 weeks, under which plan version?"** — the machine-planning
    tree inside a building. Our `planned_work/` answers a rule-shaped version of
    the last part only.
18. **"Which app version is this phone on?"** — App Versions, and the whole
    `/api/mobile/*` surface behind it. We have no mobile client.

## 11. Questions we ask that his system does not

1. **"Do you, the customer, approve this?"** — we have a customer decision
   surface; he has none. His status 4 is *labelled* "Goedkeuring door de klant"
   but is set by staff.
2. **"You are overriding a customer-side decision — why?"** — our HTTP 400
   `override_reason_required` and `TicketStatusHistory.is_override`. His
   `updateStatus` accepts any transition with an optional note.
2a. **"Did the *customer* ask for photo proof, separately from what the provider
   asked at planning?"** — we ask the completion-requirement question twice,
   from two origins, and keep them as four columns rather than two:
   `file_upload_required` / `completion_notes_required` written by the provider
   at plan time, and `customer_requires_photo` (+ its pair) written by the
   customer at create time, because "folding them into one pair would make the
   last writer win" (`backend/extra_work/models.py:641-685`). The gate reads the
   **union** in `tickets/completion_requirements.py`. He asks it once, from one
   origin. More importantly — see §11.9 — his two flags are checked in the
   frontend only.
3. **"Is this transition allowed from the current state?"** — our
   `ALLOWED_TRANSITIONS`. His server has no transition table.
4. **"Which provider company is this?"** — we are multi-tenant with H-1/H-2
   cross-tenant invariants and a `companies/` app. His system is single-provider;
   there is no company object.
5. **"Is this invoice already sent?"** — our SENT invoices are immutable and
   corrected by reversal; his sent invoices offer **Revert to draft**.
6. **"Which SLA applies, and is it breached?"** — our `sla/` engine and
   `/admin/sla-warnings`. He has an "overdue" bucket on the work plan computed
   from deadline dates, and no SLA object.
7. **"Should a staff assignment be requested and approved?"** — our
   `/admin/staff-assignment-requests`. He assigns coordinators and workers
   directly in the plan modal.
8. **"What changed, by whom, on this record?"** — our generic `AuditLog` with
   H-10 ("every permission/role/scope change writes an AuditLog"). He has a
   per-user Activities tab and per-item system comments, not a generic audit
   write-path.
9. **The same question the server asks, not just the form.** Our completion
   requirements are stored on the model and enforced in one place, in the
   transition. The model comment says why, and names his system as the reason:
   *"ENFORCEMENT is deliberately not here. It belongs in the completion
   transition, in one place, for the reason the reference system demonstrates:
   over there both flags are checked in the frontend only, so the same work
   completed through the API skips the check entirely"*
   (`backend/extra_work/models.py:644-650`). §8.2 above is the independent
   confirmation of that claim, read from his controller today: `updateStatus`
   validates `status_id`, an optional note and optional images, and nothing
   else.

---

## 12. Where this prompt was wrong

The prompt asked me to verify the claims it made about his system and correct
them. Three points:

1. **"The ten-state portal vocabulary."** The lookup has **nine** rows, not ten.
   `GET /admin/extra-works/meta/config?language=nl` returns `statuses_data` with
   values 1, 2, 3, 4, 5, 6, 7, 8, 9 — nine statuses. Two of them are dead in the
   web UI: 6 (`customer_approval`) and 7 (`invoiced_v2`) never appear in
   `WorkflowActionsBar`, the statistics bar, or the Kanban columns. And the
   labels have drifted on the dev box: **3 and 5 both read "Interne
   goedkeuring"**, while **4 reads "Goedkeuring door de klant" but has slug
   `closed`**. The slug is the stable identifier; the label is editable data and
   currently contradicts it.

2. **"The archive request/approve/reject cycle."** There is no *request* step in
   the UI. The bottom bar at status 4 offers **Archive & approve** and **Reject
   archive** directly. `archive_requested_at` / `archive_requested_by` exist as
   columns, but `approveArchive` **backfills them itself** if they are empty
   (`ExtraWorksController.php:2655-2656`) — so in practice the request is
   synthesised at approval time, not raised by anyone. The cycle a user
   experiences is approve/reject, with retry from status 5.

3. **"crm-web IS THE SCREENS… you do not need the live system."** True for what
   a screen *is*. But two things are only knowable from live data, and both
   matter: the **labels** of the nine statuses and six statistics buckets are
   database rows, not code; and the **effect** of a default filter (6 of 19
   users) cannot be read from source at all. Source told me `sourceType:
   'contact'`; only the live GET told me that hides 13 of 19 people.

4. **My own first pass was wrong ten times, all in the same direction.**
   Writing the `Ours:` column from CLAUDE.md and the route list, I claimed we
   lacked ten things we have: the department/works-type axis, invoice grouping
   granularity, the report catalogue, PDF report output, the SINGLE/MULTIPLE
   batch creation with slots, the overdue bucket on the agenda, the
   BEFORE/AFTER attachment phase, the unit on a priced line, the in-app language
   switch, and backward ("revert") transitions. Two more were wrong by object
   rather than by presence: the completion-requirement flags (we have four,
   from two origins, enforced server-side) and the hours submit step (we have
   DRAFT→SAVED→APPROVED, but on the standing agreement, not on worked hours).

   That failure has a shape worth recording, because it is the same shape as
   "chats reported items fixed that were visibly broken on the live site":
   **a project doc describes intent, and a route list describes surface;
   neither is evidence of behaviour.** Every one of the ten was findable with a
   single grep of our own repo. Any future comparison of the two systems should
   be built from `grep` on both sides, never from CLAUDE.md on ours.

One further correction, to the *framing* rather than the prompt: the reference
system is **not one application**. It is four, sharing a shell — the
Extra Work/Melding system, the Machine Planning system inside Buildings, the
PRJ/Projects planner, and Grades — plus two parallel half-migrated versions of
the first one (`extra-works` and `extra-works-v2`, `invoices` and
`invoices-v2`), of which the V2 pair is routed but hidden from the nav.
Any statement of the form "his system does X" needs to say **which** of them.

---

## Appendix A — complete route inventory

Read from `src/routes/router.jsx`. Commented-out routes excluded.

**Root, behind `AuthGuard` + `MainLayout`**
`/` (dashboard) · `/pages/notifications` · `/pricing/column` · `/pricing/table` ·
`/coming-soon` · `/faq` · `/faq/:category`

**`/admin/*` — behind `AdminGuard` (78 routes)**

*Master data* — `buildings`, `buildings/:id`, `employees`, `employees/:id`,
`contacts`, `contacts/:id`, `departments`, `customer-works`, `customers`,
`customers/:id`, `customers/:id/profile`,
`customers/:customerId/locations/:locationId`

*Lookups* — `lookup-tables`, `building-types`, `building-statuses`,
`building-floors`, `employee-statuses`, `employee-document-types`,
`employee-contract-types`, `customer-statuses`,
`customer-department-statuses`, `customer-works-type-statuses`,
`contact-email-statuses`, `room-statuses`, `room-user-types`,
`room-section-types`, `floor-types`, `role-types`, `ticket-categories`,
`service-line-types`, `service-types`

*Catalogue* — `products`, `product-categories`, `app-versions`,
`product-units`, `overtime-types`, `customer-products`

*Exports & reports* — `data-exports`, `reports`,
`reports/employee-hours/weekly`, `reports/employee-hours/extra-works`,
`reports/employee-hours/by-building`, `reports/melding`

*Work* — `work-plan`, `users`, `users/:id`, `extra-works`,
`extra-works/dashboard`, `extra-works/add`, `extra-works/:id`,
`extra-works-v2`, `extra-works-v2/add`, `extra-works-v2/continuous/:id`,
`extra-works-v2/:id`, `meldings`, `meldings/add`, `meldings/:id`

*Money* — `invoices`, `invoices/:id`, `invoices-v2`, `invoices-v2/:id`,
`contracts`, `contracts/:id`, `contracts/:contractId/projects/:projectId`

*Projects* — `projects`, `projects/create`, `projects/:id`, `projects/:id/edit`,
`prj-projects`, `prj-projects/:id`, `prj-projects/weekly-planning`,
`prj-projects/monthly-planning`, `prj-projects/week-plan`,
`prj-projects/weekly-projects`, `prj-tasks`, `prj-tasks/:id`,
`prj-task-templates`, `prj-task-templates/:id`

*Hours* — `worker-hours`, `worker-hours/approval`

*Grades (embedded)* — `grades/dashboard`, `grades/templates`,
`grades/templates/:id`, `grades/plans`, `grades/inspections`,
`grades/inspections/:id`

**`/portal/*` — behind `CustomerGuard` (13)**
`buildings`, `buildings/:id`, `customers`, `customers/:id`,
`customers/:customerId/locations/:locationId`, `contacts`, `contacts/:id`,
`extra-works`, `extra-works/dashboard`, `extra-works/add`, `extra-works/:id`,
`meldings`, `meldings/add`, `meldings/:id`, `products`, `customer-products`,
`reports`, `reports/melding`, `work-plan`

**`/work/*` — behind `EmployeeGuard` (11)**
as `/portal` minus `reports*` and `work-plan`

**`/grades/*` — standalone app, `GradesLayout` (7)**
`dashboard`, `plans`, `plans/:id`, `inspections`, `inspections/:id`,
`templates`, `templates/:id`

**Auth & misc**
`/login`, `/signup`, `/forgot-password`, `/password-reset`,
`/auth/forgot-password`, `/auth/enter-code`, `/auth/new-password`,
`/auth/setup-password`, `/authentication/default/jwt/{login,sign-up,
forgot-password,2FA,set-password}`, `/authentication/default/sanctum/{…same…}`,
`/authentication/logged-out`, `/email`, `/email/list/:label`,
`/email/details/:label/:id`, `/admin/file-manager`, `/health`, `/healthz`,
`/health.json`, `*` → 404

## Appendix B — live endpoints used to verify (GET only)

| Endpoint | Used for |
| --- | --- |
| `/me` | role shape; admin user id 1 |
| `/me/permissions` | attempted; returns 500 for this admin — **not** used as evidence |
| `/admin/meldings/dashboard` | dashboard is server-scoped to type 2 |
| `/admin/extra-works/statistics?type=1&language=nl` | the six buckets and their labels/counts |
| `/admin/extra-works/statistics?type=2&language=nl` | same for Meldings |
| `/admin/extra-works/meta/config?context=admin&language=nl` | the nine statuses, four priorities, seven categories, the filter map |
| `/admin/extra-works?type=1&statuses=1` / `?type=1` | 16 vs 32 — the EW default filter |
| `/admin/extra-works?type=1&statuses=4` | field list on a live row |
| `/admin/users?source_type=contact&status=1` / unfiltered / `?source_type=employee` | 6 / 19 / 13 — the Users default filter |
| `/admin/invoiceable-items?per_page=3` | the generic billable-line shape |
| `/work-plan/weekly?week=2026-W35` | weekDays + the server-side `overdue` bucket |
| `/admin/roles` | the eight roles |
| `/admin/role-types` | the four role types |
