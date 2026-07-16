# Osius — Gap-Closing Sprint Checklist

**Updated 2026-06-23** — post PR #98 (Sprint 8 merged). Meeting-2 block + Sprints 7–8 all shipped.

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

> The **Monday** deadline no longer applies. A **dev/test live link** (`crmtest.osius.nl`) already exists and Ramazan has access, so the "live link" need is met — real **production deployment** remains its own standing milestone (no longer pulled forward for that reason). The **Department section** and a full **requirements + codebase audit** are folded into the **Fixing & Auditing Sprint** below.

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
- [x] Move **Recurring Work** and the **customer price-quote-request** flow to live **under Extra Work** (sub-items), not as separate top-level / not performed directly in Extra Work.

### M4 — Extra Work billing: monthly invoice run + billing-month (Ramazan #2) ✅ DONE
Billing must key off a **billing month you set**, not the customer's final-approval date (work done May 31, approved Jun 7 → bills in **May**).
- [x] Backend (commits 1 / 2a–2e): settable **billing month / `invoice_date`** on `ExtraWorkRequest` (decoupled from approval; migration 0013), provider-only redaction; per-month **invoice run** — mark/clear-invoiced by **company + month** (single source of truth `extra_work/billing.py`; earned = spawned ticket CLOSED; billing month = `COALESCE(invoice_date, completion)`); **EW list filters** (billing month + invoice status); **EW-revenue report** anchored on billing month + status filter (CSV/PDF exports track it).
- [x] FE (commits 3a–3d): billing-month picker + invoice-status filter + invoiced column on the EW list (provider-only); **invoice-run toolbar** (mark/clear by month + in-view company, confirm-gated); itemized client-side **CSV export** of the filtered list; per-EW **billing-month override** on the detail page (via 2b).
- Shipped on branch `feat/m4-billing-month` (12 commits); deployed + verified on the dev/test box.

