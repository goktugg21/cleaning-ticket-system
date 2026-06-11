# Osius — Gap-Closing Sprint Checklist

**Updated 2026-06-05** — post PR #87 (Sprint 6 merged) + **Ramazan Meeting 2**.

**Purpose.** The living plan to close every remaining gap between the system and the Ramazan transcripts + Source of Truth, ending with a premium UI/UX polish. **CC ticks the boxes for a sprint as it completes it** (and stages this file with the commit), so we always know where we are.

**How to use.** Work the **Near-term priority** block first (Ramazan Meeting 2 is the Monday-deadline work), then the original Sprints 7–9, then the standing milestones. Each sprint is a separate CC prompt. Don't start a sprint before the prior one is reviewed/merged unless noted as independent.

---

## Conventions (apply to every sprint / CC prompt)
- Backend is the business source of truth; **verify, don't assume**; never invent endpoints.
- **Never read or stage** `docs/transkript.txt` / `docs/ramazan_transkript*.txt` or their `:Zone.Identifier`. Stage commits by **explicit path**.
- nl + en i18n in lockstep (Dutch primary); every referenced i18n key must resolve (no raw keys on screen).
- ESLint baseline = **49** (47 errors, 2 warnings): add **no** new violations; **never** a synchronous setState in an effect body; for prop-derived state, **key the component by id** (no resync useEffect).
- Backend / migration / RBAC → open a **PR** (CI + Codex). Migrations additive + back-compat. Routine frontend-only → also a PR now (de-facto rhythm).
- Each prompt starts with a sync + a grep GUARD proving the right base, captures the lint baseline, applies any new migration to the dev DB before a FE smoke, and ends with an adversarial review. Screenshots/smokes via **token-inject** (the e2e login form is flaky).
- Co-author trailer on commits: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Where we are (2026-06-05)

