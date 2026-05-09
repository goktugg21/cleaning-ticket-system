# Customer / building / user scope (Sprint 14)

> **Audited commit:** Sprint 13 merge `db0f9e0` → Sprint 14 work.
> **Audience:** the operator and any reviewer reading the
> Sprint-14 PR.
>
> Sprint 14 changes the customer-side scope model so it matches
> the real-world Osius / B Amsterdam structure: one customer with
> many buildings, customer users that work for that customer, each
> customer user only allowed at a *subset* of the customer's
> buildings. Building managers (Osius-side) are unchanged.

This document explains the new model, the rules, and how legacy
data continues to work.

---

## The model in one paragraph

A **Customer** is a real-world organisation Osius services. A
customer is linked to **one or more Buildings** through the
`CustomerBuildingMembership` table. A **CustomerUserMembership**
attaches a customer-user to a customer; a
**CustomerUserBuildingAccess** further restricts that user to a
subset of the customer's buildings. **BuildingManagerAssignment**
(Osius-side) is unchanged — it stays the source of truth for who
on the Osius side manages which building.

A customer-user's visibility for tickets, dashboard, reports, and
forms is the **intersection** of customer membership AND
per-building access. A user with no access rows sees nothing.

---

## The B Amsterdam example

```
Customer:                  B Amsterdam
                           Maroastraat 3, 1060LG Amsterdam
                           (Customer.building = NULL — uses the
                            M:N table only)

CustomerBuildingMembership:
                           B Amsterdam ↔ B1 Amsterdam
                           B Amsterdam ↔ B2 Amsterdam
                           B Amsterdam ↔ B3 Amsterdam

CustomerUserMembership + CustomerUserBuildingAccess:
                           Tom    @ B Amsterdam → B1, B2, B3
                           Iris   @ B Amsterdam → B1, B2
                           Amanda @ B Amsterdam → B3

BuildingManagerAssignment (Osius-side, unchanged):
                           Gokhan → B1, B2, B3
                           Murat  → B1
                           İsa    → B2
```

A ticket at *B Amsterdam / B3 Amsterdam* is visible to:

- Tom (B3 in their access set).
- Amanda (B3 in their access set).
- Gokhan (B3 in their building-manager assignment).
- Any COMPANY_ADMIN of the parent company.
- SUPER_ADMIN.

It is **not** visible to:

- Iris — she is a customer-user of B Amsterdam but only has B1/B2
  access.
- Murat — assigned to B1 only.
- İsa — assigned to B2 only.

This matches the brief's example exactly.

---

## Rules

### Visibility

| Role | Sees ticket if |
|---|---|
| `SUPER_ADMIN` | always (and not soft-deleted) |
| `COMPANY_ADMIN` | `ticket.company` ∈ `{their company memberships}` |
| `BUILDING_MANAGER` | `ticket.building` ∈ `{their assignments}` |
| `CUSTOMER_USER` | `(ticket.customer, ticket.building)` ∈ `{their (membership.customer, access.building) pairs}` |

For all roles: also `ticket.deleted_at IS NULL` (Sprint 12).

The customer-user pair check is enforced by an `Exists` subquery
in `accounts/scoping.py::scope_tickets_for` so a multi-customer
user with different building access per customer cannot
accidentally see a ticket whose pair isn't theirs.

### Ticket creation

| Role | Can create a ticket at (customer, building) if |
|---|---|
| `SUPER_ADMIN` | the pair exists in `CustomerBuildingMembership` and both rows are active |
| `COMPANY_ADMIN` | above + caller is a member of the building's company |
| `BUILDING_MANAGER` | above + caller has `BuildingManagerAssignment` for the building |
| `CUSTOMER_USER` | above + caller has `CustomerUserMembership(customer)` AND `CustomerUserBuildingAccess(membership, building)` |

A ticket cannot be created for a `(customer, building)` pair that
is not linked, regardless of role. The legacy
`Customer.building == building` check has been replaced by a
`CustomerBuildingMembership` lookup, which is satisfied by both
new consolidated customers and the legacy single-building anchor
(thanks to the migration backfill).

### Customer admin operations

These are gated by `IsSuperAdminOrCompanyAdminForCompany` (the
same permission that gates the existing CustomerUserMembership
endpoints):

- `POST /api/customers/<id>/buildings/` — link a building to a
  customer. Building must belong to the same company; building
  must be active.
- `DELETE /api/customers/<id>/buildings/<building_id>/` —
  unlink. **Cascades:** any
  `CustomerUserBuildingAccess(membership.customer=this_customer,
  building=this_building)` rows are deleted in the same
  transaction. Existing tickets for the (customer, building) pair
  are not deleted; they remain in the audit log but become
  invisible to customer-users (no access) until the link is
  restored.
