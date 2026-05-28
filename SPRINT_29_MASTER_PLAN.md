# Sprint 29 Master Plan
## CleanOps — Post-rebuild productionisation sprint

Branch base: `state/sprint28-pre-audit` @ `e057e40` (Sprint 28 Batch 15.5 — final rebuild batch, pushed).

This is a **planning doc**, not a Claude Code brief. Each batch below becomes its own CC brief later, written one at a time as we ship. The point of this doc is to:
1. Frame what we're solving so we both know *why* each batch is on the list.
2. Order the batches with explicit dependencies and rationale.
3. Flag the product-scope decisions we need to make *before* writing the first brief, so design happens at planning time, not prompt-write time.

---

## 1. What we're solving (the operator's review, categorized)

After the 15.5 walkthrough, the operator surfaced six categories of issues. Re-stated in our shared vocabulary, slightly reframed against what the code actually says:

| Cat | Theme | Operator's words (paraphrased) | Reality |
|---|---|---|---|
| **A** | Polish & small fixes | "Pricing total label, table padding too tight, scope chip 'one customers'" | Genuine ~30–50-line fixes scattered across already-rebuilt pages |
| **B** | Edit Basics duplicates Permissions | "There are two permission editors, they look different" | Confirmed. Edit Basics carries a full inline copy of customer-company policy + 16-permission per-user-per-building editor. The Permissions page (rebuilt in 15.2) duplicates the same data. Two surfaces editing the same model. |
| **C** | View-first vs edit-first | "Clicking a Company / Building / User opens edit mode directly; should show read-only first, edit via button" | A meaningful UX pattern shift across 3–4 entity types. Some pages (`ServicesAdminPage`, `CustomerPricingPage`) already implement view-first — so the pattern *exists*, it's just not universal. |
| **D** | "Empty pages" | "Services, Pricing, Extra Work, Contacts, Settings need to be filled" | **The operator's framing is half-right.** Two distinct sub-problems: (D1) The customer-scoped sub-routes (`/admin/customers/:id/{buildings,users,extra-work,contacts,settings}`) currently render a 47-line `CustomerSubPagePlaceholder` "coming soon" stub — these are *genuinely* empty. (D2) `ServicesAdminPage` (1260 lines), `CustomerPricingPage` (766 lines), `CustomerContactsPage` (731 lines), `CustomerSettingsPage` (344 lines, customer-scoped variant) all exist with real functionality but pre-date the 15.x design-system rebuild — they're *visually* under-developed, not functionally empty. |
| **E** | EW post-approval workflow gap | "I'm a SUPER_ADMIN and a customer-approved EW only lets me Move to Cancelled — why? Why can I not assign staff? Approved EWs don't show on the dashboard." | **Real working-software gap.** Three intentional Sprint 26B deferrals converging: (a) `ExtraWorkStatus` enum has no operational states past `CUSTOMER_APPROVED`; (b) `scope_extra_work_for` returns `.none()` for STAFF for the same reason; (c) `EXTRA_WORK_TERMINAL_STATUSES` includes `CUSTOMER_APPROVED`, so the dashboard hides approved EWs. All three resolve in one batch when we land operational states. |
| **F** | Reports gap | "Extra Work needs reports" | EW is missing from `/reports` entirely. Backend has the data. Depends on stable post-approval state semantics from E. |

Operator priority order: **A → B → C → D → E → F.** Confirmed. But I'll argue for *priority-with-interleaving* in §3 because strict-sequential blocks empty pages (D — pilot-blocker) behind view-first refactor (C — the biggest single piece).

---

## 2. What I found in the code (grounded findings)

Three reads worth highlighting because they shape the plan:

### 2.1 Three Sprint 26B deferrals all resolve together

Same author, same MVP, same gap pointed at from three files:

```
backend/extra_work/models.py:74
  "Operational-execution statuses (ASSIGNED / IN_PROGRESS /
   WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL / COMPLETED)
   are deferred to a follow-up sprint."

backend/extra_work/scoping.py:11–16, 67–71
  STAFF returns ExtraWorkRequest.objects.none(). Comment:
  "Will be revisited when ASSIGNED / IN_PROGRESS statuses are added
   in the follow-up sprint."

backend/extra_work/views.py:65
  EXTRA_WORK_TERMINAL_STATUSES = ("CUSTOMER_APPROVED",
   "CUSTOMER_REJECTED", "CANCELLED")
  → dashboard "ACTIVE EXTRA WORK" tile filters with
    ~Q(status__in=terminal), so customer-approved EWs are
    invisible.
```

