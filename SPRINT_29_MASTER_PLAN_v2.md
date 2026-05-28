# Sprint 29 Master Plan (revision 2)

**Status:** In progress. 29.1–29.4 shipped on `state/sprint28-pre-audit`.
**Revision date:** 2026-05-19
**Supersedes:** SPRINT_29_MASTER_PLAN.md (v1, 2026-05-15)

This revision adjusts scope after operator feedback on 2026-05-19. Two new
batches (29.6 Users view-first, 29.7 Permissions transparency) were inserted;
"Existing pages 15.x treatment" and "EW reports" slipped to Sprint 30+ to keep
this sprint tractable. The view-first pattern (introduced in 29.3) now applies
to four entities by sprint end: Companies, Buildings, Customers (already
view-first since Sprint 28 Batch 13), and Users.

---

## 1. Sprint goals

1. **Polish the obvious papercuts** (29.1) — pluralization, totals, layout
   breakpoints. ✅ Shipped.
2. **Finish the Edit Basics dedup** (29.2) — the Customer form should not
   duplicate Permissions. ✅ Shipped.
3. **Make every admin entity view-first** (29.3, 29.4, 29.5, 29.6) — opening
   a record shows it; editing requires an explicit click. ✅ 29.3 and 29.4
   shipped. Customer (29.5) and User (29.6) remaining.
4. **Make permissions transparent** (29.7) — admins can see at a glance who
   has custom access from any of three surfaces: Permissions page rows, the
   customer-scoped Users tab, the user's own profile.
5. **Unblock the EW post-approval workflow** (29.8) — the deferred
   IN_PROGRESS / COMPLETED states from Sprint 26B land here.
6. **Fill the empty customer sub-pages** (29.9) — placeholders that exist in
   the sidebar but have no content yet.

---

## 2. Revised batch table

| Batch | Title | Status | Effort |
|-------|-------|--------|--------|
| 29.1 | Polish & papercuts | ✅ Shipped (08f9e18 + follow-ups) | 1d |
| 29.2 | Edit Basics / Permissions dedup | ✅ Shipped | 1d |
| 29.3 | Companies view-first | ✅ Shipped | 0.5d |
| 29.4 | Buildings view-first | ✅ Shipped | 0.5d |
| **29.5** | **Customer Overview enhancement + cleanups** | next | 0.5d |
| **29.6** | **Users view-first** (NEW) | planned | 0.5d |
| **29.7** | **Permissions transparency rollup** (NEW) | planned | 1d |
| 29.8 | EW post-approval workflow | planned | 2d (backend + frontend) |
| 29.9 | Customer sub-page placeholders | planned | 1d |

**Slipped to Sprint 30+:**
- Existing pages 15.x treatment (was 29.8 in v1) — visual / interaction
  parity sweep across older pages.
- EW reports (was 29.9 in v1) — depends on 29.8 landing first; sprint
  capacity says next sprint, not this one.

---

## 3. Batch charters

### 29.5 — Customer Overview enhancement + test infra cleanups

**Why this isn't a fresh view-first batch like 29.3/29.4.** Customer is
already view-first — `/admin/customers/:id` has rendered `CustomerOverviewPage`
since Sprint 28 Batch 13, with the edit form reachable at `/admin/customers/
:id/edit`. The existing Overview is a useful operator dashboard (stat strip,
linked-buildings preview, six quicklinks) but it hides the basic structural
info — contact email, phone, language, provider company name — behind an
Edit basics click. Operator's father observed that admins want this info
visible at-a-glance from the Overview.

**Scope:**
1. Add an "About" card to `CustomerOverviewPage` between the explainer and
   the stat strip, using the `.detail-field-row` pattern from 29.3.
   Fields: provider company (clickable link), contact email (mailto), phone
   (tel), language, status. ~1.5 hours.
2. Extract `apiAs` to a shared `frontend/tests/e2e/fixtures/apiAs.ts` helper
   with retry-on-429 behavior. Three batches in a row (29.2, 29.3, 29.4)
   produced false regression failures from token-endpoint throttle saturation.
   ~30 min.
3. Rename `editPath` → `detailPath` in `CompaniesAdminPage` and
   `BuildingsAdminPage` (post-29.3/29.4 the variable is misleadingly named —
   it points at the detail URL, not the edit URL). ~10 min.

**No new routes. No re-pointing. No removal of anything.** This is purely
additive.

### 29.6 — Users view-first

The fourth and final entity to get the 29.3 treatment. Today
`/admin/users/:id` opens `UserFormPage` directly. After 29.6 it renders a
read-only `UserDetailPage`; the form is reachable at `/admin/users/:id/edit`.

**Cards on the User detail page** (per operator's instructions on
2026-05-19):
- **About card**: full name, email, role, language, status, last login.
- **Contact card**: phone / contact email — anything the User model carries
  that's a way to reach this person.
- **Company info card**: company memberships (which companies they admin),
  building assignments (which buildings they manage), customer memberships
  (which customers they have access to as a customer-side user). Shown as
  read-only rows with deep-links into the relevant entity detail pages.
- **Customer access card**: for each customer this user has access to, one
  row with a placeholder for the rollup chip that 29.7 fills in. Until 29.7
  ships, the rows show plain customer names + a "View permissions" link.