- `POST /api/customers/<id>/users/<user_id>/access/` — grant a
  customer-user access to a specific building under this
  customer. The building must already be linked to the customer
  (defence in depth: the admin UI gates this in the dropdown).
- `DELETE /api/customers/<id>/users/<user_id>/access/<building_id>/`
  — revoke.

All four actions are recorded in the audit log
([backend/audit/signals.py](../backend/audit/signals.py)) with
human-readable payloads (customer name, building name,
user email).

---

## Legacy fields

### `Customer.building` — DEPRECATED but kept

Pre-Sprint-14 every Customer row was anchored to a single
Building via this FK. Sprint 14 makes the field nullable and
treats it as deprecated:

- **Existing pilot data** keeps its `Customer.building` value.
- **The migration backfill** (`customers/migrations/0003_*`)
  creates one `CustomerBuildingMembership(customer,
  customer.building)` for every legacy row, so the new code
  paths read identical visibility from the new tables.
- **New consolidated customers** (B Amsterdam style) are created
  with `Customer.building = NULL` and use only the M:N table.

The field is not yet removed because:

1. It is referenced by the existing `unique_together(company,
   building, name)` constraint, which would need a separate
   schema migration to drop.
2. The frontend's existing customer-list view still shows the
   anchor building in a column, and the existing customer-form
   "Edit" path keeps it visible. Removing the field would
   require a coordinated UI change.
3. Any external integration that looked at `customer.building`
   would silently regress.

A future sprint can drop the field once we confirm no caller
relies on it. This sprint deliberately does not touch it beyond
making it nullable.

### `unique_together(company, building, name)` — kept

Postgres treats `NULL != NULL`, so a new consolidated customer
with `building=NULL, name='B Amsterdam'` does not conflict with
any other consolidated customer of the same name. The constraint
remains useful for the pre-Sprint-14 single-building rows.

---

## What did NOT change

- `BuildingManagerAssignment` and the building-manager
  permission flow are unchanged. The Osius side (Gokhan / Murat /
  İsa) keeps the existing model.
- `CustomerUserMembership` is unchanged in shape. It is still the
  parent of the new `CustomerUserBuildingAccess` rows.
- `Ticket` itself is unchanged. `(company, building, customer)`
  still appear as denormalised FKs on every ticket row.
- The audit log already covered `CustomerUserMembership` from
  Sprint 7. Sprint 14 adds coverage for the two new tables; the
  existing rows continue to be audited as before.
- Reports endpoints continue to deny customer-users (per
  `IsReportsConsumer`); the dashboard's `/api/tickets/stats/`
  endpoint respects the new pair scope automatically because it
  calls `scope_tickets_for`.
- The Sprint-12 ticket soft-delete continues to hide tickets from
  every role under the new scoping.

---

## How to seed the B Amsterdam demo locally

```bash
docker compose exec -T backend python manage.py seed_b_amsterdam_demo --with-ticket
```

The command is idempotent and safe to re-run. It refuses to run
under `DJANGO_DEBUG=False` unless explicitly overridden with
`--i-know-this-is-not-prod`, so a stray invocation on a
production host fails closed.

The customer-user accounts (Tom / Iris / Amanda) are created with
*unusable* passwords — no default credentials live in code.
Operator finishes onboarding via the password-reset flow. The
Osius manager accounts use a clearly-marked dev-only password
(`Sprint14Demo!`) printed at the end of the run; do not reuse it
on a production host.

---

## Known follow-ups (intentionally not in Sprint 14)

- Drop `Customer.building` and the legacy
  `unique_together(company, building, name)` once the rest of the
  app no longer reads them.
- A Building-form panel showing "Customers linked to this
  building" (currently the data is reachable via the API but the
  UI hint is omitted to keep this sprint focused).
- A bulk operation: "give every customer-user of this customer
  access to all linked buildings" (current UI requires selecting
  buildings one-by-one). Trivial to add later.
- An archive view that shows soft-deleted tickets to admins
  (Sprint 12 noted this; still not implemented).

---

## Cross-links

- [docs/system-behavior-audit.md](system-behavior-audit.md) — the
  contract that this sprint widens for the customer-user role.
- [docs/test-reliability-audit.md](test-reliability-audit.md) —
  test coverage matrix; Sprint 14 adds 16 new test cases under
  `customers/tests/test_customer_building_user_scope.py`.
- [docs/ticket-workflow-decision-audit.md](ticket-workflow-decision-audit.md)
  — Sprint 13's audit of the workflow ambiguity. Sprint 14
  *does not* touch workflow_type or approval rules.
- [docs/pilot-launch-checklist.md](pilot-launch-checklist.md) —
  operator runbook.
