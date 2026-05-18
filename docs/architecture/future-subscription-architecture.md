# Future architecture — subscription / abonement billing

**Status:** PARKED. Schema shape described here so the proposal /
service-catalog / pricing data model leaves room for it. No feature
code ships in Sprint 28.

**Sources:**

- [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §9.1.
- Backlog row `FUTURE-SUBSCRIPTION-1` in
  [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md).

**Reviewed today (Sprint 28 Batch 14 closeout):** the Sprint 28 Service
catalog (`backend/extra_work/models.py::Service`) + per-customer pricing
(`CustomerPricing`) + cart shape (`ExtraWorkRequest` + N
`ExtraWorkRequestItem`) do **not** bake in "one-shot only" assumptions.
A subscription aggregate can sit alongside `ExtraWorkRequest` without
touching it.

---

## 1. What subscription means here

Some customers will move from ad-hoc "request → proposal → ticket" to a
**recurring** model: weekly / monthly / quarterly cleaning contracts
that auto-generate operational work and the corresponding invoice slot
on a schedule, without a fresh request each time.

The product floor (spec §9.1) is:

- Subscriptions are a **separate aggregate** alongside ad-hoc Extra
  Work. They never replace the request → proposal → ticket flow for
  one-off jobs.
- The catalog (`Service`) and pricing (`CustomerPricing`,
  `ExtraWorkPricingLineItem`) models must NOT carry "this is always
  one-shot" assumptions. (Reviewed; they don't.)
- Per-customer override pricing already supported via
  `CustomerPricing`. Subscriptions reuse it.

---

## 2. Schema shape (placeholder, NOT shipped)

### 2.1. `SubscriptionPlan`

The customer-side contract. One row per customer + service + building
triple, optionally per company.

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `customer` | FK → `customers.Customer` | Scope anchor for H-2. |
| `building` | FK → `buildings.Building` (nullable) | Some plans cover all customer buildings; some are building-specific. |
| `service` | FK → `extra_work.Service` (PROTECT) | The catalog row that defines what work is performed. |
| `cadence` | TextChoices enum | `WEEKLY`, `BIWEEKLY`, `MONTHLY`, `QUARTERLY`, `YEARLY`. |
| `cadence_day` | small int (nullable) | e.g. day of week 0–6 for WEEKLY, day of month 1–31 for MONTHLY. |
| `unit_type` | reuse `ExtraWorkPricingUnitType` | hourly / per_m2 / fixed_price / per_item — matches Service catalog. |
| `unit_price` | Decimal | Per-subscription override; falls back to `CustomerPricing` then global default per the spec §5 rule. |
| `vat_pct` | Decimal | Default 21.00, editable per plan. |
| `active_from` | Date | When the plan starts generating executions. |
| `active_to` | Date (nullable) | NULL = open-ended. |
| `is_active` | bool | Soft-off for pausing without losing history. |
| `auto_approve_customer` | bool | Spec §8 says pre-agreed contract lines skip proposal; for subscriptions, same posture — `True` means "skip proposal approval; spawn ticket directly when execution fires". |
| `created_by` | FK → `accounts.User` | Audit. |
| `created_at` / `updated_at` | DateTime | |

**Constraints:**
- `UniqueConstraint(customer, building, service, active_from)` so a
  plan can be reactivated (new row with new `active_from`) rather than
  mutated.

**Audit:**
- Register on `audit/signals.py` with full CRUD tracking. The plan
  shape is a contract — every change is audit-worthy. Mirror
  `CustomerPricing` registration.

### 2.2. `SubscriptionExecution`

The concrete materialisation. One row per scheduled run inside the
plan's active window.

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `subscription_plan` | FK → `SubscriptionPlan` (CASCADE) | |
| `period_start` | Date | Start of the period this execution covers. |
| `period_end` | Date | Inclusive end. |
| `quantity` | Decimal | Resolved at execution time from plan + unit_type. |
| `unit_price` | Decimal | Denormalised from plan at execution time. |
| `vat_pct` | Decimal | Denormalised. |
| `subtotal_amount` / `vat_amount` / `total_amount` | Decimal | Stored. |
| `status` | TextChoices enum | `PENDING`, `TICKET_SPAWNED`, `COMPLETED`, `INVOICED`, `PAID`, `CANCELLED`. |
| `generated_ticket` | FK → `tickets.Ticket` (SET_NULL, nullable) | Same pattern as `Ticket.proposal_line` (Sprint 28 Batch 8). NULL until the scheduler spawns the ticket. |
| `executed_at` | DateTime (nullable) | When the scheduler actually fired. |
| `created_at` / `updated_at` | DateTime | |

**Constraints:**
- `UniqueConstraint(subscription_plan, period_start, period_end)` so a
  scheduler restart can't double-spawn.

**Audit:**
- `_*_TRACKED_FIELDS` should include `status` + `generated_ticket`. The
  status timeline is the bookkeeping trail.

---

## 3. API surface placeholder

Mirror the Extra Work / Proposal pattern. No code ships in Sprint 28.

- `GET /api/subscriptions/` — provider-side list. Scoped via the same
  `scope_customers_for(user)` rule used elsewhere.
- `POST /api/subscriptions/` — provider-side create (SUPER_ADMIN /
  COMPANY_ADMIN only, via the same `IsSuperAdminOrCompanyAdminForCompany`
  gate used on `CustomerPricing`).
- `GET /api/subscriptions/<id>/` — detail.
- `PATCH /api/subscriptions/<id>/` — provider-side update (e.g. pause,
  change price). Audit-tracked.
- `DELETE` — soft via `is_active=False`; hard delete blocked once
  executions exist.
- `GET /api/subscriptions/<id>/executions/` — per-plan execution list.
- `POST /api/subscriptions/<id>/executions/run/` — manual fire (for
  catch-up); the recurring scheduler is a Celery Beat task.

Customer-side surface (read-only): under `/api/me/subscriptions/`,
filtered by `scope_customers_for(user)`. CUSTOMER_USER actors see their
own plans + execution history.

---

## 4. Scheduler

Celery Beat task `extra_work.tasks.fire_due_subscription_executions`,
runs daily at 00:05 UTC. For each `SubscriptionPlan` where
`is_active=True` and `active_from <= today` and (`active_to IS NULL` OR
`active_to >= today`):

1. Determine the next un-spawned period the plan owes (`cadence` +
   `cadence_day` + the most recent `SubscriptionExecution.period_end`).
2. If the period is due (`period_start <= today`), create a
   `SubscriptionExecution` with status `PENDING` inside
   `transaction.atomic()`.
3. If `auto_approve_customer=True`, spawn the operational `Ticket`
   immediately (atomic, same posture as Sprint 28 Batch 7 instant
   tickets); set `generated_ticket` and transition the execution to
   `TICKET_SPAWNED`.
4. Otherwise, emit a notification to the customer (per the Sprint 28
   notification posture) and leave the execution `PENDING` until the
   customer approves.

Idempotency: the `(subscription_plan, period_start, period_end)`
unique constraint blocks double-fires under retry.

---

## 5. Customer-side UX (placeholder)

Sidebar entry "Subscriptions" inside the customer-scoped submenu.
Read-only home: plan list + recent executions + upcoming executions +
"View invoice (PDF)" link per execution. No edit surface; provider-side
admins manage plans via `/admin/customers/:id/subscriptions/`.

---

## 6. Open questions parked for the future sprint

These intentionally do not bind a decision today:

- **Billing trigger ownership.** Does the subscription scheduler own
  invoice generation directly, or does it spawn a `Ticket` and let the
  ticket-completion flow generate the invoice (consistent with ad-hoc)?
  The latter is more uniform.
- **Interaction with ad-hoc Extra Work.** If a customer has a weekly
  cleaning plan AND requests one-off extra work in the same week, are
  these two separate invoices or one combined? Spec §8 separates them;
  the future sprint must confirm.
- **Customer approval cadence.** Does each individual execution need
  customer approval (heavy), or only the parent plan (light)? Today's
  proposal-approval flow assumes per-instance. For subscriptions the
  product call is per-plan with optional per-execution skip via
  `auto_approve_customer=True`.
- **Provider-side override on a subscription execution.** Spec
  §6 / §7 establish provider override with mandatory reason on
  customer-decision transitions. For subscriptions, override semantics
  are likely "fire this execution despite customer-side pause" — same
  shape, separate concrete enforcement.

---

## 7. What this doc explicitly does NOT do

- Does not add any column to `Proposal`, `ProposalLine`, `Ticket`,
  `ExtraWorkRequest`, or `Customer` today. Premature columns are
  forbidden per master plan §2A.9.
- Does not create a `SubscriptionPlan` or `SubscriptionExecution`
  model class.
- Does not wire any URL, view, serializer, or test.
- Does not ship a UI surface.

When subscription work is scheduled, that future sprint:

1. Lands the two model classes + migrations.
2. Registers them in `audit/signals.py` with `_*_TRACKED_FIELDS` lists.
3. Wires the API surface above with the same RBAC posture as
   `CustomerPricing`.
4. Adds the Celery Beat task with idempotency lock.
5. Adds Playwright coverage for the customer read surface.
6. Updates the `osius.*` permission resolver if a new key is needed
   for subscription management.

Until then, this document is the contract.
