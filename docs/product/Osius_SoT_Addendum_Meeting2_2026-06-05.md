# Osius — Source of Truth · Addendum A (Ramazan Meeting 2)

**Date:** 2026-06-05. **Status:** authoritative; extends `Osius_Source_of_Truth_FINAL_2026-05-30.md`. Section references below point at the base SoT. Where this addendum and the base SoT differ, **this addendum wins** for the items it covers.

---

## A.0 What's been built since the base SoT
Sub-tasks (PR #84/#85), customer-pricing default-price surfacing (#86), and the recurring **calendar-tick** model (#87: additive `PlannedOccurrence.is_ad_hoc` + per-date `skip-date / add-date / clear-date / calendar` actions + the month-grid UI) are now in. The recurrence engine remains **rule-based** (frequency × weekday-set × `[start_date, end_date]`, MONTHLY anchored on day-of-month); the calendar layers hand-shaping on top (rule pre-fills ticks; untick = skip, tick off-rule = ad-hoc add). This satisfies SoT §8 "explicit picked dates" additively.

---

## A.1 Customer Company Admin is company-wide (revises §2.5)
A **Customer Company Admin (CCA)** is admin across **all** of the customer's buildings — it is a **company-wide** status, not a per-building role. The current implementation enforces CCA **per-building** (`accounts/effective_actions.compute_role_defaults` reads the building-specific access row; the cross-row "strongest" is only the `building=None` aggregate). This must change to company-wide:
- Granting CCA applies to every building the customer is linked to (present and future); demotion removes it everywhere.
- The customer-permissions UI shows CCA as a **single company-wide status** and **drops the per-building rows** for that user (per-building sub-roles only apply to non-CCA users: Customer User / Customer Location Manager).
- Migration: collapse existing multi-building CCA rows to the company-wide flag, back-compat. RBAC enforcement updated so a CCA passes any per-building admin check for their customer.

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
