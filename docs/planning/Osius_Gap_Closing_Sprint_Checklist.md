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

### Sprint 9 — Premium UI/UX polish  ✅ DONE (PR #99, deployed)
- [x] A cohesive visual polish pass for a premium look (tokens, spacing, density, consistency), with extra attention to the recurring + sub-task + new profile/notification surfaces. **No behavior changes**; gates/e2e green; before/after screenshots. Feature-level layout asks (e.g. enlarging the right-side responsible-manager / assignment cards — see Backlog note #7) are DEFERRED to the Fixing & Auditing sprint, pending Ramazan + father feedback.

## Roadmap — phase order (updated 2026-06-23 after the Ramazan mini-meeting)
1. ✅ **Sprint 9 — light UI/UX polish** → PR #99, deployed.
2. **Quick-wins sprint** (from received feedback that further feedback can't invalidate) → **PR #100**, then deploy: **RF-3** Tickets top-level page · **RF-4** tuck the ticket audit timeline away · **RF-5** attachment type + in-app preview (recon the backend serving path).
3. **PDF & Preview sprint** → **PR #101**, then deploy: **RF-10** proposal-PDF quality (Dutch-only) · **RF-6** split-screen live proposal preview · **RF-12** attachment thumbnails.
4. **Continue-without-feedback work (agreed 2026-06-24):** ~~**PR #102** — `sub_tasks` CUSTOMER_USER redaction (privacy) + **RF-2** unified Add-price flow with "Other/Custom" (adds an additive free-text `custom_unit_label` to CustomerCustomPrice — also delivers the core of backlog #1).~~ **DONE — PR #102, deployed to crmtest.** ~~Then **PR #103** — **RF-1** WhatsApp-style message inbox (per-recipient read state, aggregation endpoint, logo avatars) with **RF-11** (EW Messages card restyle) riding along.~~ **DONE — PR #103, deployed to crmtest.** ~~Then **PR #104** — **IA & Effectiveness** consolidation: disjoint Notificaties/Berichten (message events out of the feed by default), customer-detail content tabs 4→2 with filter chips, inbox unread-toggle + mark-all-read, clarity pass (subtitles, SA empty-state, terminology sweep).~~ **DONE — PR #104, deployed to crmtest.**
5. **Post-#104 queue (agreed with Göktuğ, 2026-06-25; queue collapsed 2026-06-26):**
   - ~~**PR #105** — **RF-14** EW-detail comfort (collapsible Requested-services/Pricing-proposal cards, scrollable long tables, preview-pane toggle + relaxed spacing) + **RF-15** formal branded PDFs (Osius logo header, embedded font with real €, both PDF families).~~ **DONE — PR #105, deployed to crmtest.**
   - ~~**PR #106** — **combined queue sprint** (the former #106–#109 collapsed into one): **RF-8** permission bundles (module cards, approved design below) + **RF-9** calm assignment area (simple-first AND enlarged details) + **RF-13** invoices v1 (Facturen overview, customer+building filters, existing mark-invoiced granularity) + **RF-16** dashboard = overview/attention cards, full lists exclusive to Tickets / Extra Work pages.~~ **DONE — PR #106, deployed to crmtest.**
   - ~~**PR #107** — **RF-17** collapsible/wider ticket-detail right column + **RF-18** dashboard info widgets + **RF-19** stable proposal add-line grid (frontend-only).~~ **DONE — PR #107, merged (c3ae017), deployed to crmtest.**
   - ~~**PR #108** — **owner-review round-2 batch** (all decisions locked 2026-06-28, see the decision block below): Option-A dashboard rebuild · single-row proposal composer + Custom unit (additive `custom_unit_label` on ProposalLine) · Bulk adjust (raise+lower) · UI consistency sweep (toggles vs restyled checkboxes, multi-select scroll + Select all/Clear all) · customer detail Invoices + Reports sub-tabs · EW-list mark-invoiced → Facturen pointer · ticket-detail right cards default-collapsed (Workflow open) · seed enrichment.~~ **DONE — PR #108, squash-merged (aed15f7), deployed to crmtest, seed enrichment applied.**
   - ~~**PR #109** — **audit fixes + owner review round-3 + SA notifications + docs**: audit P2-1 (EW billing audit trail) · P2-2 (ticket customer-approval user_can gate) · P3-1 (billing-month Europe/Amsterdam localtime) · P3-3 (SA CONVERTED_TO_EXTRA_WORK terminal guard) · round-3 fixes · SA per-company notification subscriptions (in-app v1) · eslint-disable cleanup · docs polish.~~ **DONE — PR #109, squash-merged (5b37e6f), deployed to crmtest.**
   - **PR #110** — **round-4 polish** (feat/sprint-110, held for owner review): collapse Responsible-managers + Scheduling by default · taller Extra Work live-preview (embed fills the pane, measured 420→747px) · seed 15 extra Osius demo buildings so the building pickers visibly overflow the capped scroll.
6. **Feedback completion** — Ramazan's full side-by-side gap list; father's invoice-integration answers; RF-7 pinpointed.
7. **Fixing & Auditing Sprint** — the full batch + Department + RF-7 + codebase audit + reconcile this checklist. (RF-8 and RF-9 pulled forward into the #105–#109 queue above.)
8. **E2E testing sprint**, then **Frontend testing sprint** — against the settled, post-feedback system.
9. **Production hardening** (TLS · real SMTP · non-root containers · `ALLOWED_HOSTS` healthcheck fix under `DEBUG=False` · Postgres backups) → **CD** → **Sentry DSNs**. → Production-ready, barring further feedback.

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

**IA decisions (2026-06-25):** Notifications + Messages both stay, disjoint — message-type events default OFF in the feed (user-mutable opt-in); names locked Notificaties / Berichten / Melding-reserved; customer detail content tabs merged 4→2 with filter chips; inbox gets unread toggle + mark-all-read; Request-a-Quote nav stays (Ramazan); SA notification-emptiness confirmed BY DESIGN (deliberate fan-out exclusion, directed messages bypass it) — documented, not changed.

**RF-1 — Notifications "messages" overview, WhatsApp-style (father, received 2026-06-23, voice memo).** He wants the main messages view to work like a WhatsApp chat list (WhatsApp used as the explicit analogy):
- A conversation-list view where **each row is a ticket** (a ticket ≈ a WhatsApp chat).
- Each row shows the **ticket name**, an **avatar** — the person who last acted on the ticket, or (preferably) the **customer company logo**; possibly both — and an **unread-count badge** (1, 2, … like WhatsApp).
- At a glance an admin sees: **which tickets have messages**, **who wrote the latest message**, and **who hasn't read it** (per-recipient read state — who is the one that hasn't read, not just an unread flag).
- **Searchable / filterable** (a ticket filter on this view).
- Goal: *"see all the messages in one place"* — a chat-style aggregated inbox over tickets. Messages still live inside their tickets; this is a unified inbox **surface into** them, not a new home for messages.
- Sharpens backlog **#4** (notifications history / read-state) + the **M1** notification center. Note: per-recipient read tracking ("who hasn't read") is a real capability distinct from a simple unread badge (roster-level read receipts).
- **Design locked 2026-06-24 (Göktuğ):** per-user-per-thread read cursors (a `MessageReadCursor` with `last_read_at`, advanced when a thread's messages are viewed); read receipts ("who hasn't read") are **provider-management-only** (SA/CA/BM) — customer users never see who-hasn't-read, only their own unread state. The inbox covers **both** thread kinds (ticket + Extra Work) with **kind / date-range / search / unread-only** filters, ordered by latest-visible-message time. Every count, snippet, and receipt is computed **per-viewer through the existing five-mode visibility matrix** — reuse the canonical visibility filter, never reimplement it. Threads with zero visible messages don't appear. Additive `User.profile_photo`, `Customer.logo`, `Company.logo` (jpeg/png/webp, magic-byte validated, ~2 MB cap) with **hardcoded** permission rules: any user sets their own profile photo; a customer's logo only by that customer's `CUSTOMER_COMPANY_ADMIN`; the provider company logo only by that company's `COMPANY_ADMIN`; `SUPER_ADMIN` may change any photo/logo. **RF-11** (restyle the EW detail Messages card in the inbox's design language, presentation-only) rides along.

**RF-2 — Fold custom price lines into the regular "Add price" flow (Göktuğ, 2026-06-23).** On the customer pricing page, merge the separate "add custom price" surface into the regular **Add price line** flow: the service dropdown gains an **"Other" / "Custom"** option, and selecting it lets the user type a **free-text custom service name** and a **free-text custom unit name** — one unified add-price flow for both catalog services and ad-hoc custom lines. Ties into backlog **#1** (custom units on the "Other" unit type). Note: M5 (PR #94) shipped these today as a separate "Custom price lines" section (the `CustomerCustomPrice` model); this is a UX consolidation, not net-new pricing capability.

**RF-3 — Tickets as a top-level page (Ramazan, 2026-06-23, in-person).** The sidebar jumps straight to "New Ticket"; there is no Tickets page (the list lives on the dashboard). Mirror Extra Work: a top-level **Tickets** page (list) with **New Ticket** reached from inside it.

**RF-4 — Ticket detail: the audit timeline dominates the page (Ramazan, 2026-06-23; raised twice).** The "who did what / changed what" timeline is a good, transparent feature but currently occupies the **entire main column** of the ticket detail (the actual ticket details sit in the right sidebar), which overwhelms at first glance. Move it to a discreet spot — a right-corner control, a tab, or a collapsed drawer — visible on demand ("ileride lazım oluyor ama ilk bakışta lazım değil"). His stated general principle: **at a glance, minimal; depth behind a click** — apply it to dense surfaces. Build-time note: the timeline also carries low-signal rows (e.g. "Created · Ticketmanagerassignment — No tracked field changed") worth condensing/pruning while relocating.

**RF-5 — Attachment preview (Ramazan, 2026-06-23; CONFIRMS backlog #5).** He hit it live: attaching a file was non-obvious at first, and clicking an attachment downloads it. Promised in-meeting: show the **file type without clicking**, and clicking opens an **in-app view** (PDF inline) instead of downloading. May need a small backend tweak (inline Content-Disposition / preview endpoint) — recon at build time.

**RF-6 — Live proposal-PDF preview, split screen (Ramazan, 2026-06-23).** While building a price proposal, the right half of the screen shows the proposal **rendered as it will look** (a visual preview, not an opened PDF file), updating as lines are entered. He was very enthusiastic; agreed in-meeting. The proposal-PDF endpoint already exists — this is a preview pane over it (v1 may refresh on save rather than per keystroke).

**RF-7 — Extra Work detail: pricing section "big tabs" (Ramazan, 2026-06-23; location confirmed, element TBC).** In the **Extra Work detail page's pricing area**, big tab/block elements appeared where he prefers click-in navigation ("üstüne basıp gir; burayı çıkartalım"). Göktuğ confirms it's the EW pricing section; the **exact element is still to be pinpointed** (likely the pricing/proposal blocks) — clarify with Ramazan's full review before acting.

**RF-8 — Simplified module/permission surface + future modules (Ramazan, 2026-06-23).** Think of melding / extra work as **modules** (not every customer gets extra work); future third modules possible (e.g. **DKS** — assumed: their daily quality-control system, Dagelijks Controle Systeem). One user-management surface grants module access — no access ⇒ the module disappears entirely for that user. Keep the visible permission UI to **3-4 coarse toggles per module** (e.g. can open EW / can close / can act / can respond), bundling the fine-grained permissions behind them: "simple at a glance; the depth exists but the user never needs to see it" — incl. hiding the delegated who-can-grant-what depth. Osius already enforces fine-grained permissions and hides inaccessible surfaces — the ask is a simpler **presentation layer** (presets/bundles). Design with Ramazan in the Fixing & Auditing sprint (ties into Department / backlog #6).

**RF-9 — Assignment/slot page density (Ramazan, 2026-06-23; CONFIRMS backlog #7).** Too much info at once on the assignment surface; hard to parse what's what. Ideas: enlarge/clarify the sub-task/detail areas (Göktuğ) or a simple "assign to someone" button flow (Ramazan). Stays deferred to Fixing & Auditing per backlog #7 — now with his confirmation.

**RF-10 — Proposal PDF: text overlap + professional pass, Dutch-only (Göktuğ + Ramazan, 2026-06-24).** Root cause verified: `proposal_pdf.py` writes `"{qty} x {UNIT_ENUM}"` into a fixed 22mm fpdf2 cell with no width fitting — long enums (SQUARE_METERS) overflow into the Unit-price column (proposal-12 broken; proposal-10 fits only because `1.00 x OTHER` is short). Fix in the PDF & Preview sprint: humanized **Dutch** unit labels + width-aware cells; all labels/status/urgency in Dutch (PDF is Dutch-only, like the emails); Dutch number/money formatting (€, comma decimals) with the font question (€ glyph / charset) decided at recon; a modest professional layout pass (numeric right-alignment, consistent rows, footer). Otherwise the PDF structure is fine per Göktuğ.

**RF-11 — EW detail: Messages card looks out of place (Göktuğ, 2026-06-24).** The Messages section on the Extra Work detail page sits awkwardly (full-width card between Details and Notify-people). DEFERRED to Fixing & Auditing: messaging UX is being rethought there anyway (RF-1 WhatsApp-style inbox) — restyle once, not twice.

**RF-12 — Attachment thumbnails without a click (Göktuğ, 2026-06-24).** Post-#100, click-to-view + download work well. New ask: the attachment cards should show a real preview with no click — images render the actual image as the card; PDFs render a first-page thumbnail (client-side render feasibility decided at recon; graceful fallback to the type badge). Ships in the PDF & Preview sprint.

**RF-13 — Invoices get their own page (Göktuğ, 2026-06-24).** Confirms backlog #2: a dedicated invoices page/workflow is the direction. Waits on the father's invoice-integration answers; designed in Fixing & Auditing.

**RF-14 — EW detail pricing area: preview squeeze + long-list comfort (Göktuğ, 2026-06-25).** The live proposal preview (RF-6) squeezes the Pricing proposal section; relax it. Make **Requested services** + **Pricing proposal** collapsible/scrollable for long lists. May be what RF-7 meant — **RF-7 itself stays open** for Ramazan to pinpoint.

**RF-15 — Formal branded PDFs (Göktuğ, 2026-06-25).** Osius logo header + embedded font with real € across **proposal PDFs and report PDF exports** — a formal, branded document pass on both PDF families.

**RF-16 — Dashboard and Tickets show nearly the same content (Göktuğ, 2026-06-25).** Distinction/polish between the two surfaces — queued after the current run.

**Decisions (with Göktuğ, 2026-06-25):** **RF-8** = design+build now (bundle list pending Göktuğ's sign-off); **RF-9** = simple-first AND enlarged details, combined; **RF-13** = v1 invoices overview now, filterable by customer AND building; tickets get **NO** invoiced status (billing stays on EW; convert-to-EW is the bridge).

**Decisions (with Göktuğ, 2026-06-26 — the #106 combined sprint):** **RF-8 bundle design approved:** module cards **Meldingen** + **Extra werk**, each a master on/off + 3 coarse toggles, all existing depth behind an **Advanced** ("Geavanceerd") section. **RF-9 direction:** simple-first AND enlarged details combined (collapsed summary + prominent Toewijzen; expand for the enlarged detail layout). **RF-13 v1 scope:** overview page, customer+building filters, the existing mark-invoiced granularity — no new billing model. **RF-16 direction:** dashboard = overview/attention cards ("Te bevestigen", "Niet toegewezen", "Recente activiteit"); the full lists live exclusively on the Tickets / Extra Work pages.

**RF-17 — Ticket-detail right-side sections not collapsible, narrow column (Göktuğ, 2026-06-27).** The right-side sections (Workflow, Scheduling, Ticket Details, Assignment, Responsible managers, …) are not collapsible and waste horizontal space — make them collapsible and widen the column. Fulfills the card half of backlog #7 (owner's call, without waiting for Ramazan).

**RF-18 — Dashboard too empty (Göktuğ, 2026-06-27).** Add compact info widgets from existing endpoints: unread messages, awaiting pricing, proposals awaiting customer, month billing open/invoiced, today's slots.

**RF-19 — Proposal-builder add-line form reflows (Göktuğ, 2026-06-27).** The add-line form reflows as content grows, pushing the Internal/Customer note down — stabilize the grid.

**#106 review (Göktuğ, 2026-06-27):** #106 deployed + owner-reviewed; the invoices page and settings approved as-is. → Sprint #107 = RF-17 + RF-18 + RF-19 (frontend-only). **DONE — PR #107, merged (c3ae017).**

**Owner review round 2 (2026-06-28), all locked:** dashboard rebuilt to Option A (4-KPI hero · 'Aandacht nodig' priority list · 'Vandaag' column · 'Mijn werk' chips); proposal composer single-row with modal editors (Description strict-modal per owner); proposal lines gain a Custom unit (additive custom_unit_label on ProposalLine); bulk-raise becomes Bulk adjust (raise+lower, guarded); platform rule: toggles for boolean state, checkboxes (restyled) for selection; system-wide multi-select sweep (scroll + Select all/Clear all); customer detail gains Invoices (view-only + Facturen link) and Reports sub-tabs; seed data enriched; EW-list mark-invoiced action moves to Facturen (filters stay, pointer link added); ticket-detail right cards default-collapsed with Workflow open; zero-price proposal send stays permitted; demo data cleanup declined; E2E deferred until after Ramazan+father feedback — web-Claude code audit runs instead. → **Sprint #108** = this batch, one branch (`feat/owner-batch-2`), PR #108 held for owner review. **DONE — PR #108, squash-merged (aed15f7), deployed to crmtest.**

**Owner review round 3 (2026-07-20):** five feedback items on the deployed #108, logged verbatim-compact — (1) proposal composer: move the PDF live-preview to the bottom of the Pricing-proposal card so the composer regains full card width, and restore the pre-#108 LABELED Add-line/Cancel buttons (the ✓/✕ icons were too terse); (2) multi-select lists: prove the scroll cap actually bites, and sweep the whole frontend for any OTHER unbounded lists inside modals/popovers; (3) dashboard is too empty at the bottom — fill the band with an open-vs-invoiced hero split, a Facturatie per-building mini-table and a Laatste-tickets/extra-werk list, reusing already-loaded data; (4) customer Reports tab should show real per-customer report GRAPHS (revenue + tickets-over-time + status-distribution locked to the customer); (5) ticket-detail collapse should be per-ticket — an opened card must not stay open when you navigate to a different ticket, and the correction disclosure must reset per mount. → **Sprint #109** = audit fixes (P2-1, P2-2, P3-1, P3-3) + round-3 fixes + SA notifications (in-app v1; email parity deferred) + docs polish. Branch feat/sprint-109, PR #109 held for owner review. **DONE — PR #109, squash-merged (5b37e6f), deployed to crmtest.**

**Owner review round 4 (2026-07-20):** three targeted polish fixes on the deployed #109 — (1) the right-column **Responsible managers** + **Scheduling** cards still defaulted open; both now default COLLAPSED (Workflow stays the only always-open card; per-ticket remount already in place from #109 Part I). (2) The Extra Work **live-preview** looked short: the PDF embed was not filling the pane. The pane now has a real height (80vh, min 560px, max 85vh) and the embed flex-fills it — MEASURED embed height 420px → 747px on a 1000px-tall viewport (→ 1067px at 1400px), showing the Osius logo through the first line-item rows with the rest scrollable. (3) The **building-list cap** (#109 Part F, 260/320px capped scroll) is re-confirmed and the Osius demo now seeds **18 buildings** (3 core + 15 "Bijkantoor NN Amsterdam", additive, no migration) all linked to the B Amsterdam customer, so the contact/permissions pickers **visibly overflow** — MEASURED 18 rows, clientHeight 258 ≤ 260 cap, scrollHeight 484 → scrolls. → **Sprint #110** = these three fixes. Branch feat/sprint-110, ~~PR #110 held for owner review~~ **DONE — PR #110, squash-merged (cd86e3a), deployed to crmtest, demo buildings seeded.**

**Owner review round 5 (2026-07-20):** "My Work" made role-adaptive and hidden for SA + CA (owner decision, locked). → **Sprint #111** = My Work role-adaptive: **STAFF** keeps the slot agenda unchanged; **BUILDING_MANAGER** gets a new assigned-tickets view via the new opt-in ticket-list `?my_managed` filter (union of `Ticket.assigned_to` + `TicketManagerAssignment`); **hidden for SUPER_ADMIN + COMPANY_ADMIN** (nav gate `canAccessAgenda` = STAFF||BM in `permissions.ts`; backend `TicketFilter.filter_my_managed` on top of `scope_tickets_for`). Added `docs/product/role_visibility_matrix.md` (role → left-nav visibility, every cell sourced from the FE gate + the backend permission/scoping fn). Branch feat/sprint-111, PR #111 held for owner review.

**Open discussion items (pending owner direction, not built in #110):**
- **SUPER_ADMIN "My Work" page content** — what an SA should see on a "my work" surface (SA creates little of their own; the provider-management "Mijn werk" concept is admin-scoped). Awaiting the owner's definition before building.
- **Dashboard "Mijn werk" section purpose** — clarify whether the chip row is "items I created" (current) or a broader "what needs me" queue, and whether it should differ per role. Awaiting owner direction.

### Documented-intentional behaviors (audit 2026-07-20)
These surfaced during the #109 audit and are intentional — recorded so a future audit does not re-flag them:
- **(I-1)** The ticket-level `/tickets/<id>/unable-to-complete/` endpoint is superseded by the slot-completion flow (AgendaPage → `send_slot_unable_to_complete_email`) and is intentionally left unsurfaced.
- **(I-2)** The legacy `ExtraWorkPricingLineItem` route is alive by design (older EWs keep it) and has no `actual_hours` column by design — it never gates the completion transition.
- **(I-3)** The SA notification feed is empty by design (the in-app fan-out deliberately excludes unsubscribed SUPER_ADMIN; only directed messages reach them) — now opt-in per company via the #109 SA subscriptions.
- **(I-4)** `clear-invoiced` clears by the EW's CURRENT billing month (COALESCE(invoice_date, spawned-ticket completion)), not the month it was originally marked in.
- **(I-5)** The customer logo GET is open to any authenticated user by design; writes are gated (a customer's logo only by that customer's CUSTOMER_COMPANY_ADMIN; SA may change any).
- **(I-6)** The user profile-photo GET is open by design; writes are self/SA only.

*(Note: proposal-10's `f — 1.00 x OTHER @ 0.00` line was confirmed junk demo data, not a bug.)*

**Meeting notes (2026-06-23, for the audit sprint):** Department/event are **category-like** fields; names must stay editable/customer-flexible ("herkese uymuyor") — refines backlog #6. Ramazan will do a **full side-by-side review** vs their current system and deliver the complete gap list at once (the agreed batch — Göktuğ implements it in one pass). He validated the pricing work (bulk raise, customer-specific prices, **price history preserved — old EWs keep their old prices**). The credentials/permissions area of their *current* tool is their worst pain point; he'll study ours as the reference.

---

## Standing milestones
- [ ] **Production deployment** (the dev/test link already covers the "live link" need; this is the real thing): VPS, TLS, real SMTP, non-root containers, `ALLOWED_HOSTS` fix for the Docker internal healthcheck (broken with `DEBUG=False`), Postgres backups.
- [ ] **CD** via GitHub Actions (CI already runs as required PR checks: backend Django/Postgres/Redis + frontend lint/tsc/build).
- [ ] **Sentry** DSNs (integration is merge-safe / empty-DSN no-op; needs Göktuğ to create the account + provide DSNs).
- [x] **Backend follow-up ✅ DONE (PR #102):** nested `sub_tasks` redacted for all CUSTOMER_* roles in `TicketDetailSerializer` (empty list; staff identity + internal notes no longer leak).

## Deferred
- [ ] **Department section** — folded into the **Fixing & Auditing Sprint** below (design + build in person with Ramazan + father there).
- [ ] **CCA legacy-row retirement + SoT sign-off** — retire the legacy per-building `CUSTOMER_COMPANY_ADMIN` grant path, rework the B5 grant gate to bind the `is_company_admin` flag (split-brain), and document the `user_can` CustomerCompanyPolicy-bypass decision in the product SoT (owner sign-off). → Fixing & Auditing sprint.
- [ ] **SA notification EMAIL parity** (#109 Part D shipped in-app only) — decide whether a subscribed SUPER_ADMIN also receives the provider-management EMAILS (TICKET_CREATED / TICKET_STATUS_CHANGED / TICKET_SLOT_UNABLE). Deferred; the in-app v1 email path is deliberately untouched.
- [ ] **Customer-scoped chart follow-ups** (#109 Part H) — the customer Reports charts reuse the existing dimension endpoints with the new `customer` param; a richer per-customer revenue breakdown (per-building split in the chart itself, or a customer axis on more dimensions) is a follow-up if the owner wants it.

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

## Shipped summary #100–#109 (from `git log --oneline master` merges)
One line per PR — number · theme · key surfaces.
- **#100** — Quick-wins RF-3/4/5 · top-level Tickets page, tucked ticket audit-timeline, attachment type + in-app preview.
- **#101** — PDF & Preview sprint · proposal-PDF quality (Dutch), split-screen live proposal preview, attachment thumbnails.
- **#102** — Small independents · `sub_tasks` CUSTOMER_USER redaction (privacy) + RF-2 unified Add-price flow with Other/Custom (`custom_unit_label` on CustomerCustomPrice).
- **#103** — RF-1 message inbox · WhatsApp-style aggregated inbox over ticket + Extra Work threads, per-recipient read cursors, logo/photo avatars, RF-11 EW Messages card restyle.
- **#104** — IA & Effectiveness · disjoint Notificaties/Berichten (message events out of the feed by default), customer-detail content tabs 4→2 with filter chips, inbox unread-toggle + mark-all-read.
- **#105** — EW comfort + branded PDFs · RF-14 collapsible/scrollable EW-detail cards + preview toggle, RF-15 Osius-logo header + embedded DejaVu font with real € on both PDF families.
- **#106** — Combined queue · RF-8 permission module bundles, RF-9 calm assignment area, RF-13 Facturen invoices v1 (customer+building filters), RF-16 dashboard = attention cards (full lists on Tickets/Extra Work only).
- **#107** — Detail/dashboard polish · RF-17 collapsible/wider ticket-detail right column, RF-18 dashboard info widgets, RF-19 stable proposal add-line grid.
- **#108** — Owner-batch-2 · Option-A dashboard rebuild, single-row proposal composer + `custom_unit_label` on ProposalLine, Bulk adjust (raise+lower), toggle/checkbox + multi-select sweep, customer Invoices+Reports sub-tabs, EW-list mark-invoiced→Facturen pointer, collapsed ticket-detail cards, seed enrichment.
- **#109** — Audit fixes + round-3 + SA notifications · P2-1 EW billing audit, P2-2 ticket customer-approval `user_can` gate, P3-1 billing localtime, P3-3 SA CONVERTED terminal guard; composer preview-to-bottom + labeled buttons, multi-select scroll proof + unbounded-list sweep, dashboard density band, customer-scoped report charts (revenue/over-time/status), per-ticket collapse; SA per-company notification subscriptions (in-app) + view-as feed; docs polish.