**Completed in this gap-closing effort (do NOT rebuild):**
- **Sprint 0** — PR #79 Codex P2 fixes (paginate responsible-managers; key by ticket id) ✅ merged; customer-pricing reference prefill ✅ (shipped as the #86 line below).
- **Sprint 1** — Reschedule frontend control on ticket detail (consumes `/tickets/<id>/schedule/`; SA/CA/BM) ✅.
- **Sprint 2** — Permission editor in-place from the contact (popup/expand; existing page still reachable) ✅.
- **Sprint 3** — Contact-first enforcement audited + invitations restricted to provider staff ✅.
- **Sprint 4** — Sub-tasks **backend** (PR #84): `SubTask` model, nullable `TicketStaffAssignment.sub_task` FK, PA/SA `auto_complete_on_subtasks` flag + roll-up, audit ✅ merged.
- **Sprint 5** — Sub-tasks **frontend** (PR #85): grouped staff slots, sub-task CRUD, PA/SA auto-complete toggle, PII-safe customer view ✅ merged.
- **Customer pricing — surface the service default price** (PR #86): dialog prefills unit price + VAT from the service default; default-price column (incl. inactive services); dropdown shows defaults ✅ merged.
- **Sprint 6** — Recurring **calendar-tick** (PR #87): additive `PlannedOccurrence.is_ad_hoc` (migration 0004) + four idempotent per-date `RecurringJobViewSet` actions (skip-date / add-date / clear-date / calendar) + the month-grid calendar UI + customer/building dropdown swap + per-window pricing clarity. Back-compat with #77. **Follow-up fix in-flight:** bound `add-date` to `[start_date, end_date]` + cap the ad-hoc spawn at `end_date` (Codex P2) — push re-triggers CI; resolve the thread; merge on green.
- **M1 — Notification & message center** (PR #90): in-app notifications feed + recipient-scoped REST + NotificationBell + /notifications page; 5-channel ticket message visibility + RESTRICTED directed messages through the single `filter_messages_visible_to` chokepoint; 3-channel Extra Work thread; EW lifecycle + message notifications ✅ merged.

**Standing infra not yet done:** production deployment; CD (CI exists as PR checks); Sentry DSNs.

---

## Near-term priority — Ramazan Meeting 2 (2026-06-05) + carried-over

> Ramazan wants these by **Monday**. He also wants a **live login link** to poke around himself → the deployment milestone is pulling forward. Department section is **deferred** (do it in person, after these). Re-read `ramazan_transkript (2).txt` + the SoT addendum before scoping each.

### CP — Customer-permissions page (carried over) — do first, one PR (same page)
Backend already supports granting a building a customer user isn't in (`POST /api/customers/<id>/users/<user_id>/access/ {building_id}`, gated only by the Sprint-14 customer↔building link). The FE has `addCustomerUserAccess` wired but the matrix view doesn't surface the control.
- [x] **Add-building control** in the customer-permissions matrix (pick an un-granted building linked to the customer + role → POST). FE-only. **DONE** (branch `feat/cca-company-wide-and-people-consolidation`): surfaced in the People drill-in modal via the reused `ContactPermissionsPanel` (building picker + grantable-role select from `allowed_target_customer_access_roles`, hidden for a company-admin user).
- [x] **Option A — `CUSTOMER_COMPANY_ADMIN` company-wide.** Make CCA grant admin across **all** the customer's buildings from one setting; collapse the per-building rows into a single company-wide status; demote = remove that status. **DONE**: additive `CustomerUserMembership.is_company_admin` flag (migration `0010`, forward-only collapse of existing per-building CCA rows); `company_admin_customer_ids` unioned into scoping (tickets/EW/buildings) + ticket-scope/transition + EW catalog/pricing; `compute_role_defaults`/`compute_scope`/`user_can` short-circuit so no per-building row can downgrade a CCA; dedicated POST/DELETE `/users/<id>/company-admin/` endpoint (gated by `can_manage_customer_company_admins`, audited via a dedicated membership UPDATE signal). **Follow-up (not in this PR):** retire the legacy per-building CCA grant path + rework the B5 grant gate to bind the flag (split-brain); document the `user_can` CustomerCompanyPolicy-bypass decision in the product SoT (owner sign-off).
- [x] **People consolidation + drill-in edit** (Ramazan #5): Contacts / Users / (customer) Employees on **one page** with **drill-in / modal edit** ("click in, edit, leave" — NOT accordion expand). **DONE**: new `/admin/customers/:id/people` page + "People" sidebar tab; one roster with distinct TYPE badges (Contact / Employee / User, several at once); row click opens `CustomerUserManageModal` (company-admin single-status + reused `ContactPermissionsPanel` access editor) — replaced the old `CustomerUsersPage` accordion with the same drill-in. Concepts kept distinct; phone validation unchanged.

### M1 — Notification / message center (Ramazan #1 — his top pain)
Messages on tickets / extra-work / meldingen get lost; nobody sees replies.
- [x] Backend: a notifications feed + per-message "directed-to" (personal/tagged) targeting; recon what already exists (notifications app) before building. Events: new message on a ticket / EW request / melding, and a personally-addressed message.
- [x] FE: a **top-right bell** + a **notifications page**; each item deep-links to the source (ticket/EW/melding). Personal/tagged messages surface to the addressee only.

### M2 — User/staff profile: structured credentials + flexible custom properties + visibility (Ramazan #4, expanded)
**Hybrid model (confirmed):**
- [x] **Structured, typed, compliance-aware credential fields** with built-in rules: **residence permit** (showable; when shown, only expiry date + ID number) · **EU national ID** (**HARD-BLOCKED from any customer — PA/SA only, never a customer-visible PDF**; enforced in code, not a toggle) · **certificates/VCA** (PDF, showable). Documents are **PDF**.
- [x] **Generic custom-property system** on **all** user profiles (staff + customer users): `property name / value / optional PDF attachment`, **add/remove** (e.g. age, salary, contract).
- [x] **Visibility model:** every property/document has a visibility level, **default most-restrictive (provider-only)**; salary-type defaults to **PA/SA-only**; visibility selectable **per-customer and per-staff** (who sees what). Visibility changes on sensitive fields are **audited**.
- [x] Customer-side view honours visibility + the customer permission gate; the EU-ID block is unconditional.

### M3 — Navigation / IA (Ramazan #1-nav)
- [ ] Move **Recurring Work** and the **customer price-quote-request** flow to live **under Extra Work** (sub-items), not as separate top-level / not performed directly in Extra Work.

### M4 — Extra Work billing: monthly invoice run + billing-month (Ramazan #2)
Billing must key off a **billing month you set**, not the customer's final-approval date (work done May 31, approved Jun 7 → bills in **May**).
- [ ] Backend: a settable **billing month / invoice date** on completed extra work (decoupled from approval); an **"invoice run" per month** concept; filters by month + status (completed / invoiced). Extends the existing EW-revenue report.
- [ ] FE: a **monthly filter** on Extra Work (time-range select) + status filter; surface the billing-month field at completion; revenue/invoice export per month (PDF/CSV).

### M5 — Customer pricing: custom line + category edit + bulk raise (Ramazan #3)
Builds on #86.
- [ ] **Custom/ad-hoc price line**: add a price for a service **not in the catalog** (free-text name + price + VAT), customer-specific.
- [ ] **Category editing** on the service catalog; a **bulk price-raise** helper (raise many catalog/customer prices at once).

### M6 — Customer detail (provider side) + dashboard "my X" (Ramazan #7)
- [ ] On a customer's page, surface **that customer's** tickets / extra-work / **price-quote-requests** / meldingen as drill-in sub-tabs (mirror existing surfaces).
- [ ] Dashboard: a **"my X"** aggregation (my tickets / meldingen / extra-work / requests).

### M7 — Melding (Ramazan #8)
- [ ] **Melding = a customer-created waiting ticket** (the Dutch-facing name; NOT a separate concept). Verify the customer-create-ticket path exists + is surfaced as "melding" in the customer UI; close any gap.

---

## Original remaining sprints (after the Meeting-2 block)

### Sprint 7 — Bulk select-and-approve
The father's "select" button: confirm many completions at once.
- [ ] Backend bulk-complete/approve endpoint (provider-management; validates each; clear all-or-nothing vs per-item semantics) + tests.
- [ ] FE multi-select + bulk-confirm on a completions/queue view; gates/e2e green; screenshots.

### Sprint 8 — Coverage verification & surface
Verify, then surface only what's missing.
- [ ] **Unable-to-complete**: the "couldn't finish + reason → manager notification" path is surfaced (SoT §4.4).
- [ ] **Actual-hours**: hourly EW finalize is surfaced (SoT §5.12).
- [ ] **Copy-from-default**: a "copy default prices to this customer" action is surfaced (SoT §5.9).
- [ ] Occurrence **skip/cancel** surfaced; any other unsurfaced endpoint closed.

### Sprint 9 — Premium UI/UX polish
- [ ] A cohesive visual polish pass for a premium look (tokens, spacing, density, consistency), with extra attention to the recurring + sub-task + new profile/notification surfaces. No behavior changes; gates/e2e green; before/after screenshots.

---

## Standing milestones
- [ ] **Production deployment** (pull forward — Ramazan wants a live link): VPS, TLS, real SMTP, non-root containers, `ALLOWED_HOSTS` fix for the Docker internal healthcheck (broken with `DEBUG=False`).
- [ ] **CD** via GitHub Actions (CI already runs as required PR checks: backend Django/Postgres/Redis + frontend lint/tsc/build).
- [ ] **Sentry** DSNs (integration is merge-safe / empty-DSN no-op; needs Göktuğ to create the account + provide DSNs).
- [ ] **Backend follow-up:** redact nested `sub_tasks` for `CUSTOMER_USER` in `TicketDetailSerializer` (like `assigned_staff`) — the FE currently does a PII-safe summary client-side.

## Deferred
- [ ] **Department section** — do in person with Ramazan, after the Meeting-2 block.
