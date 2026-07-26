# Osius — Source of Truth · Addendum A (Ramazan Meeting 2)

**Date:** 2026-06-05. **Status:** authoritative; extends `Osius_Source_of_Truth_FINAL_2026-05-30.md`. Section references below point at the base SoT. Where this addendum and the base SoT differ, **this addendum wins** for the items it covers.

---

## A.0 What's been built since the base SoT
Sub-tasks (PR #84/#85), customer-pricing default-price surfacing (#86), and the recurring **calendar-tick** model (#87: additive `PlannedOccurrence.is_ad_hoc` + per-date `skip-date / add-date / clear-date / calendar` actions + the month-grid UI) are now in. The recurrence engine remains **rule-based** (frequency × weekday-set × `[start_date, end_date]`, MONTHLY anchored on day-of-month); the calendar layers hand-shaping on top (rule pre-fills ticks; untick = skip, tick off-rule = ad-hoc add). This satisfies SoT §8 "explicit picked dates" additively.

---

## A.1 Customer Company Admin is company-wide (revises §2.5) — **SHIPPED**
A **Customer Company Admin (CCA)** is admin across **all** of the customer's buildings — it is a **company-wide** status, not a per-building role. **This is implemented**, via the `CustomerUserMembership.is_company_admin` flag (migration `customers/0010`, which collapsed existing multi-building per-building CCA rows into the flag). The bullets below are the original ask, kept as the historical record of what was requested — do not read them as still-outstanding:
- Granting CCA applies to every building the customer is linked to (present and future); demotion removes it everywhere. — **done**: the flag is a single company-wide boolean on the membership, not a per-building row.
- The customer-permissions UI shows CCA as a **single company-wide status** and **drops the per-building rows** for that user (per-building sub-roles only apply to non-CCA users: Customer User / Customer Location Manager). — **done**.
- Migration: collapse existing multi-building CCA rows to the company-wide flag, back-compat. RBAC enforcement updated so a CCA passes any per-building admin check for their customer. — **done** (migration `customers/0010`; `accounts/effective_actions.compute_role_defaults` and `compute_scope` short-circuit on the flag before reading any per-building row).

### A.1.1 Amendment — company policy binds a CCA (2026-07-26, owner decision)

**The company-level `CustomerCompanyPolicy` DOES bind a company-wide CCA.** If a provider turns a policy family off for a customer, that customer's CCA cannot exercise the keys in that family either — a CCA is no longer an unconditional bypass of the company's own policy settings.

The four `CustomerCompanyPolicy` boolean fields and the six permission keys each governs (read fresh from `_POLICY_FAMILY_FIELD` in `backend/customers/permissions.py`, 2026-07-26 — verify against that dict before relying on this list in future work, it is the single source of truth):

| Policy field | Keys it governs |
|---|---|
| `customer_users_can_create_tickets` | `customer.ticket.create` |
| `customer_users_can_approve_ticket_completion` | `customer.ticket.approve_own`, `customer.ticket.approve_location` |
| `customer_users_can_create_extra_work` | `customer.extra_work.create` |
| `customer_users_can_approve_extra_work_pricing` | `customer.extra_work.approve_own`, `customer.extra_work.approve_location` |

**What stays UNCHANGED from the base A.1 guarantee:**
- A CCA is still admin across **all** of the customer's buildings and still needs **no** per-building access row.
- Per-building `is_active` and `permission_overrides` still do **NOT** apply to a company-wide CCA.
- **No per-building row can downgrade a CCA.** Company policy is the **ONLY** layer that can narrow a CCA.
- **Denial is ACTION-only, never scope**: a CCA still **SEES** every ticket and every Extra Work item of every customer they administer, regardless of the policy. Only the ability to create/approve within a denied family is affected.

**Where it is enforced:** `customers.permissions.user_can` — the CCA short-circuit in `user_can` consults the customer's `CustomerCompanyPolicy` (via the shared `_policy_denies_for_customer` core) before returning the CCA role default.

**Architectural rule for future work — CCA special-casing belongs in `user_can` and nowhere else.** Any caller that short-circuits on `is_company_admin` **before** reaching `user_can` silently bypasses the policy layer, because it never gives `user_can` the chance to deny. Two such bypasses existed — ticket creation (`tickets/serializers.py`) and the `SCOPE_CUSTOMER_LINKED` branch of `tickets/state_machine.py` — and were removed in Sprint 116 (see the sprint checklist). Scoping/visibility helpers (`company_admin_customer_ids`, `scope_tickets_for`, `scope_extra_work_for`, …) are the **deliberate exception**: they decide what a CCA **sees**, never what it may **do**, and are correctly untouched by this rule.

## A.2 People management — Contacts / Users / Employees (extends §3.1–§3.2)
Ramazan's strongest UX preference: **drill-in / modal edit** ("click into a row, edit, leave") — **not** accordion expand-in-place — because lists can hold 40+ people.
- The three concepts stay **distinct**: a **Contact/Employee can be a non-user** (information only, no login); a **customer Employee** record governs **building access**; a **User** record governs the **permissions** for those buildings.
- Combine the **management surface** (one page to manage a person's access + permissions + profile via drill-in), keeping the underlying data distinct. The existing `/admin/customers/:id/permissions` matrix may remain reachable.
- The backend already supports **granting a building a customer user isn't yet in** (`POST /api/customers/<id>/users/<user_id>/access/ {building_id}`, constrained to buildings linked to the customer); the FE must surface an **add-building** control.
- Phone numbers entered must be **valid** (already enforced).

## A.3 User & staff profile — structured credentials + custom properties + visibility (new; relates to §2.4, §3)
Every user profile (staff **and** customer users) carries richer detail under a **hybrid** model:

**A.3.1 Structured, compliance-aware credential fields** (typed, with built-in rules; documents are **PDF**):
- **Residence permit ("oturum kart"):** may be shown to a customer; when shown, **only the expiry date + the ID/permit number** — nothing else.
- **EU national ID:** **hard-blocked from every customer — visible to PA/SA only, never as a customer-visible PDF.** This is enforced in code, **not** a flippable toggle. (Compliance: exposure is a severe liability.)
- **Certificates / VCA:** PDF, may be shown to a customer.

**A.3.2 Generic custom properties** on all profiles: `property name / value / optional PDF attachment`, freely **add / remove** (e.g. age, salary, contract, notes).

**A.3.3 Visibility model:**
- Every property/document has a **visibility level**, defaulting to **most-restrictive (provider-only)**; salary-type data defaults to **PA/SA-only**.
- Visibility is selectable **per-customer and per-staff** (which customers see it; what each staff record exposes). The customer-side view honours visibility **and** the customer-company permission gate.
- The EU-national-ID block is **unconditional** regardless of any setting. Visibility changes on sensitive fields are **audited** (§9).

## A.4 Extra Work — monthly invoice run & billing month (extends §5.11, §7.2–§7.3)
Billing must key off a **billing month you set**, decoupled from the customer's final-approval date. Example: work completed **May 31**, customer final-approves **June 7** → it must bill in **May**, not June.
- A settable **billing month / invoice date** on completed extra work; an **"invoice run" per month** that gathers all extra work billable in that month.
- Extra Work gets a **monthly (time-range) filter + status filter** (e.g. completed / invoiced); per-month revenue/invoice export (PDF/CSV) — extends the EW-revenue report (§7.2).

## A.5 Navigation / IA (extends §5, §8)
**Recurring Work** and the **customer price-quote-request** flow live **under Extra Work** as sub-items — not as separate top-level entries, and the quote-request is **not** performed directly in the Extra Work create flow.

## A.6 Customer pricing — custom line, category edit, bulk raise (extends §5.6–§5.9)
- Allow adding a **custom/ad-hoc price line** for a service **not in the catalog** (free-text name + unit price + VAT), customer-specific.
- **Edit service categories**; a **bulk price-raise** helper (prices rise over time — raise many at once).

## A.7 Notification / message center (new; relates to §4.5 notes, §7.1)
Today, messages on tickets / extra-work / meldingen are buried and replies are missed. Required:
- A **notification feed**: events for a new message on a ticket / EW request / melding, and for a **personally-addressed** ("directed-to") message.
- A **top-right notification bell** + a **notifications page**; each item **deep-links** to its source. Personally-addressed messages surface to the addressee only. This is Ramazan's **highest-priority** request.

## A.8 Customer detail (provider) + dashboard "my X" (extends §7.1)
- On a customer's page (provider side), surface **that customer's** tickets / extra-work / **price-quote-requests** / meldingen as drill-in sub-tabs.
- The dashboard gains a **"my X"** aggregation (my tickets / meldingen / extra-work / requests).

## A.9 Melding (clarifies §1.4, §4.1)
**"Melding" is the Dutch-facing name for a customer-created waiting ticket** — it is **not** a separate concept. Ensure the customer can create a ticket/report and that it surfaces as a "melding" in the customer-facing UI.

## A.10 Department (deferred)
A **Department** section is planned but **deferred** — to be designed in person with Ramazan after the items above. Placeholder only; no scope locked yet.

---

## A.11 Operational notes
- Ramazan wants a **live login link** to use the system himself and find further gaps → the **production-deployment** milestone is pulling forward.
- Target cadence: the Meeting-2 items are wanted by **Monday**; Göktuğ + his father will work in person.