When 29.3 lands the operational states, all three corrections happen at once. Nice consolidation.

### 2.2 The "empty pages" framing has two distinct shapes

| Page (route) | LoC | Status | Treatment needed |
|---|---|---|---|
| `/admin/customers/:id/buildings` | 47 (placeholder) | Genuinely empty stub | **Build from scratch** |
| `/admin/customers/:id/users` | 47 (placeholder) | Genuinely empty stub | **Build from scratch** |
| `/admin/customers/:id/extra-work` | 47 (placeholder) | Genuinely empty stub | **Build from scratch** (filtered EW list) |
| `/admin/customers/:id/contacts` | 47 (placeholder) | Genuinely empty stub | **Build from scratch** (or wire to existing `CustomerContactsPage`) |
| `/admin/customers/:id/settings` | 344 | Built (Batch 13), feels bare | **Apply 15.x rebuild treatment** |
| `/admin/customers/:id/permissions` | 1500+ | Built and rebuilt (15.2) | Done |
| `/admin/customers/:id/overview` | (CustomerFormPage parent) | Built, but mixed with Edit Basics | Covered by B (de-dup) and C (view-first) |
| `/admin/services` | 1260 | Built (Batch 5), already view-first | **Apply 15.x rebuild treatment** |
| `/admin/customers/:id/pricing` | 766 | Built (Batch 5), already view-first | **Apply 15.x rebuild treatment** |
| `/admin/customers/:id/contacts` (top-level legacy) | 731 | Built, in use | **Apply 15.x rebuild treatment** |

Two batches, not one. **29.4** builds the genuinely-empty sub-routes; **29.5** brings the under-styled pages up to 15.x standard.

### 2.3 View-first pattern partial-existence

`ServicesAdminPage`, `CustomerPricingPage`, `CustomerContactsPage` already implement view-first (rows read-only, click opens read-only panel, edit is explicit modal action). They have docstrings calling this out as a deliberate pattern. So when we roll out view-first to Companies, Buildings, Customers — we're not inventing it, we're **extending an existing local pattern to the rest of the surface**. That makes 29.6 less risky than I initially scoped.

---

## 3. The batches

### 29.1 — Small fixes (A)

**Goal.** Knock out the scattered ~30–50-line polish items from the 15.x walkthrough. One batch, half a day.

