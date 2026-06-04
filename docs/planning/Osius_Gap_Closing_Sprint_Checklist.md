# Osius — Gap-Closing Sprint Checklist

**Purpose.** This is the living plan to close every remaining gap between the system and the Ramazan transcript + Source of Truth, ending with a premium UI/UX polish. **CC ticks the boxes for a sprint as it completes it** (and stages this file with the commit), so we always know where we are and what's done.

**How to use.** Work sprints top-to-bottom. Each sprint is a separate CC prompt. After a sprint passes its gates + review and is pushed, CC checks its boxes here. Don't start a sprint before the prior one is reviewed/merged unless noted as independent.

---

## Background — what the system is

Osius / CleanOps is a multi-tenant cleaning-operations SaaS for cleaning providers (Osius is the first provider) and their customer companies. Django 5.2 + DRF + Postgres/Redis/Celery backend; React 19 + TS + Vite + i18next (Dutch default) frontend; Docker Compose. Roles: SUPER_ADMIN, COMPANY_ADMIN (Provider Admin/PA), BUILDING_MANAGER (BM), STAFF, CUSTOMER_USER; per-customer access roles CCA > CLM > CU; staff employment types INTERNAL_STAFF / ZZP / INHUUR. Tickets (operational), Extra Work (priced, becomes operational after pricing), a service catalog with per-customer agreed prices, recurring/planned jobs, multi-manager + multi-staff assignment, a system-wide audit log, and reports with CSV/PDF export.

**Conventions (apply to every sprint / CC prompt):**
- Backend is the business source of truth; **verify, don't assume**; never invent endpoints.
- **Never read or stage** `docs/transkript.txt` or its `:Zone.Identifier`. Stage commits by explicit path.
- nl + en i18n in lockstep (Dutch primary); every referenced i18n key must resolve (no raw keys on screen).
- ESLint baseline = **49** (47 errors, 2 warnings): add **no** new violations; **never** add a synchronous setState in an effect body.
- Backend-touching / migration / RBAC → open a PR (CI + Codex). Routine frontend-only → push the branch and STOP for the owner to fast-forward.
- Each prompt starts with a sync + a grep GUARD proving the right base, captures the lint baseline, and ends with an adversarial review. Screenshots via token-inject (the e2e login form is flaky).

---

## Current codebase state — what we have / what we don't