### M5 — Customer pricing: custom line + category edit + bulk raise (Ramazan #3) ✅ DONE
Builds on #86.
- [x] **Custom/ad-hoc price line**: add a price for a service **not in the catalog** (free-text name + price + VAT), customer-specific. **DONE** (PR #94): additive `CustomerCustomPrice` model (no service FK, resolver/cart/billing-isolated), provider-only CRUD at `/api/customers/<id>/custom-pricing/` + "Custom price lines" section on the customer pricing page; full-CRUD audit.
- [x] **Category editing** on the service catalog; a **bulk price-raise** helper (raise many catalog/customer prices at once). **DONE** (PR #94): category editing already shipped (Sprint 28); bulk-raise both **customer contract prices** (`/api/customers/<id>/pricing/bulk-raise/` — new validity-window rows, history-preserving, per-service de-dup) and **catalog defaults** (`/api/services/bulk-raise/` — in place, billing-isolated), % or fixed, with UI on the customer-pricing and services pages.

### M6 — Customer detail (provider side) + dashboard "my X" (Ramazan #7) ✅ DONE
- [x] On a customer's page, surface **that customer's** tickets / extra-work / **price-quote-requests** / meldingen as drill-in sub-tabs (mirror existing surfaces). **DONE** (PR #95).
- [x] Dashboard: a **"my X"** aggregation (my tickets / meldingen / extra-work / requests). **DONE** (PR #95).

### M7 — Melding (Ramazan #8) ✅ DONE
- [x] **Melding = a customer-created waiting ticket** (the Dutch-facing name; NOT a separate concept). Verify the customer-create-ticket path exists + is surfaced as "melding" in the customer UI; close any gap. **DONE** (PR #96).

---

## Original remaining sprints (after the Meeting-2 block)

### Sprint 7 — Bulk select-and-approve  ✅ DONE (PR #97)
The father's "select" button: confirm many completions at once.
- [x] Backend bulk endpoint DONE (PR #97): `POST /api/tickets/bulk-status/` advances tickets `WAITING_MANAGER_REVIEW → WAITING_CUSTOMER_APPROVAL`, per-item atomic via `apply_transition`, explicit source-status guard (Codex P1 fix: rejects wrong-state tickets even for SUPER_ADMIN), scoped not-found, gated 403 for CUSTOMER_USER/STAFF; tests added.
- [x] FE multi-select + bulk-confirm on the dashboard manager-review queue ("Te bevestigen" preset); gates green.

### Sprint 8 — Coverage verification & surface  ✅ DONE (PR #98)
- [x] **Unable-to-complete** (§4.4): already surfaced via the slot-completion path (AgendaPage) — requires a reason and fires `send_slot_unable_to_complete_email` to the manager. The legacy ticket-level `/tickets/<id>/unable-to-complete/` endpoint is superseded by the slot model and intentionally left unsurfaced.
- [x] **Actual-hours** (§5.12): hourly EW finalize surfaced on the Extra Work detail page (provider-only panel → `POST /api/extra-work/<id>/actual-hours/`). Covers BOTH the INSTANT-cart route AND proposal-routed/auto-start hourly EWs — the active set follows `active_priced_lines`, fixing the Codex P1 dead-end where proposal-routed hourly EWs were blocked by the `actual_hours_required` completion gate with no entry UI. Legacy pricing lines stay out (no `actual_hours` column; never gate).
- [x] **Copy-from-default** (§5.9): "Copy from defaults" action on the customer pricing page → `POST /api/customers/<id>/pricing/copy-from-default/` (active-services multi-select + valid_from/optional valid_to, all-or-nothing).
- [x] Occurrence **skip/cancel** surfaced (`skipOccurrence`/`cancelOccurrence` on RecurringJobDetailPage); no other unsurfaced in-scope endpoint found.

### Sprint 9 — Premium UI/UX polish (light, no behavior change — runs now; PR #99)
- [ ] A cohesive visual polish pass for a premium look (tokens, spacing, density, consistency), with extra attention to the recurring + sub-task + new profile/notification surfaces. **No behavior changes**; gates/e2e green; before/after screenshots. Feature-level layout asks (e.g. enlarging the right-side responsible-manager / assignment cards — see Backlog note #7) are DEFERRED to the Fixing & Auditing sprint, pending Ramazan + father feedback.

## Roadmap — phase order (updated 2026-06-23 after the Ramazan mini-meeting)
1. ✅ **Sprint 9 — light UI/UX polish** → PR #99, deployed.
2. **Quick-wins sprint** (from received feedback that further feedback can't invalidate) → **PR #100**, then deploy: **RF-3** Tickets top-level page · **RF-4** tuck the ticket audit timeline away · **RF-5** attachment type + in-app preview (recon the backend serving path).
3. **Proposal-preview sprint** → **PR #101**, then deploy: **RF-6** split-screen live proposal preview.
4. *(Optional, if the full batch is slow to arrive)* **RF-2** — unified Add-price flow with an "Other/Custom" option (small, self-contained).
5. **Feedback completion** — Ramazan's full side-by-side gap list; father's invoice-integration answers; RF-7 pinpointed.
6. **Fixing & Auditing Sprint** — the full batch + **RF-1** WhatsApp-style message inbox (needs per-recipient read state — real backend work) + **RF-8** module/permission presentation + **RF-9**/backlog #7 density + Department + RF-7 + codebase audit + reconcile this checklist.
7. **E2E testing sprint**, then **Frontend testing sprint** — against the settled, post-feedback system.
8. **Production hardening** (TLS · real SMTP · non-root containers · `ALLOWED_HOSTS` healthcheck fix under `DEBUG=False` · Postgres backups) → **CD** → **Sentry DSNs**; plus the small `sub_tasks` CUSTOMER_USER redaction follow-up. → Production-ready, barring further feedback.

**Ordering decision (testing vs Fixing & Auditing):** testing runs AFTER Fixing & Auditing. The missing coverage is E2E + frontend (the UI layer); the backend already has a CI test suite protecting the audit's backend changes. The Fixing & Auditing sprint mostly reshapes the UI (new dropdowns, invoice page/PDF, attachment previews, layout/density), so E2E/frontend tests written first would be invalidated by those changes — tests deliver durable value when they lock in final behavior. *Caveat — decide at the fork:* if the feedback returns small/cosmetic, the UI is already near-final and testing-first becomes reasonable; revisit when feedback lands.

## Sprint 9 — Feedback & Backlog Notes (captured 2026-06-23; NOT for implementation yet)
Göktuğ's pre-feedback recollections, to be reconciled with Ramazan + father feedback before anything is built. These feed the **Fixing & Auditing Sprint**. Several intersect shipped work — flagged inline.

1. **Custom units on the Service "Other" unit type.** "Other" should accept free-text units (cm, m³, …). Possibly customer-specific — even per-room. Open: how far down unit definitions go (customer / building / room).
2. **Dedicated invoices page + workflow.** Extra work lives in the stream today; may want its own invoice page/workflow; possible "invoiced" status on EW. (Partly built — M4 shipped a settable billing month, a per-month invoice run that marks/clears "invoiced," + an invoice-status filter & invoiced column. New asks: a standalone invoices page + item 3.)
3. **Invoice PDF + send-to-customer.** A PDF invoice system; likely Ramazan feedback on how invoices / customer feedback get sent. Builds on M4's billing-month + run.
4. **Notifications history / read messages.** Can't reliably see past notifications; need full history incl. already-read items → audit how the feed surfaces read vs unread + retention. (Relates to M1 / PR #90.)
5. **Attachment in-app preview.** Clicking an attachment downloads it; want in-app viewing, with PDF preview inside the app. (Flagged deliberately — Ramazan may not raise it.)
6. **Customer "event" + "department" fields.** On customer create, possibly two more dropdowns: event + department. Department likely customer-specific (ties into the deferred Department section). "Event" may be a selectable event type, not a category — undecided.
7. **Right-side card layout / density.** Assignment / responsible-manager / building-manager / scheduling / ticket-detail / add-slot / add-subcard / manager sections are good UX. Possible: make the right-side cards (responsible manager / assignment) larger with more horizontal space so they read as primary, not small technical details; maybe light explanatory copy. Decide post-feedback.
8. **Customer surfaces — keep combined.** Separate pages for a customer's EW / quote-requests / tickets likely won't be liked; want one customer page with tabs/subsections. (Already built — M6 / PR #95 put these on the customer page as drill-in sub-tabs. Validate/refine vs Ramazan's preference, not rebuild.)
9. **Baseline:** system is in good shape; editing customers/users + general flows are fine; no major issues right now.

### Received feedback (logged as it arrives — reconcile into the Fixing & Auditing Sprint)

**RF-1 — Notifications "messages" overview, WhatsApp-style (father, received 2026-06-23, voice memo).** He wants the main messages view to work like a WhatsApp chat list (WhatsApp used as the explicit analogy):
- A conversation-list view where **each row is a ticket** (a ticket ≈ a WhatsApp chat).
- Each row shows the **ticket name**, an **avatar** — the person who last acted on the ticket, or (preferably) the **customer company logo**; possibly both — and an **unread-count badge** (1, 2, … like WhatsApp).
- At a glance an admin sees: **which tickets have messages**, **who wrote the latest message**, and **who hasn't read it** (per-recipient read state — who is the one that hasn't read, not just an unread flag).
- **Searchable / filterable** (a ticket filter on this view).
- Goal: *"see all the messages in one place"* — a chat-style aggregated inbox over tickets. Messages still live inside their tickets; this is a unified inbox **surface into** them, not a new home for messages.
- Sharpens backlog **#4** (notifications history / read-state) + the **M1** notification center. Note: per-recipient read tracking ("who hasn't read") is a real capability distinct from a simple unread badge (roster-level read receipts).

**RF-2 — Fold custom price lines into the regular "Add price" flow (Göktuğ, 2026-06-23).** On the customer pricing page, merge the separate "add custom price" surface into the regular **Add price line** flow: the service dropdown gains an **"Other" / "Custom"** option, and selecting it lets the user type a **free-text custom service name** and a **free-text custom unit name** — one unified add-price flow for both catalog services and ad-hoc custom lines. Ties into backlog **#1** (custom units on the "Other" unit type). Note: M5 (PR #94) shipped these today as a separate "Custom price lines" section (the `CustomerCustomPrice` model); this is a UX consolidation, not net-new pricing capability.

**RF-3 — Tickets as a top-level page (Ramazan, 2026-06-23, in-person).** The sidebar jumps straight to "New Ticket"; there is no Tickets page (the list lives on the dashboard). Mirror Extra Work: a top-level **Tickets** page (list) with **New Ticket** reached from inside it.

**RF-4 — Ticket detail: the audit timeline dominates the page (Ramazan, 2026-06-23; raised twice).** The "who did what / changed what" timeline is a good, transparent feature but currently occupies the **entire main column** of the ticket detail (the actual ticket details sit in the right sidebar), which overwhelms at first glance. Move it to a discreet spot — a right-corner control, a tab, or a collapsed drawer — visible on demand ("ileride lazım oluyor ama ilk bakışta lazım değil"). His stated general principle: **at a glance, minimal; depth behind a click** — apply it to dense surfaces. Build-time note: the timeline also carries low-signal rows (e.g. "Created · Ticketmanagerassignment — No tracked field changed") worth condensing/pruning while relocating.

**RF-5 — Attachment preview (Ramazan, 2026-06-23; CONFIRMS backlog #5).** He hit it live: attaching a file was non-obvious at first, and clicking an attachment downloads it. Promised in-meeting: show the **file type without clicking**, and clicking opens an **in-app view** (PDF inline) instead of downloading. May need a small backend tweak (inline Content-Disposition / preview endpoint) — recon at build time.

**RF-6 — Live proposal-PDF preview, split screen (Ramazan, 2026-06-23).** While building a price proposal, the right half of the screen shows the proposal **rendered as it will look** (a visual preview, not an opened PDF file), updating as lines are entered. He was very enthusiastic; agreed in-meeting. The proposal-PDF endpoint already exists — this is a preview pane over it (v1 may refresh on save rather than per keystroke).

**RF-7 — Extra Work detail: pricing section "big tabs" (Ramazan, 2026-06-23; location confirmed, element TBC).** In the **Extra Work detail page's pricing area**, big tab/block elements appeared where he prefers click-in navigation ("üstüne basıp gir; burayı çıkartalım"). Göktuğ confirms it's the EW pricing section; the **exact element is still to be pinpointed** (likely the pricing/proposal blocks) — clarify with Ramazan's full review before acting.

**RF-8 — Simplified module/permission surface + future modules (Ramazan, 2026-06-23).** Think of melding / extra work as **modules** (not every customer gets extra work); future third modules possible (e.g. **DKS** — assumed: their daily quality-control system, Dagelijks Controle Systeem). One user-management surface grants module access — no access ⇒ the module disappears entirely for that user. Keep the visible permission UI to **3-4 coarse toggles per module** (e.g. can open EW / can close / can act / can respond), bundling the fine-grained permissions behind them: "simple at a glance; the depth exists but the user never needs to see it" — incl. hiding the delegated who-can-grant-what depth. Osius already enforces fine-grained permissions and hides inaccessible surfaces — the ask is a simpler **presentation layer** (presets/bundles). Design with Ramazan in the Fixing & Auditing sprint (ties into Department / backlog #6).

**RF-9 — Assignment/slot page density (Ramazan, 2026-06-23; CONFIRMS backlog #7).** Too much info at once on the assignment surface; hard to parse what's what. Ideas: enlarge/clarify the sub-task/detail areas (Göktuğ) or a simple "assign to someone" button flow (Ramazan). Stays deferred to Fixing & Auditing per backlog #7 — now with his confirmation.

**Meeting notes (2026-06-23, for the audit sprint):** Department/event are **category-like** fields; names must stay editable/customer-flexible ("herkese uymuyor") — refines backlog #6. Ramazan will do a **full side-by-side review** vs their current system and deliver the complete gap list at once (the agreed batch — Göktuğ implements it in one pass). He validated the pricing work (bulk raise, customer-specific prices, **price history preserved — old EWs keep their old prices**). The credentials/permissions area of their *current* tool is their worst pain point; he'll study ours as the reference.

---

## Standing milestones
- [ ] **Production deployment** (the dev/test link already covers the "live link" need; this is the real thing): VPS, TLS, real SMTP, non-root containers, `ALLOWED_HOSTS` fix for the Docker internal healthcheck (broken with `DEBUG=False`), Postgres backups.
- [ ] **CD** via GitHub Actions (CI already runs as required PR checks: backend Django/Postgres/Redis + frontend lint/tsc/build).
- [ ] **Sentry** DSNs (integration is merge-safe / empty-DSN no-op; needs Göktuğ to create the account + provide DSNs).
- [ ] **Backend follow-up:** redact nested `sub_tasks` for `CUSTOMER_USER` in `TicketDetailSerializer` (like `assigned_staff`) — the FE currently does a PII-safe summary client-side.

## Deferred
- [ ] **Department section** — folded into the **Fixing & Auditing Sprint** below (design + build in person with Ramazan + father there).

## Fixing & Auditing Sprint (planned — after the remaining sprints)
Opened once the remaining sprint work is done. Scope:
- [ ] Incorporate the further changes/additions Ramazan + father want (specifics TBD — Göktuğ will provide them).
- [ ] Codebase audit: review how everything works end-to-end; hunt for bugs / dead code / inconsistencies; confirm each shipped feature behaves as intended.
- [ ] Reconcile this checklist against the real codebase (tick/realign every item to what's actually implemented).
- [ ] Department section (deferred above) — design + build in person with Ramazan + father.

## E2E Testing Sprint (planned — after Fixing & Auditing)
- [ ] End-to-end (Playwright) coverage of the critical full-stack flows on the settled post-feedback system: auth/login, create ticket + melding, ticket lifecycle (staff complete → manager review → customer approval), extra-work request → proposal/instant → actual-hours finalize, customer pricing (contract / custom / bulk-raise / copy-default), notification deep-links. Use the token-inject pattern (the e2e login form is flaky). Green in CI.

## Frontend Testing Sprint (planned — after E2E)
- [ ] Component/unit tests for high-value frontend logic that lacks coverage (pricing-amount display, active-priced-line selection, permission/visibility gating, the drill-in people/permissions flows, notification rendering). Establish the test runner + a CI gate; do not regress the ESLint baseline (49).