**Scope.**
- Pricing proposal table — add "Total" label cell on the totals row (currently the row is identifiable only by emphasized numbers).
- Pricing table cell padding — increase vertical padding so text doesn't hug row borders.
- Scope chip pluralization — `users.scope_buildings`, `users.scope_customers`, `users.scope_companies` go from bare plurals to i18next `_one` / `_other` form. EN: `"{{count}} building"` / `"{{count}} buildings"`. NL parallel. (Screenshot showed "1 customers" which is the bug.)
- "Affects: customer.ticket.approve_own" technical strings on the Permissions page — move behind a "Show technical keys" toggle (per-user preference, off by default) instead of always-visible. Super admins / integration partners can flip on; client admins see the human-readable label only.
- Settings page (`SettingsPage.tsx`, the user's own account page) — left-column emptiness. Decide: add a "Recent activity" or "Sessions" card, OR centre the existing form and drop the empty column entirely. **Open decision: which approach?** I lean toward dropping the column and centring the form because we don't have user-specific telemetry to put there yet.

**Files touched (rough).** `frontend/src/pages/admin/customer/CustomerPermissionsPage.tsx`, `frontend/src/pages/admin/UsersAdminPage.tsx`, `frontend/src/components/ScopeChip.tsx` (or wherever it ended up after 15.5), `frontend/src/pages/ExtraWorkDetailPage.tsx` (pricing table), `frontend/src/pages/SettingsPage.tsx`, `frontend/src/i18n/en/common.json`, `frontend/src/i18n/nl/common.json`, `frontend/src/index.css`.

**Effort.** Half a day.

**Dependencies.** None.

**Open product decisions before CC brief.**
- Settings page left-column treatment (drop vs add).
- "Show technical keys" toggle — per-user preference (stored in `User.preferences` JSONB) or per-session (localStorage)? I'd go per-user so it persists across devices.

---

### 29.2 — Edit Basics / Permissions de-duplication (B)

**Goal.** One source of truth for customer permissions. Edit Basics page stops carrying inline permission editing.

**Scope.**
- Edit Basics (`CustomerFormPage.tsx`) loses:
  - The full customer-company policy section (4 toggles: `allow_customer_users_to_create_tickets`, etc.)
  - The per-user inline 16-permission editor
  - The "Edit permissions" inline link per building-access row
- Edit Basics keeps:
  - Customer name, language, contact email
  - Linked buildings (list + add/remove)
  - User membership (list + add/remove users, set per-building access role)
  - Lifecycle (deactivate / reactivate)
  - Assigned-staff visibility flags (matches what's on `customer/CustomerSettingsPage` today)
- The user list on Edit Basics gets a per-row "Manage permissions →" deep-link that opens the Permissions page (`/admin/customers/:id/permissions`) with a query param like `?focus_user=<id>&focus_building=<id>` that pre-expands the right user card and opens the overrides drawer if `focus_building` is also set.
- Permissions page is **unchanged** — it's already the canonical surface (rebuilt in 15.2). We just add the `?focus_user=&focus_building=` URL params to its existing logic.

**Files touched (rough).**
- `frontend/src/pages/admin/CustomerFormPage.tsx` — remove inline policy + permissions, keep structural fields, add deep-link button
- `frontend/src/pages/admin/customer/CustomerPermissionsPage.tsx` — handle query params (auto-scroll + auto-expand)
- Tests in both Playwright (Edit Basics no longer renders policy fields; deep link works) and the React unit suite

**Effort.** 1 day (frontend-only; no backend change — the data was always served by the same endpoints).

**Dependencies.** None.

**Open product decisions.**
- Where does the customer-company policy actually live in the UI? Three options:
  - (a) Stays in Edit Basics (we just remove the per-user permissions, keep the company-level toggles).
  - (b) Moves entirely to the Permissions page (one source of truth includes the policy).
  - (c) Lives on `customer/CustomerSettingsPage` (the customer-scoped sub-route).
  - **My recommendation: (b).** The customer-company policy and the per-user-per-building permissions are the same shaped decision at different granularities. They belong on the same page so a power user can reason about the override stack in one view.
- Should the "Edit permissions" deep link be a button (action) or a link (navigation)? Either works; button reads more clearly as an action that opens the drawer.

---

### 29.3 — EW post-approval workflow + STAFF visibility + dashboard recount (E, promoted from operator's #5)

**Goal.** Close the three Sprint 26B deferrals as a single coherent change. EW becomes a first-class operational + commercial object, not a negotiation artifact that dies at customer-approved.

**Scope (backend).**
- `ExtraWorkStatus` enum gains two new values: `IN_PROGRESS`, `COMPLETED`. (Skip `ASSIGNED` / `WAITING_MANAGER_REVIEW` / `WAITING_CUSTOMER_APPROVAL` — those are ticket-level concerns. Keep the EW machine small.)
- Transition rules in `ExtraWorkRequest.transition_to()` (or wherever transitions live):
  - `CUSTOMER_APPROVED → IN_PROGRESS` (provider operator action, or auto when first spawned ticket moves out of OPEN)
  - `IN_PROGRESS → COMPLETED` (provider operator action, or auto when all spawned tickets terminal)
  - `IN_PROGRESS → CUSTOMER_REJECTED` blocked (already past customer approval)
  - `IN_PROGRESS → CANCELLED` allowed (cascades cancel to non-terminal spawned tickets — needs design decision below)
- `EXTRA_WORK_TERMINAL_STATUSES` (in `views.py`) shrinks to `("CUSTOMER_REJECTED", "CANCELLED", "COMPLETED")`. Approved + in-progress now count as active.
- `scope_extra_work_for(STAFF)` stops returning `.none()`. Returns:
  ```
  ExtraWorkRequest.objects.filter(
      deleted_at__isnull=True,
      spawned_tickets__assigned_to=user,  # or via BuildingStaffVisibility
      status__in=("CUSTOMER_APPROVED", "IN_PROGRESS"),
  ).distinct()
  ```
  STAFF only sees EWs that have an active spawned ticket they're assigned to. Doesn't see REQUESTED / PRICING_PROPOSED / CUSTOMER_REJECTED.
- EW detail serializer gains `spawned_tickets: [{id, subject, status, assigned_to_name, ...}]` (already partially there — verify and complete).
- "Working on this" derived field on EW detail: `assigned_staff: [user, user, ...]` computed from the union of spawned tickets' assignments. Read-only on the EW side — write path stays on the ticket. (This solves "why can't I assign staff to EW?" — answer: you already did, on the ticket; the EW now surfaces it.)
- Audit: every transition writes `ExtraWorkStatusHistory` (already happens for the existing states; just extends).
- Migration: trivial (just add the two enum values). No data migration for existing rows — they stay in `CUSTOMER_APPROVED` and become eligible for `IN_PROGRESS` going forward.
- Tests: full coverage of the new transitions, the new STAFF scope, the dashboard recount, the spawned-ticket panel data.

**Scope (frontend).**
- EW detail page Workflow card (right rail):
  - For `CUSTOMER_APPROVED`: shows "Move to In progress" + "Move to Cancelled" (instead of just "Move to Cancelled").
  - For `IN_PROGRESS`: shows "Move to Completed" + "Move to Cancelled".
  - For `COMPLETED`: card collapses or shows "This work is complete" with status timestamp.
- EW detail page right rail gains a **"Spawned tickets" panel** below Workflow: list of tickets with status badges, click-through. Empty state: "No tickets yet" (for PROPOSAL-routed not-yet-spawned cases).
- EW detail page right rail gains a **"Working on this" panel**: list of staff (with role badges) currently assigned to active spawned tickets. Empty state: "No staff assigned yet — assign on the ticket." with a link to the first spawned ticket.
- Dashboard EW KPI tile "ACTIVE EXTRA WORK" now correctly counts CUSTOMER_APPROVED + IN_PROGRESS. Add an "IN PROGRESS" sub-count or a second tile?
- Status badge for `IN_PROGRESS` and `COMPLETED` — pick tones. `IN_PROGRESS` likely green-distinct from CUSTOMER_APPROVED (use existing `.badge-in_progress` from tickets). `COMPLETED` neutral grey.

**Files touched (rough).** `backend/extra_work/models.py`, `backend/extra_work/transitions.py` (if it exists, else `views.py`), `backend/extra_work/scoping.py`, `backend/extra_work/views.py`, `backend/extra_work/serializers.py`, `backend/extra_work/tests/test_*.py`, `frontend/src/pages/ExtraWorkDetailPage.tsx`, `frontend/src/pages/DashboardPage.tsx`, `frontend/src/components/StatusBadge.tsx`, `frontend/src/api/types.ts`.

**Effort.** 2–3 days. The biggest single batch in Sprint 29.

**Dependencies.** None — it sits on top of 15.x foundations.

**Open product decisions.**
- **Cascade cancellation.** When provider moves EW from IN_PROGRESS to CANCELLED, should non-terminal spawned tickets auto-cancel? My recommendation: **no, but warn**. Show a dialog listing the active spawned tickets and ask "Cancel these too? [Yes / No, keep tickets open]". If "no, keep tickets open", the tickets become orphans of the EW but remain workable — that's an edge case but real (e.g. the EW gets cancelled commercially but the work was already done).
- **Auto-transition vs explicit.** When the first spawned ticket moves OPEN→IN_PROGRESS, does the EW auto-transition CUSTOMER_APPROVED→IN_PROGRESS? My recommendation: **yes, auto, with audit-log entry**. The alternative (manual transition) requires the provider operator to remember to bump the EW state separately, which they won't.
- **COMPLETED-auto.** When all spawned tickets terminal, does the EW auto-transition IN_PROGRESS→COMPLETED? My recommendation: **yes, auto**, same rationale.
- **Customer-side visibility.** Does the customer see the IN_PROGRESS / COMPLETED transitions on their EW detail? My recommendation: **yes** — it's better customer experience to see "your approved work is now in progress" than to have the EW look frozen.
- **Reject from IN_PROGRESS?** Customer can't reject past CUSTOMER_APPROVED. Confirmed by spec.

---

### 29.4 — Customer sub-page placeholders (D1: genuinely empty pages)

**Goal.** Build the five customer-scoped sub-routes that today render `CustomerSubPagePlaceholder`.

**Scope.** Each sub-page is a focused customer-context view of an existing data source:

- **`/admin/customers/:id/buildings`** — table of `CustomerBuildingMembership` rows. Add/remove buildings for this customer. ~half-day. (Already covered partially by Edit Basics; this is the proper dedicated page.)
- **`/admin/customers/:id/users`** — table of `CustomerUserMembership` rows. Add/remove users. Click row → opens the Permissions page focused on that user (deep link from 29.2). ~half-day.
- **`/admin/customers/:id/extra-work`** — filtered view of `/extra-work` with `customer_id=<id>` pre-applied. Same KPI strip + filter chrome from 15.3. Header: "Extra work for {customer name}". ~1 day.
- **`/admin/customers/:id/contacts`** — customer-context contacts. Today's top-level `CustomerContactsPage` (731 lines) is global; the customer sub-route stub should render the same component scoped to this customer's contacts only. Probably wires up by passing `customerId` as prop. ~half-day (mostly wiring).
- **`/admin/customers/:id/settings`** — already built (the `customer/CustomerSettingsPage`, 344 lines). The placeholder route mapping just needs to point to it. **Verify wiring** — this might already be correct, in which case nothing to do here. ~15 minutes.

**Each can ship as its own sub-batch (29.4a, 29.4b, 29.4c, 29.4d, 29.4e)** — they don't depend on each other.

**Files touched.** Five new sub-page components, route table in `AppShell.tsx` or wherever React Router is configured, copy/paste-and-scope from existing pages where possible.

**Effort.** 3 days total if interleaved across sessions.

**Dependencies.** 29.2 (Edit Basics dedup) is a soft prerequisite — once Edit Basics no longer carries building/user management inline, the dedicated sub-pages become the canonical surface.

**Open product decisions.**
- Customer Buildings sub-page: does it support **linking new buildings** (= adding a `CustomerBuildingMembership`), or just listing existing? Recommendation: list + add + remove, matching Edit Basics' current behaviour.
- Customer Users sub-page: same question. Recommendation: list + invite + remove + per-row "Manage permissions" deep link.
- Customer Extra Work sub-page: does it have its own KPI strip (like the top-level `/extra-work`), or just the table? Recommendation: **yes, KPI strip**, scoped to this customer only. Lets a customer-admin see "you have 2 approved EWs in progress, 1 pending price" without leaving the customer context.
- Customer Contacts: do we keep the top-level `/admin/customers/contacts` global page at all, or fold everything into customer-scoped? Recommendation: **fold**. Contacts only make sense in customer context; the top-level page is a leftover.

---

### 29.5 — 15.x design treatment for the under-styled pages (D2: existing pages)

**Goal.** Apply the design system (PageHeader, KPI strips where they help, EmptyState, StatusBadge, intl-formatted dates and money, etc.) to the pages that pre-date 15.x.

**Scope.** Four target pages:
- `ServicesAdminPage` (1260 lines, Sprint 28 Batch 5) — add PageHeader, drop the local tab implementation in favour of `<PageTabs>` if we have one, format dates with `lib/intl`, replace any local money formatting with `formatMoney`, ensure the empty-state for no-services-yet uses `<EmptyState>`.
- `CustomerPricingPage` (766 lines, Batch 5) — same treatment. Add a KPI strip ("X active prices", "Y inactive", "Z services with no price") if it adds clarity, otherwise just PageHeader + EmptyState + intl.
- `CustomerContactsPage` (731 lines) — same treatment. Likely candidates for a small KPI strip too ("X total contacts", "Y primary contacts").
- `customer/CustomerSettingsPage` (344 lines, Batch 13 rework) — PageHeader, drop the bare top-of-page text in favour of the consistent eyebrow + h1 + helper text shape used elsewhere. Re-balance the cards so the page isn't 1/3 used.

**Files touched.** The four pages above; minor additions to `frontend/src/index.css` for any new patterns.

**Effort.** 2 days total (half-day per page).

**Dependencies.** None — purely cosmetic on already-functional pages.

**Open product decisions.**
- Do we add KPI strips to Pricing / Contacts pages? Recommendation: **yes for Pricing, no for Contacts** — pricing rows have quantitative state (active count, total contracted value) that's worth surfacing; contacts are mostly a phonebook.
- Does the Settings page need new fields (e.g. default SLA, default notification routing for the customer's users)? Recommendation: **defer**. Bring the existing fields up to 15.x styling first; new fields are a separate product decision.

---

### 29.6 — View-first pattern rollout (C)

**Goal.** Apply the view-first pattern (already in use on Services / Pricing / Contacts pages) to the three entities where clicking still opens edit mode directly: Companies, Buildings, Customers Overview.

**Scope.**

- **Companies** (`CompanyFormPage.tsx`) — split into `CompanyDetailPage` (read-only) + `CompanyFormPage` (edit). Route `/admin/companies/:id` shows detail; explicit "Edit" button (role-gated to SUPER_ADMIN + COMPANY_ADMIN of *that* company) navigates to `/admin/companies/:id/edit`. Cancel returns to detail. Save returns to detail.
- **Buildings** (`BuildingFormPage.tsx`) — same split. `/admin/buildings/:id` → detail. `/admin/buildings/:id/edit` → form.
- **Customers Overview** (`/admin/customers/:id/overview` which currently renders `CustomerFormPage` parent) — same split. Detail is the read-only "this customer at a glance" view; Edit Basics (post-29.2) is the form behind the explicit Edit button.

**Users page stays edit-first** per operator preference — "in the Users section, directly opening edit mode is okay because clicking is already for editing." (Operator's exact framing.) The Users **list** stays as-is; the per-user form stays as-is.

**Files touched.** Six new components (three detail pages, three split forms — though the forms may already be 80% there since they exist today). Routing changes in `AppShell.tsx` / `App.tsx`. Role-gating logic on the Edit button.

**Effort.** 2–3 days. Each entity ~1 day.

**Dependencies.** 29.2 (Edit Basics dedup) is a hard prerequisite for the Customer Overview split, because we can't split Edit Basics into view + edit if Edit Basics still carries the duplicated permission editor. 29.5 (15.x design treatment) is also a soft prerequisite for the Customer Overview specifically — easier to design the read-only view if the source page is already styled to 15.x.

**Open product decisions.**
- Edit button role-gating exact rules:
  - **Company**: SUPER_ADMIN, or COMPANY_ADMIN-of-this-company. Not COMPANY_ADMIN of another company.
  - **Building**: SUPER_ADMIN, or COMPANY_ADMIN-of-this-building's-company, or BUILDING_MANAGER-of-this-building.
  - **Customer**: SUPER_ADMIN, or COMPANY_ADMIN-of-this-customer's-company. (Not Customer admins editing themselves — that's customer-side, different UI.)
- "Phone number" field on user detail (operator mentioned: *"when you click on a user, it would be nice to also see things like the person's phone number"*) — is that a real product gap? Today `User` model has no `phone` field. Adding it is a 1-line model change + serializer + form field but requires a product decision: do we collect operator phone numbers? Recommendation: **yes**, defer to its own batch, not part of 29.6.

---

### 29.7 — Extra Work reports (F)

**Goal.** Close the Reports gap. `/reports` today shows ticket charts only; EW is missing.

**Scope.**
- New report block on `/reports` page: "Extra Work".
- Charts:
  - **EW volume by month** (last 6 months) — count of EWs requested.
  - **EW value by month** — sum of `total_amount` for CUSTOMER_APPROVED + IN_PROGRESS + COMPLETED.
  - **Routing split** — INSTANT vs PROPOSAL, pie or stacked bar.
  - **Avg proposal-to-approval time** — mean delta between `PRICING_PROPOSED` history entry and `CUSTOMER_APPROVED` history entry, by month.
  - **Customer-rejection rate** — % of EWs that ended CUSTOMER_REJECTED.
- Filterable by date range, customer, building (same controls as the ticket reports).
- Export buttons reused.

**Files touched.** New aggregation endpoints in `backend/extra_work/views.py` (or a new `backend/extra_work/reports.py` module), new chart components in `frontend/src/pages/reports/charts/`, integration into `ReportsPage.tsx`.

**Effort.** 2–3 days.

**Dependencies.** 29.3 is a **hard prerequisite** — the value/volume reports rely on the operational states existing so we can count "in flight" separately from "complete" separately from "approved-but-not-started". Until those states exist, the value-by-status chart can't tell a useful story.

**Open product decisions.**
- Should EW reports also expose **internal margin** (revenue − provider-only cost notes)? Recommendation: **no in 29.7, yes later**. Margin is a more sensitive number that probably wants its own role-gating and report surface; bolt it on once basic EW reports work.

---

## 4. Recommended order

Strict priority A→B→C→D→E→F (operator's preference) gives:

```
29.1 → 29.2 → 29.6 → 29.4 → 29.4… → 29.4… → 29.3 → 29.7
A      B      C      D1      D1      D1      E      F
```

This sequence blocks D (pilot-unblocking empty pages) behind C (biggest visual refactor) and pushes E (working-software bug) to the back. Not ideal.

**My recommended interleaving**, which keeps the A→B→… priority but lets us ship visible progress every week:

```
Week 1
  29.1   small fixes                    ✅ pilot-visible polish
  29.2   Edit Basics/Permissions dedup  ✅ fixes consistency issue
  29.3   EW workflow (backend starts)   🟡 in flight

Week 2
  29.3   EW workflow (frontend + tests) ✅ fixes working-software gap
  29.4a  Customer Buildings sub-page    ✅ unblocks pilot
  29.4b  Customer Users sub-page        ✅ unblocks pilot

Week 3
  29.4c  Customer Extra Work sub-page   ✅ unblocks pilot
  29.4d  Customer Contacts sub-page     ✅ unblocks pilot
  29.4e  Customer Settings verify       ✅ unblocks pilot
  29.5a  ServicesAdminPage rebuild      ✅ design consistency

Week 4
  29.5b  CustomerPricingPage rebuild    ✅ design consistency
  29.5c  CustomerContactsPage rebuild   ✅ design consistency
  29.5d  CustomerSettingsPage rebuild   ✅ design consistency
  29.6a  Companies view-first           🟡 in flight

Week 5
  29.6b  Buildings view-first           ✅
  29.6c  Customer Overview view-first   ✅
  29.7   EW reports                     🟡 in flight

Week 6
  29.7   EW reports                     ✅
  --     full regression / manual QA    ✅
  --     pilot release tag              ✅
```

Total: ~6 weeks of focused work. Some weeks heavier than others. Each batch is a separate CC brief we write the week we ship it, not all up-front.

**Key reasoning for the order:**
- **29.1 first** because it's the lowest-risk, highest-visibility win. Builds momentum after the rebuild plan closed.
- **29.2 second** because it's bounded, unblocks the view-first work on Customer Overview, and fixes the "two surfaces editing the same data" inconsistency that the operator noticed.
- **29.3 third** even though it's the operator's #5 — because (a) it's a real working-software bug, not a polish issue; (b) it unblocks 29.7 (reports); (c) the dashboard EW invisibility is going to bite pilot users on day 1.
- **29.4 fourth** because pilot users need the customer sub-pages to actually exist. Five sub-batches; they're independent and parallelizable.
- **29.5 fifth** because it's pure cosmetic on already-functional pages — no risk to anything else.
- **29.6 sixth** because it's the largest single piece and benefits from the foundations laid by 29.2 and 29.5.
- **29.7 last** because it depends on stable post-29.3 state semantics.

---

## 5. Out of scope for Sprint 29 (explicitly deferred)

- **Phone field on User model** — operator requested seeing phone numbers on user detail; needs its own product decision (do we collect / require / display these? what's the privacy stance?). Park for Sprint 30.
- **Commercial / billing EW states** (`FULFILLED`, `BILLED`) — operator confirmed operational-first; revisit when invoicing is in scope.
- **Permissions drawer backdrop opacity tweak** — cosmetic paper-cut.
- **× remove button styling on per-building access chips** — cosmetic paper-cut.
- **Full responsive screenshot tests at 380px** — operator visually confirmed mobile works.
- **EW margin reports** — see 29.7 notes.
- **Customer-side view-first** — operator's view-first preference is for *admin* surfaces. The customer-side surfaces (where Amanda / Iris / Tom log in) are a separate question we haven't tackled yet.
- **Notification preferences expansion** — Settings page currently has 4 notification toggles (ticket created / status changed / assigned / unassigned). Adding more is a product decision.
- **Audit log search / filter** — Audit log page exists (rebuilt in 15.3) but has no search. Park for Sprint 30.

---

## 6. Cross-cutting constraints (carries through every batch)

These are the "never touch" rules from Sprint 28 that continue to apply in Sprint 29:

- **`ProposalLine.internal_note` privacy**. Customer-side never sees provider-only fields. Separate serializer (`ProposalLineCustomerSerializer`) + byte-search tests stay in place.
- **`ExtraWorkRequest.manager_note`, `internal_cost_note`, `override_*` fields** — provider-only. Customer-side serializers exclude.
- **BUILDING_MANAGER read-only on customer pages** (Overview + Contacts only via the `ByRole` dispatcher pattern).
- **All locked testids from 15.1–15.5** stay. New testids only.
- **No new permission keys** outside of explicit RBAC matrix updates.
- **`osius.*` permission key naming convention** — even if operator dislikes it, it's a separate cleanup sprint, not Sprint 29.
- **16-key `CUSTOMER_PERMISSION_KEYS` universe** — the universe doesn't change. We can rename labels / add tooltips / hide technical keys, but the set itself is frozen.
- **H-6 / H-7 RBAC safety nets** — only SUPER_ADMIN grants CUSTOMER_COMPANY_ADMIN. Continues to hold.
- **No emojis in code or comments** (per operator preference established in 15.x).
- **No new icon library** — lucide-react only, no Material/Fontawesome/etc.
- **No new npm dependencies** without explicit approval.
- **i18n parity** — every new EN key has an NL counterpart. The Sprint 28 Batch 15.5 audit found 30+ existing parity gaps; those are deferred to a dedicated translation pass (not Sprint 29's job).

---

## 7. Pre-flight checklist before writing the 29.1 CC brief

The bare minimum we need to lock before I can write the first prompt:

1. ☐ Operator confirms the recommended order in §4 (or reorders).
2. ☐ Decision: Settings page left-column treatment (drop vs add a card). [§3.29.1]
3. ☐ Decision: "Show technical keys" toggle — per-user preference vs localStorage. [§3.29.1]
4. ☐ Decision: customer-company policy location post-29.2 — option (a), (b), or (c). [§3.29.2]
5. ☐ Decision: 29.3 cascade-cancellation behaviour. [§3.29.3]
6. ☐ Decision: 29.3 auto-transition rules (CUSTOMER_APPROVED → IN_PROGRESS auto when first ticket starts? IN_PROGRESS → COMPLETED auto when all tickets terminal?). [§3.29.3]
7. ☐ Decision: 29.3 customer-side visibility of IN_PROGRESS / COMPLETED. [§3.29.3]
8. ☐ Decision: 29.4 each customer sub-page's exact scope (mostly listed in §3.29.4 with recommendations).

Items 1–3 are needed for the 29.1 brief. 4 is needed for 29.2. 5–7 are needed for 29.3. 8 is needed for each 29.4 sub-batch. They don't all need to be decided today.

---

## 8. Numbering convention

Sprint 28 rebuild was "Batch 15.x." Sprint 29 batches are **"29.x"** (29.1, 29.2, ..., 29.7), with sub-batches as 29.Na/b/c where applicable. Commit message prefix: `Sprint 29 Batch 29.N: <title>`. This makes the git history easy to slice by sprint.

---

## 9. After Sprint 29

The likely Sprint 30 topics (not committing to them now, just noting what would come next):

- Customer-side surfaces audit (Amanda / Iris / Tom views — make sure the customer experience is as polished as the provider experience).
- Phone field + richer User profile.
- Commercial EW states (FULFILLED / BILLED).
- Notification preferences expansion.
- Audit log search / filter.
- `osius.*` permission key naming cleanup.
- i18n translation parity pass.
- Pilot release prep: docs, onboarding flow, demo data scrubbing.

---

*End of Sprint 29 master plan. Ready for review.*
