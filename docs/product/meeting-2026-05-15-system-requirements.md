# Meeting 2026-05-15 — System Requirements

Authoritative product behaviour from the stakeholder meeting on **2026-05-15**.

This document sits at the same authority level as
[`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md).
The RBAC matrix is the **security floor**; this doc is the **product floor**.
A backlog item that contradicts either is wrong by default — open a backlog
row to reconcile, do not implement the conflicting version.

When a sprint design references one of these rules, cite the section number
below (e.g. "per §4, customers compose a request as a cart of line items").

---

## §1. Contacts vs Users — two distinct entities

Contacts and Users are different domain objects. Conflating them is the
single most common modelling mistake; the design must prevent it.

### Contact
- A person listed only for **communication purposes** (telephone book entry).
- Has fields like: `full_name`, `email`, `phone`, `role_label` (free text,
  e.g. "Facility manager", "Janitor lead"), `notes`, plus the FK back to the
  Customer / Building they're attached to.
- **No login.** No password, no JWT, no `User.role`, no permission overrides,
  no scope rows.
- Can be created, edited, and deleted independently of any User. Deletion of
  a Contact never affects a User.

### User
- An authenticated principal. Has a `UserRole` (the five-value global enum
  from the RBAC matrix), zero or more memberships
  (`CompanyUserMembership`, `CustomerUserMembership`,
  `BuildingManagerAssignment`, `BuildingStaffVisibility`,
  `TicketStaffAssignment`), and per-building access rows
  (`CustomerUserBuildingAccess`) carrying the sub-role and permission
  overrides.
- Login is gated by the existing JWT auth + lockout pipeline.

### Promotion rule
A Contact does **not** become a User by "adding a password to a Contact row".
Promotion is an explicit operator action that creates a User row + the
appropriate memberships, optionally linked back to the Contact via a foreign
key for record-keeping. This is a separate sprint; not in scope until then.

---

## §2. Modular per-location permissions

A single User MAY have different effective permissions per building inside
the same Customer.

Examples:
- **Tom** has `access_role = CUSTOMER_USER` for Building A (basic create
  ticket / approve own) and `access_role = CUSTOMER_LOCATION_MANAGER` for
  Building B (location-wide view + approve).
- **Sara** is a basic `CUSTOMER_USER` in Building C but has a granular
  per-key override: `customer.extra_work.approve_own = True` on her
  `CustomerUserBuildingAccess.permission_overrides`, so she can approve
  pricing for Building C without being promoted to LOCATION_MANAGER.

### How this maps to the existing model

- Per-access sub-role: `CustomerUserBuildingAccess.access_role`
  (Sprint 23A; `CUSTOMER_USER` / `CUSTOMER_LOCATION_MANAGER` /
  `CUSTOMER_COMPANY_ADMIN`).
- Per-key override: `CustomerUserBuildingAccess.permission_overrides` JSON
  (Sprint 27C write endpoint, Sprint 27E UI).
- Resolver order (Sprint 27D, also documented in the matrix §2):
  1. `is_active = False` → all keys False.
  2. Key in `permission_overrides` → that value wins.
  3. `CustomerCompanyPolicy` field is False → False (DENY layer; cannot
     grant).
  4. Otherwise → per-`access_role` default.

### Hard rule
Granting a single right MUST NOT require promoting the user's global
`User.role`. The provider-side admin UI on `CustomerFormPage` (Sprint 27E)
is the operator surface for this; do not introduce parallel surfaces that
edit `User.role` to flip a per-building bit.

---

## §3. Frontend — view-first / closed-door design

The UI follows a **closed-door** discipline: pages are read-only by default.
Mutations happen only through explicit "Edit" / "Add" actions that open a
modal or navigate to a separate page.

### Navigation rules

1. **Left sidebar is the primary navigation anchor.** Top-level entries:
   Dashboard, Tickets, Extra Work, Customers (Relations), Reports,
   Settings.
2. **Hierarchical customer navigation.** Clicking "Customers" in the
   sidebar opens the list of authorized customers. Selecting one
   **switches the sidebar into a customer-scoped submenu**:
   - Buildings
   - Users (with access overrides editor)
   - Permissions (company-policy panel)
   - Extra Work
   - Contacts (telephone book)
   - Settings
   - **Back** (returns the sidebar to the top-level)
3. The submenu state is **URL-encoded** so deep links work and browser-back
   behaves predictably.
4. **No data dumps.** A page must never render 30 buildings, 16 permission
   keys, or N contacts as one long list. Hard rule: > ~10 items requires
   pagination, search, tabs, or a modal.
5. **Modals / separate pages for "Add" and "Edit" actions.** Never
   inline-mutate from a list row.

### Reference implementations (already shipped)

- **View-first**: `frontend/src/pages/admin/CustomerFormPage.tsx` — per-access
  pills are read-only until "Edit permissions" opens an inline section
  (Sprint 27E G-F1).
- **Modal-driven edit**: the ticket workflow override modal on
  `TicketDetailPage.tsx` (Sprint 27F-F1).
- **Two-press confirmation**: the same Ticket override modal, mirroring the
  Extra Work pattern at `ExtraWorkDetailPage.tsx:250-273`.

---

## §4. Extra Work — shopping-cart flow

Customers compose an Extra Work request as a **cart of line items**, similar
to an e-commerce checkout. Each line is a selected service from the
catalog, with its own quantity, requested date, and per-line notes.

### Flow

1. Customer opens "Add extra work" from the customer-scoped sidebar
   submenu (§3).
2. Customer browses **service categories** (Cleaning, Maintenance,
   Inspection, …) and selects services to add to the cart.
3. Each cart line carries:
   - `service` (FK to the Service catalog row)
   - `quantity` (decimal; depends on `unit_type`, see §5)
   - `requested_date` (per line; the cart can mix dates)
   - `customer_note` (free text, customer-facing)
4. Customer submits the cart → one parent `ExtraWorkRequest` is created
   with N `ExtraWorkRequestItem` line items.
5. **Branching** on submission (§4.1).

### §4.1. Pre-agreed price path → instant ticket(s)

If every line item resolves to a pre-agreed price (global default OR
customer-specific contract override, §5), the proposal phase is **skipped**.
The system automatically creates execution `Ticket` rows (one per
approved line item, or one ticket with a billing breakdown — exact mapping
defined by the sprint that ships this). Customer sees the request go
straight to "scheduled / in progress".

### §4.2. Custom / unknown price path → proposal

If any line item lacks an agreed price OR is flagged custom, the whole
request enters the **proposal phase**: it's queued for a provider-side
manager / admin to build a proposal (§6) and send it back to the customer
for approval.

### Hard rule
The branching decision is per-request (the entire cart), not per-line: a
single line without an agreed price routes the whole cart to the proposal
flow. This keeps the UX predictable for both the customer (one approval
moment for the whole cart) and the operator (one proposal to build).

---

## §5. Pricing — global default + customer / contract overrides

### Pricing model

- **Global default price.** Every catalog service has a default price.
- **Customer-specific contract price.** A customer can have a contract
  row that overrides the global default for a given service. Same
  service can have different prices for different customers, even in
  the same building.

### Unit types

Catalog services declare a `unit_type` and the corresponding price field
is interpreted accordingly:

| Unit type | Price meaning |
|---|---|
| `HOURLY` | Price per hour of work |
| `PER_SQM` | Price per square meter |
| `FIXED` | Single fixed price for the whole service |
| `PER_ITEM` | Price per item delivered / consumed |

The `quantity` on a cart line is interpreted against the unit type
(e.g. hours for HOURLY, m² for PER_SQM, item count for PER_ITEM, always
1 for FIXED — the FIXED branch may make `quantity` read-only in the UI).

### VAT

- Default VAT is **21%** (Dutch standard rate).
- VAT is **editable per line** on the proposal (a service might fall under
  the reduced 9% rate, or be exported). The default is applied at
  cart-add time; the proposal builder lets the operator change it.

### Resolution order

For a given (service, customer) pair:
1. Customer-specific contract price (if exists and active).
2. Global default price.
3. None → flag the line as "custom / no agreed price" → route to
   proposal phase (§4.2).

---

## §6. Proposal builder

When a request enters the proposal phase (§4.2), an operator builds a
proposal by listing one or more lines. Each line:

| Field | Type | Customer-visible? |
|---|---|---|
| `service` | FK to Service catalog (or free-text label for ad-hoc) | yes |
| `quantity` | Decimal | yes |
| `unit_type` | `HOURLY` / `PER_SQM` / `FIXED` / `PER_ITEM` | yes |
| `unit_price` | Decimal | yes |
| `vat_pct` | Decimal (default 21.00, editable) | yes |
| `customer_explanation` | Text (the customer-facing description of why this line exists) | **yes** |
| `internal_note` | Text (internal cost breakdown, supplier note, margin reasoning) | **NO** — never serialized to a customer endpoint |

### Hard rule on the dual-note system
`internal_note` MUST never appear on any customer-facing endpoint or PDF
view. The customer-facing serializer (e.g.
`ExtraWorkProposalLineCustomerSerializer`) must omit the field; the
provider-facing serializer (`ExtraWorkProposalLineAdminSerializer`)
includes it. A test must assert this with a regression lock.

### Timeline events

Every proposal lifecycle event (created, submitted, customer viewed,
customer approved, customer rejected, admin override) emits a timeline
entry visible to provider-side users. Customer-side users see a filtered
subset (no internal notes, no override-reason free text — only that an
override happened).

### PDF export
PDF generation of the proposal is a planned deliverable
(see EXTRA-PDF-1 in the backlog). The PDF format must include all
customer-visible lines + the customer-visible explanation, and MUST
exclude internal notes. Engine: `fpdf2` is already in
`backend/requirements.txt` — reuse it.

---

## §7. Approval + admin override

### Customer side
The customer can **approve** or **reject** a proposal. Both actions are
state-machine transitions on the proposal entity; reject requires a
reason field (mirror the Ticket model's customer-rejection reason rule
from CHANGE-1 era).

### Provider-side admin override
A provider-side admin (SUPER_ADMIN / COMPANY_ADMIN, per matrix §3 H-5)
can override the customer decision (push approved → rejected, or
rejected → approved) **only with a mandatory `override_reason`**.

### Audit / timeline contract

The override fact is recorded in BOTH the operational state-history row
(`is_override=True` + `override_reason` columns on the proposal's status
history table — mirror the Sprint 27F-B1 shape that
`TicketStatusHistory` and `ExtraWorkStatusHistory` already use) AND on
the timeline (§6) with actor + timestamp.

The override fact is NOT additionally written to the generic `AuditLog`
table — the history row IS the audit trail (RBAC matrix H-11). The
generic AuditLog is reserved for **permission / role / scope** changes.

---

## §8. Accepted proposal → operational tickets

When a proposal is approved (customer-side OR admin override), the system
**automatically** spawns operational `Ticket` rows.

### Mapping

- Parent: the existing `ExtraWorkRequest`.
- Line items: `ExtraWorkRequestItem` (or `ExtraWorkProposalLine` once
  the proposal is approved — exact name is a sprint-design decision).
- For each **approved** line item, the system creates one execution
  `Ticket` anchored to the parent request, with:
  - `building`, `customer`, `company` from the parent request.
  - `title` derived from the line's service name + qty / unit.
  - `description` derived from the line's `customer_explanation`.
  - `priority` defaulting to NORMAL.
  - `status = OPEN`.

Rejected line items do NOT spawn tickets. The parent request retains the
full audit trail of which lines were approved / rejected / overridden.

### Hard rule
The ticket creation must run inside the same `transaction.atomic()` as the
proposal approval transition — partial state (proposal approved but no
ticket) is not acceptable.

---

## §9. Future architecture hooks — parked

The following are documented now so future schema and API design leaves
room for them, but they are **explicitly not in scope** until separately
scheduled.

### §9.1. Subscription / abonement billing
Some customers will move to a recurring subscription model
(weekly / monthly cleaning contracts). The proposal flow and the
service catalog must NOT bake in assumptions that every request is
one-shot. The current data model already allows N requests per customer,
so the placeholder is "leave room — don't ship feature code".

### §9.2. Bank-transaction matching
The system will eventually match bank transactions to proposals / tickets
to verify payment. Schema needs an `external_reference` / `paid_at` /
`paid_amount` slot, but the matching logic and integration are out of
scope.

Both are tracked in `docs/backlog/PRODUCT_BACKLOG.md` as FUTURE-*
placeholders so the backlog doesn't lose them.

---

## §10. How this doc interacts with other authoritative sources

| Authority | Scope |
|---|---|
| [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) | RBAC + role model + invariants. Security floor. |
| **This doc** | Product behaviour. Product floor. |
| [`CLAUDE.md`](../../CLAUDE.md) | How Claude Code works in this repo. Process floor. |
| [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md) | The live work queue. Items must cite a section of this doc or the RBAC matrix as their source. |

If a sprint design conflicts with this doc, the conflict goes to a
backlog row labelled "RECONCILE-…" and the sprint pauses until the
stakeholders are consulted.