**Already built (verified in the repo — do NOT rebuild):**
- Contacts under a customer + **promote-to-user** (contact-anchored); customer **permissions matrix** (per-building access + tri-state inherit/allow/deny override modal); per-user building scoping.
- Staff **"My Work" agenda** (`/agenda`, `GET /tickets/my-slots/`).
- **Slot-level completion** note-or-photo enforcement (`TicketAttachment.staff_assignment` FK exists).
- **Ticket → Extra Work** convert; EW **instant-vs-proposal/quote** ordering + dangerous quote-bypass (ProposalBuilder, RouteBadge, direct-publish, company toggle).
- Reports + **CSV/PDF export** + EW revenue chart.
- Recurring engine (weekday-sets + AM/PM windows + per-occurrence billing, #77); system-wide audit + ticket-id timeline + severity (#78); multi-manager + SA company policy toggles (#79).
- **Reschedule backend**: `POST/DELETE /tickets/<id>/schedule/` (set/reschedule/clear) — provider-management only, additive.

**Genuine gaps (this checklist closes them):**
- Reschedule has **no frontend control** (backend exists).
- **Sub-tasks** do not exist (no model, no UI).
- **Bulk select-and-approve** of completions does not exist.
- **Contact-first enforcement** unverified (a non-contact path to a customer user with access may exist).
- Permission editor is a **separate page**, not the in-place popup Ramazan wants.
- A few backend endpoints may be **unsurfaced** (unable-to-complete, actual-hours, copy-from-default, occurrence skip/cancel) — verify.
- Recurring + recurrence **pricing UX** should be improved (calendar-tick).
- A final **premium UI/UX polish** is wanted.

---

## Sprints

### Sprint 0 — In-flight (track only)
- [ ] PR #79 Codex P2 fixes (paginate the responsible-manager list; key the section by ticket id) — pushed/merged.
- [ ] Customer-pricing **reference prefill** (dropdown shows the service's reference €; selecting prefills `unit_price`+VAT, editable; never clobbers a saved price) — pushed/merged.

### Sprint 1 — Reschedule (frontend-only)
Surface the existing `/tickets/<id>/schedule/` action as a **set / change / clear scheduled-date** control on the ticket detail, for **all ticket types**, provider-management gated (SA/CA/BM). Read the schedule contract from the backend; don't invent fields.
- [x] Reschedule/clear control on ticket detail, consuming the existing schedule action.
- [x] Gated to SA/CA/BM; STAFF/customer see the date read-only (no 403 surfaced).
- [x] Gates green (typecheck/build/eslint 49); at-risk e2e green; screenshots.

### Sprint 2 — Permission editor in-place from the contact
Re-host the permission editor (role + per-building access + the tri-state inherit/allow/deny override modal) so it **opens in place from the contact's user entry as a popup / expanding panel**, with groups **stacked vertically** (ticket → extra-work → toggles), compact. **Keep** the existing `/admin/customers/:id/permissions` page reachable (Ramazan: "can stay for now"). Reuse the existing `PermissionEditorModal` + access/override logic — this is placement/flow, not new permission logic.
- [ ] In-place popup/expand from the contact's user section (no forced navigation away).
- [ ] Vertical-stacked, compact groups; per-building scoping intact; tri-state overrides intact.
- [ ] Existing permissions page still reachable; gates + e2e green; screenshots.

### Sprint 3 — Contact-first enforcement
**Audit first**, then fix only the hole if present: a customer user **with access** must only be creatable **via a contact** (promote-from-contact). Make the **Invitations screen provider-staff-only**; customer-access invitations require a contact. Confirm no membership/invitation path bypasses this.
- [ ] Audit of all customer-user-with-access creation paths documented.
- [ ] Invitations screen restricted to provider staff; customer users only via contact-promote.
- [ ] Backend enforcement (if a bypass existed) + tests; gates/e2e green.

### Sprint 4 — Sub-tasks (backend)
A **SubTask** = a **named work unit** under a ticket, on **all tickets**, layered on the existing dated multi-slot assignment (don't rewrite it).
- [ ] `SubTask` model: FK to ticket, `title`, `ordering`, `status`, timestamps; carries the occurrence link when spawned from recurrence.
- [ ] Nullable `sub_task` FK on `TicketStaffAssignment` (slots with `null` = the ticket's default un-split work — back-compat).
- [ ] **Auto-complete rule:** default = a manager (SA/CA/BM) confirms ticket completion; **PA/SA can set a per-ticket `auto_complete_on_subtasks` flag** — when set, the ticket auto-completes once all its sub-tasks are done. (Sub-tasks are **not** priced separately; billing stays per-occurrence.)
- [ ] Completion roll-up: a sub-task is done when its assignments are done (note/photo already enforced per assignment); ticket completion per the rule above.
- [ ] Audit coverage for SubTask CRUD + the flag; tests; PR.

### Sprint 5 — Sub-tasks (frontend)
- [ ] Sub-task section on the ticket detail (all tickets): add named sub-tasks; under each, **time-windowed staff assignments** (reuse the slot picker) so one sub-task can be Ahmet 09:00 / Mehmet 12:00 / Ahmet 16:00; per-assignment completion state.
- [ ] **Layered** on the current multi-slot UI (sub-tasks optional); careful UI/UX so it's not cluttered.
- [ ] The `auto_complete_on_subtasks` toggle exposed to PA/SA; staff see/complete only their own assignments.
- [ ] Gates/e2e green; screenshots (manager splits + assigns; staff view).

### Sprint 6 — Recurring UI/UX (calendar-tick + pricing)
Redesign the recurring job workflow to **calendar-tick** as the primary input (hand-pick specific dates + AM/PM windows + per-date/window price), with an **optional weekday-rule generator** that pre-fills ticks you can edit/remove, and a **clearer pricing UX**. **Includes a backend recon/design step** — the current model is weekday-based; explicit picked-date support may need a small backend change (design it minimally, back-compat with #77).
- [ ] Backend recon + minimal design for explicit picked dates (if needed); migration back-compat with #77.
- [ ] Calendar-tick form (primary) + optional weekday-rule generator; clearer per-date/window pricing.
- [ ] Reschedule (Sprint 1) works naturally on a single ticked date; gates/e2e green; screenshots.

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
- [ ] A cohesive visual polish pass for a premium look (tokens, spacing, density, consistency), with extra attention to the recurring + sub-task surfaces. No behavior changes; gates/e2e green; before/after screenshots.

---

## Open assumptions to confirm before their sprint (veto any)
- **Sub-task auto-complete (Sprint 4):** default is manager-confirm; PA/SA can flip a per-ticket auto-complete-when-all-sub-tasks-done flag. (Your Q4, as I read it.)
- **Permission page (Sprint 2):** additive — keep the existing page reachable, add the in-place popup as the primary path.
- **Recurring (Sprint 6):** calendar-tick primary + optional weekday-rule generator; a small back-compat backend change for explicit dates is likely needed (I'll recon the recurrence engine at that sprint).