**Role-gating for Edit:** SUPER_ADMIN always. COMPANY_ADMIN cannot edit
arbitrary users; the form already enforces this. (Detailed gating policy
verified against the existing UserFormPage during 29.6 archaeology.)

**Pattern reuse:** Mirror 29.3 / 29.4 verbatim — same `.detail-field-row`
CSS, same role-gate idiom, same `PageHeader` actions slot, same Cancel
button pattern.

**After 29.6 ships:** We have four detail-page implementations
(Company, Building, User, Customer). That's the canonical inflection point
for deciding whether `<DetailPage>` is worth extracting as a shared
component. Decision postponed to that moment — premature now.

### 29.7 — Permissions transparency rollup

The dad-driven batch. After admins save a custom override or policy change
on the Permissions page, that state is currently invisible from every other
surface. Three places gain a rollup chip:

1. **Permissions page rows** — each user row in the customer-scoped
   Permissions page surfaces a `<PermissionsRollupChip>` after the role
   badge, showing `Default` (no overrides) or `Custom (N)` where N counts
   overrides differing from policy. Click the chip → opens the existing
   override drawer focused on that user (the focus_user URL param from
   29.2 makes this trivial).
2. **Customer-scoped Users tab rows** — same chip on `/admin/customers/
   :id/users` rows, click deep-links to the Permissions page with
   `focus_user`.
3. **User detail "Customer access" card** — the 29.6 placeholder rows get
   the chip, click deep-links to `/admin/customers/:customerId/permissions
   ?focus_user=:userId`.

**Design defaults locked on 2026-05-19:**
- **Q1 (where does click go?):** Permissions page deep-link in all three
  surfaces. Edit stays in one place; complex permissions logic doesn't
  fragment.
- **Q2 (chip copy):** "Default" / "Custom (N)". Simple wins for now;
  descriptive labels like "Standard / Extended / Restricted" deferred —
  too easy to argue about and not load-bearing.
- **Q3 (User detail scope):** Show only customers this user has access to,
  not the full catalog.

**Implementation note:** One new component, `PermissionsRollupChip`, used
in three call-sites. The N count is derived from the existing customer
policy + per-user override API responses; no new endpoint needed.

### 29.8 — EW post-approval workflow

Unchanged from v1. Three Sprint 26B deferrals all unblock together:
- Add `IN_PROGRESS` + `COMPLETED` states to `ExtraWorkStatus`
  (operational lens; FULFILLED / BILLED commercial states remain deferred).
- Update `scope_extra_work_for(STAFF)` to surface EWs with active spawned
  tickets.
- Update `EXTRA_WORK_TERMINAL_STATUSES` so dashboard re-counts include
  customer-approved EWs.
- Add "Spawned tickets" panel to EW detail page.
- Cascade-cancel dialog when EW is cancelled with active tickets.
- Auto-transition on first / all spawned tickets entering / leaving
  IN_PROGRESS.
- Customer-side surface shows IN_PROGRESS / COMPLETED transitions.

**First backend-touching batch of Sprint 29.** Migration: yes.

### 29.9 — Customer sub-page placeholders

Unchanged from v1. The customer-scoped sidebar shows links to Settings,
Contacts, Pricing, etc., some of which are placeholder pages today.
This batch fills them with the minimum useful content. Out of scope:
deep editing flows — those are individual batches in later sprints.

---

## 4. Cross-cutting carry-over (unchanged from v1)

- Foundation primitives from 15.1–29.4 are shipped. Reuse, don't reinvent.
- i18n parity rule: every new EN key gets an NL counterpart.
- No new npm dependencies in any Sprint 29 batch.
- No backend changes in 29.5, 29.6, 29.7. Backend resumes in 29.8.
- DO NOT auto-commit. Operator commits after each batch.
- Preserve every locked testid from 15.1–29.4.

---

## 5. Never-touch list (carries through every batch)

Unchanged from v1:
- ProposalLine.internal_note customer-side privacy
- ExtraWorkRequest.manager_note / internal_cost_note / override_* provider-only gates
- BM read-only on customer pages (Overview + Contacts only via ByRole dispatcher)
- All locked testids from prior batches
- osius.* permission key naming (deferred cleanup sprint)
- 16-key CUSTOMER_PERMISSION_KEYS universe
- H-6 / H-7 RBAC (only SUPER_ADMIN grants CUSTOMER_COMPANY_ADMIN)

---

## 6. Decision log (revision 2)

- **2026-05-19**: Permissions rollup chip click target → deep-link to
  Permissions page (option A), not inline edit on User detail. Edit lives
  in one place.
- **2026-05-19**: Rollup chip copy → "Default" / "Custom (N)". Defer
  descriptive labels.
- **2026-05-19**: User detail customer-access scope → only customers this
  user has access to.
- **2026-05-19**: apiAs throttle cleanup → fold into 29.5 as task 2.
- **2026-05-19**: editPath rename → fold into 29.5 as task 3.
- **2026-05-19**: `<DetailPage>` extraction → decide after 29.6, not before.

---

## 7. What this sprint deliberately doesn't do

- Customer-side view-first work (operator-facing only this sprint).
- Phone field on User model (already on Customer model; not adding to User).
- Commercial EW states (FULFILLED, BILLED).
- osius.* permission key naming cleanup.
- i18n NL parity translation pass (~30 untranslated strings from 15.5 audit).
- Audit log search / filter.
- Notification preferences expansion.
