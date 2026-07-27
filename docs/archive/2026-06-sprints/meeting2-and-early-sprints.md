> **ARCHIVED — historical.** Describes the system as of 2026-06-23. Not
> maintained; do not rely on it as current truth. Live docs: `docs/README.md`.
> Moved out of `docs/planning/sprint-checklist.md` in Sprint 122.1 (the
> Now/Next/Shipped restructure) — every item here was already shipped and
> superseded by later sprints; nothing in this file was still open.

# Early gap-closing sprints — Sprint 0–9 + Ramazan Meeting 2 (2026-06-05)

**Completed in this gap-closing effort (do NOT rebuild):**
- **Sprint 0** — PR #79 Codex P2 fixes (paginate responsible-managers; key by ticket id) ✅ merged; customer-pricing reference prefill ✅ (shipped as the #86 line below).
- **Sprint 1** — Reschedule frontend control on ticket detail (consumes `/tickets/<id>/schedule/`; SA/CA/BM) ✅.
- **Sprint 2** — Permission editor in-place from the contact (popup/expand; existing page still reachable) ✅.
- **Sprint 3** — Contact-first enforcement audited + invitations restricted to provider staff ✅.
- **Sprint 4** — Sub-tasks **backend** (PR #84): `SubTask` model, nullable `TicketStaffAssignment.sub_task` FK, PA/SA `auto_complete_on_subtasks` flag + roll-up, audit ✅ merged.
- **Sprint 5** — Sub-tasks **frontend** (PR #85): grouped staff slots, sub-task CRUD, PA/SA auto-complete toggle, PII-safe customer view ✅ merged.
- **Customer pricing — surface the service default price** (PR #86): dialog prefills unit price + VAT from the service default; default-price column (incl. inactive services); dropdown shows defaults ✅ merged.
- **Sprint 6** — Recurring **calendar-tick** (PR #87): additive `PlannedOccurrence.is_ad_hoc` (migration 0004) + four idempotent per-date `RecurringJobViewSet` actions (skip-date / add-date / clear-date / calendar) + the month-grid calendar UI + customer/building dropdown swap + per-window pricing clarity. Back-compat with #77.
- **M1 — Notification & message center** (PR #90): in-app notifications feed + recipient-scoped REST + NotificationBell + /notifications page; 5-channel ticket message visibility + RESTRICTED directed messages through the single `filter_messages_visible_to` chokepoint; 3-channel Extra Work thread; EW lifecycle + message notifications ✅ merged.

**Standing infra not yet done (as of this sprint):** production deployment; CD (CI exists as PR checks); Sentry DSNs. (Superseded — see the live `## NEXT` section in `docs/planning/sprint-checklist.md`.)

---

## Near-term priority — Ramazan Meeting 2 (2026-06-05) + carried-over

> The **Monday** deadline no longer applies. A **dev/test live link** (`crmtest.osius.nl`) already exists and Ramazan has access, so the "live link" need is met — real **production deployment** remains its own standing milestone (no longer pulled forward for that reason). The **Department section** and a full **requirements + codebase audit** are folded into the **Fixing & Auditing Sprint**.

### CP — Customer-permissions page (carried over) — do first, one PR (same page)
Backend already supports granting a building a customer user isn't in (`POST /api/customers/<id>/users/<user_id>/access/ {building_id}`, gated only by the Sprint-14 customer↔building link). The FE has `addCustomerUserAccess` wired but the matrix view doesn't surface the control.
- [x] **Add-building control** in the customer-permissions matrix (pick an un-granted building linked to the customer + role → POST). FE-only. **DONE** (branch `feat/cca-company-wide-and-people-consolidation`): surfaced in the People drill-in modal via the reused `ContactPermissionsPanel` (building picker + grantable-role select from `allowed_target_customer_access_roles`, hidden for a company-admin user).
- [x] **Option A — `CUSTOMER_COMPANY_ADMIN` company-wide.** Make CCA grant admin across **all** the customer's buildings from one setting; collapse the per-building rows into a single company-wide status; demote = remove that status. **DONE**: additive `CustomerUserMembership.is_company_admin` flag (migration `0010`, forward-only collapse of existing per-building CCA rows); `company_admin_customer_ids` unioned into scoping (tickets/EW/buildings) + ticket-scope/transition + EW catalog/pricing; `compute_role_defaults`/`compute_scope`/`user_can` short-circuit so no per-building row can downgrade a CCA; dedicated POST/DELETE `/users/<id>/company-admin/` endpoint (gated by `can_manage_customer_company_admins`, audited via a dedicated membership UPDATE signal). The legacy per-building CCA grant path was later fully retired, and the `user_can` CustomerCompanyPolicy-bypass question was resolved in Sprint 116 — see [`sot-addendum-a-meeting2.md`](../../product/sot-addendum-a-meeting2.md) §A.1.1.
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
- Shipped on branch `feat/m4-billing-month` (12 commits); deployed + verified on the dev/test box. (Superseded by the invoicing subsystem's per-month generation — see [`sot-addendum-b-invoicing.md`](../../product/sot-addendum-b-invoicing.md).)

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
- [x] A cohesive visual polish pass for a premium look (tokens, spacing, density, consistency), with extra attention to the recurring + sub-task + new profile/notification surfaces. **No behavior changes**; gates/e2e green; before/after screenshots. Feature-level layout asks (e.g. enlarging the right-side responsible-manager / assignment cards) were deferred to the Fixing & Auditing sprint — see the RF/backlog log kept live in `docs/planning/sprint-checklist.md`.

## Roadmap — phase order (as agreed 2026-06-23 after the Ramazan mini-meeting)
1. ✅ **Sprint 9 — light UI/UX polish** → PR #99, deployed.
2. **Quick-wins sprint** (from received feedback that further feedback can't invalidate) → **PR #100**, then deploy: **RF-3** Tickets top-level page · **RF-4** tuck the ticket audit timeline away · **RF-5** attachment type + in-app preview (recon the backend serving path).
3. **PDF & Preview sprint** → **PR #101**, then deploy: **RF-10** proposal-PDF quality (Dutch-only) · **RF-6** split-screen live proposal preview · **RF-12** attachment thumbnails.
4. **Continue-without-feedback work (agreed 2026-06-24):** **PR #102** — `sub_tasks` CUSTOMER_USER redaction (privacy) + **RF-2** unified Add-price flow with "Other/Custom" (adds an additive free-text `custom_unit_label` to CustomerCustomPrice). **PR #103** — **RF-1** WhatsApp-style message inbox (per-recipient read state, aggregation endpoint, logo avatars) with **RF-11** (EW Messages card restyle) riding along. **PR #104** — **IA & Effectiveness** consolidation: disjoint Notificaties/Berichten (message events out of the feed by default), customer-detail content tabs 4→2 with filter chips, inbox unread-toggle + mark-all-read, clarity pass (subtitles, SA empty-state, terminology sweep). All three shipped and deployed to crmtest.
5. **Post-#104 queue (agreed with Göktuğ, 2026-06-25; queue collapsed 2026-06-26):** **PR #105** (EW-detail comfort + branded PDFs), **PR #106** (combined queue: permission bundles, calm assignment area, invoices v1, dashboard attention cards), **PR #107** (collapsible ticket-detail column, dashboard widgets, stable proposal grid), **PR #108** (owner-review round-2 batch: Option-A dashboard, single-row composer, Bulk adjust, toggle/checkbox sweep, customer Invoices+Reports sub-tabs, seed enrichment). All four shipped and deployed to crmtest.
6. **Feedback completion** — Ramazan's full side-by-side gap list; father's invoice-integration answers; RF-7 pinpointed. (Still gating later work — see the live `## NEXT` section.)
7. **Fixing & Auditing Sprint** — the full batch + Department + RF-7 + codebase audit + reconcile the checklist. (RF-8 and RF-9 pulled forward into the #105–#109 queue.)
8. **E2E testing sprint**, then **Frontend testing sprint** — against the settled, post-feedback system.
9. **Production hardening** (TLS · real SMTP · non-root containers · Postgres backups) → **CD** → **Sentry DSNs**. (The `ALLOWED_HOSTS`-under-`DEBUG=False` healthcheck problem is already solved: `docker-compose.prod.yml` uses a TCP socket probe for the backend — see `backend/config/security.py`'s host validator.)

**Ordering decision (testing vs Fixing & Auditing), recorded 2026-06-23:** testing runs AFTER Fixing & Auditing. The missing coverage is E2E + frontend (the UI layer); the backend already has a CI test suite protecting the audit's backend changes. The Fixing & Auditing sprint mostly reshapes the UI (new dropdowns, invoice page/PDF, attachment previews, layout/density), so E2E/frontend tests written first would be invalidated by those changes — tests deliver durable value when they lock in final behavior. *Caveat at the time:* if the feedback returned small/cosmetic, testing-first would become reasonable instead.
