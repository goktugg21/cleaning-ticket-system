# Ticket workflow decision audit (Sprint 13)

> **Status:** documentation only. **No behavior change.**
> The pilot will ship the workflow as it is today. This document
> describes what the code does, the ambiguity Sprint-12 pilot
> feedback surfaced, three product options to resolve it, a
> recommendation, and an implementation plan to keep on the shelf
> until the operator picks an option.
>
> **Audited commit:** Sprint 12 merge (`6daf658`).
>
> **Where the rules live:**
> - State machine: [backend/tickets/state_machine.py](../backend/tickets/state_machine.py)
> - Create / status / assign serializers: [backend/tickets/serializers.py](../backend/tickets/serializers.py)
> - Viewset: [backend/tickets/views.py](../backend/tickets/views.py)
> - Frontend status buttons: [frontend/src/pages/TicketDetailPage.tsx](../frontend/src/pages/TicketDetailPage.tsx)

---

## A. Current behavior

Every ticket — regardless of who created it — follows the **same
single linear workflow**:

```
OPEN
  └─> IN_PROGRESS
        └─> WAITING_CUSTOMER_APPROVAL
              ├─> APPROVED ─> CLOSED
              │                  └─> REOPENED_BY_ADMIN ─> IN_PROGRESS …
              └─> REJECTED ──> IN_PROGRESS …
```

There is **no** field on the Ticket model that distinguishes a
"customer request" from an "internal task". `WAITING_CUSTOMER_APPROVAL`
is reached by the same edge regardless of origin.

### Common to every role

- **Initial status** is always `OPEN`
  ([serializers.py:294](../backend/tickets/serializers.py#L294)) —
  hard-coded in `TicketCreateSerializer.create`.
- **Soft-delete (Sprint 12)** is orthogonal to status; it works on
  any status and is not part of the workflow.
- **Assignment** (`assigned_to`) is a separate field. Only staff
  (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) can call
  `POST /api/tickets/<id>/assign/`, and the assignee must be a
  `BUILDING_MANAGER` already attached to the ticket's building
  ([serializers.py:489-503](../backend/tickets/serializers.py#L489-L503)).
- **`created_by` does not grant any extra workflow rights.** A
  customer user who opened a ticket has no different permissions on
  it than any other customer user attached to the same customer; a
  building manager who opened a ticket cannot approve or close it.
- **`SUPER_ADMIN` is special-cased** in `can_transition` and
  `allowed_next_statuses`
  ([state_machine.py:96-97 / 159-164](../backend/tickets/state_machine.py#L96-L97))
  — they can perform any non-no-op transition regardless of the
  matrix below.
- **`WAITING_CUSTOMER_APPROVAL` always literally means "wait for
  customer approval".** Even when no real customer is in the loop
  (e.g. a manager-opened internal task), the only way to leave that
  status is via `APPROVED` or `REJECTED`, which only customer-users,
  COMPANY_ADMINs, and SUPER_ADMINs can perform.

### Per-role transition matrix (from
[state_machine.py:18-57](../backend/tickets/state_machine.py#L18-L57))

| From → To | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER |
|---|---|---|---|---|
| `OPEN → IN_PROGRESS` | ✅ any | ✅ company | ✅ assigned to building | — |
| `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL` | ✅ any | ✅ company | ✅ assigned to building | — |
| `WAITING_CUSTOMER_APPROVAL → APPROVED` | ✅ any | ✅ company | — | ✅ linked to customer |
| `WAITING_CUSTOMER_APPROVAL → REJECTED` | ✅ any | ✅ company | — | ✅ linked to customer (note required) |
| `REJECTED → IN_PROGRESS` | ✅ any | ✅ company | ✅ assigned to building | — |
| `APPROVED → CLOSED` | ✅ any | ✅ company | — | — |
| `CLOSED → REOPENED_BY_ADMIN` | ✅ any | ✅ company | — | — |
| `REOPENED_BY_ADMIN → IN_PROGRESS` | ✅ any | ✅ company | ✅ assigned to building | — |

### Per-role: what happens when they create a ticket

#### CUSTOMER_USER

| | |
|---|---|
| Can create? | ✅ — `POST /api/tickets/` if the chosen `customer` is one of their `CustomerUserMembership`s and the customer's `building` matches ([serializers.py:272-280](../backend/tickets/serializers.py#L272-L280)). |
| Initial status | `OPEN` |
| Who can assign it? | Staff only (any of SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER assigned to the building). |
| Who can move to IN_PROGRESS? | SUPER_ADMIN, COMPANY_ADMIN (in company), BUILDING_MANAGER (assigned to building). |
| Who can move to WAITING_CUSTOMER_APPROVAL? | Same as IN_PROGRESS. |
| Who can approve? | SUPER_ADMIN, COMPANY_ADMIN (in company), CUSTOMER_USER (linked to customer — including, but **not exclusively**, the original creator). |
| Who can reject / reopen? | Reject: same as approve. Reopen-from-CLOSED: SUPER_ADMIN or COMPANY_ADMIN only. Reopen-from-REJECTED to IN_PROGRESS: SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER. |
| Who can close (APPROVED → CLOSED)? | SUPER_ADMIN, COMPANY_ADMIN. |
| Does the creator get special approval rights? | **No.** Any customer-user linked to the same customer can approve. The creator is not preferred. |
| Does WAITING_CUSTOMER_APPROVAL mean "customer must approve"? | Yes. This is the originating use case for the status. |

#### BUILDING_MANAGER

| | |
|---|---|
| Can create? | ✅ — must be `BuildingManagerAssignment` for the chosen building ([serializers.py:262-271](../backend/tickets/serializers.py#L262-L271)). |
| Initial status | `OPEN` (same as everyone). |
| Who can assign it? | Staff only. A building manager can assign tickets — including ones they created — to themselves or any other manager attached to the building. |
| Who can move to IN_PROGRESS? | SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER (themselves or any peer assigned to the building). |
| Who can move to WAITING_CUSTOMER_APPROVAL? | Same. |
| Who can approve? | SUPER_ADMIN, COMPANY_ADMIN, **or** any CUSTOMER_USER linked to the ticket's customer. **The building manager cannot approve their own ticket.** |
| Who can reject / reopen? | Reject: same as approve. Reopen-from-CLOSED / REJECTED: as above. |
| Who can close? | SUPER_ADMIN, COMPANY_ADMIN. |
| Does the creator get special approval rights? | **No.** A manager who opened the ticket has no privileged path through the workflow. |
| Does WAITING_CUSTOMER_APPROVAL mean "customer must approve"? | Currently **yes by code, but possibly no by intent** — see §B. |

#### COMPANY_ADMIN

| | |
|---|---|
| Can create? | ✅ — must be `CompanyUserMembership` for the building's company ([serializers.py:251-260](../backend/tickets/serializers.py#L251-L260)). |
| Initial status | `OPEN`. |
| Who can assign it? | Themselves, any other COMPANY_ADMIN of the company, SUPER_ADMIN, BUILDING_MANAGER attached to the building. |
| Who can move to IN_PROGRESS? | Themselves and the other staff roles in scope. |
| Who can move to WAITING_CUSTOMER_APPROVAL? | Same. |
| Who can approve? | Themselves, peer COMPANY_ADMINs, SUPER_ADMIN, or any CUSTOMER_USER linked to the customer. **A company admin can approve a ticket they themselves opened** — there is no creator-vs-approver guard. |
| Who can reject / reopen? | Same as approve, plus a forward path back to IN_PROGRESS. |
| Who can close? | Themselves (or any peer COMPANY_ADMIN / SUPER_ADMIN). |
| Does the creator get special approval rights? | No formal rule, but in practice they have full approval / close rights anyway. |
| Does WAITING_CUSTOMER_APPROVAL mean "customer must approve"? | The path goes through the status, but a COMPANY_ADMIN can approve the ticket themselves without involving any customer-user (`isAdminCustomerDecisionOverride` in [TicketDetailPage.tsx:53-63](../frontend/src/pages/TicketDetailPage.tsx#L53-L63) makes this an "admin override" path with a confirm-twice warning, but it is allowed). |

#### SUPER_ADMIN

| | |
|---|---|
| Can create? | ✅ — short-circuits all scope checks ([serializers.py:248-249](../backend/tickets/serializers.py#L248-L249)). |
| Initial status | `OPEN`. |
| Who can assign it? | Anyone with staff role in scope; SUPER_ADMIN themselves of course. |
| Workflow transitions | SUPER_ADMIN can perform **any** transition that is not a no-op ([state_machine.py:96-97](../backend/tickets/state_machine.py#L96-L97) / [:159-164](../backend/tickets/state_machine.py#L159-L164)). They are not constrained by the matrix. |
| Does the creator get special approval rights? | No formal rule, but irrelevant — SUPER_ADMIN can do anything anyway. |
| Does WAITING_CUSTOMER_APPROVAL mean "customer must approve"? | Same as COMPANY_ADMIN: SUPER_ADMIN can self-approve via the admin-override path. |

### One-line summary of A

The current workflow is **one workflow for all tickets**. Every
ticket must (in code) pass through `WAITING_CUSTOMER_APPROVAL`
before it can reach `APPROVED → CLOSED`. There is no field
distinguishing customer-facing requests from internal operational
tasks; the system trusts staff to use the admin-override path when
the customer is not actually in the loop.

---

## B. Current risk / ambiguity

The pilot user surfaced this concern: **the same workflow is being
used for two semantically different things.**

1. **Customer-opened ticket.** Customer reports a leaking tap, a
   manager investigates, sets `IN_PROGRESS`, fixes it, sends it for
   the customer's approval. The customer flips the ticket to
   `APPROVED`. An admin closes it. → `WAITING_CUSTOMER_APPROVAL`
   means *literally* what it says. ✅ Clean.

2. **Manager-opened internal task.** A building manager notices a
   common-area light is out and opens a ticket so they have a
   record. They fix it. To close it, the system requires the ticket
   to first go to `WAITING_CUSTOMER_APPROVAL`. There is no real
   customer awaiting anything — the manager is forced to either
   wait for an arbitrary customer-user to approve (irrelevant) or
   call the COMPANY_ADMIN admin-override path. → The status is now
   misleading: nobody is actually waiting for customer approval.

3. **Admin-opened operational task.** A COMPANY_ADMIN opens a
   ticket to track a vendor visit they need to coordinate. They
   move it through the same flow and self-approve via the
   admin-override path. The audit trail records "moved to
   WAITING_CUSTOMER_APPROVAL → APPROVED" but no customer-user ever
   touched the ticket. → Same issue: the lifecycle history reads
   like a customer was involved when none was.

### Does the system currently distinguish customer requests from internal tasks?

**No.** No field on the model, no flag on the API, no UI hint at
create time. The only signal an operator has is the `created_by`
role — which the codebase does not consult for workflow rules
(only for soft-delete in Sprint 12).

### What real-world confusion could happen in the pilot?

- **Audit feed reads wrong.** A COMPANY_ADMIN reading the audit
  log of an internal-task ticket will see `WAITING_CUSTOMER_APPROVAL`
  → `APPROVED` when no customer was ever in the loop. Compliance /
  customer dispute scenarios will be confusing.
- **Reports misleading.** The "Sent for approval" timestamp
  (`sent_for_approval_at`) is the only signal the reporting layer
  uses for "ticket entered review". For internal tickets it's
  noise; for customer tickets it's signal. Mixing them dilutes the
  metric.
- **Customer-side training friction.** Customer users may receive
  email notifications ("ticket awaiting your approval") for tickets
  the manager opened, was never about them, and that they have no
  context on. They will either ignore them (training noise) or
  approve them blindly (false positive in the audit trail).
- **SLA semantics mismatch.** SLA pause-on-`WAITING_CUSTOMER_APPROVAL`
  is correct when waiting for the *customer*, wrong when waiting
  for a self-approve no-op.

The risk is **low for blast radius** (no security breach, no data
loss), but **moderate for trust**: if early pilot users encounter
the friction above, they will lose confidence in the audit trail.

---

## C. Options

### Option 1 — Keep current workflow

**What:** Ship the pilot with the current single workflow.
COMPANY_ADMINs and SUPER_ADMINs use the existing admin-override
path when there is no real customer in the loop.

**Pros:**

- **Zero code change**, zero migration, zero new test surface, zero
  new release risk for the pilot.
- The admin-override warning text already exists (Dutch + English)
  and explains the override clearly.
- Pilot scale (≤ 50 users, 2-3 companies) makes the friction
  bearable.
- Pilot feedback can clarify which workflow distinction is
  actually wanted before the team commits to a model field.

**Cons:**

- Audit feed and notifications will record "customer-approval"
  events for tickets that never involved a real customer.
- Customer users may receive notification noise for tickets they
  have no context on.
- Reports that aggregate `sent_for_approval_at` will mix two
  different semantics.

### Option 2 — `requires_customer_approval` boolean

**What:** Add a boolean field on Ticket; the creator (or admin)
chooses at create time whether the ticket requires customer
approval. When `false`, the workflow allows direct
`IN_PROGRESS → CLOSED` (skipping `WAITING_CUSTOMER_APPROVAL`).

**Pros:**

- Smallest possible model change (one boolean column, default
  derived from creator role).
- Cleanly removes the false-positive customer-approval events from
  the audit feed.
- No new domain concepts to teach customer-side users — they only
  ever see `requires_customer_approval=true` tickets in their
  scope.

**Cons:**

- "True/false" is opaque in the audit feed and the UI. A reader
  later asking "*why* did this ticket skip customer approval?" has
  to infer it from the boolean.
- If the workflow continues to grow (e.g. a future "vendor
  approval" stage, "compliance sign-off"), more booleans pile up.
- The boolean conflates "*who* is the audience" with "*which*
  workflow shape to use". Two concepts collapsed into one field.

### Option 3 — `workflow_type` enum

**What:** Add a CharField `workflow_type` on Ticket with values
like `CUSTOMER_REQUEST` (default) and `INTERNAL_TASK`. Customer
requests use the current workflow; internal tasks use a shortened
workflow (`OPEN → IN_PROGRESS → CLOSED`, no `WAITING_CUSTOMER_APPROVAL`,
no customer notification, no SLA pause-for-customer).

**Pros:**

- Semantic naming. Audit feed, list filters, reports, and
  notifications can branch cleanly on `workflow_type` and the
  reason will be explicit at every layer.
- Extensible — adding `VENDOR_TASK` / `COMPLIANCE_AUDIT` later
  doesn't pile up booleans; it adds an enum value.
- Maps to a likely product-team mental model: "this is the kind of
  ticket I'm raising" is a question users already answer when they
  pick `type` (REPORT / COMPLAINT / REQUEST), so adding a sibling
  field is consistent.
- Reports can split "customer satisfaction" metrics from "operational
  throughput" cleanly.

**Cons:**

- Bigger surface area than Option 2: new enum, migration with
  default-backfill, frontend create-form change, ticket-detail
  workflow-button change, two test classes (one per workflow type),
  i18n keys for the labels in EN + NL.
- Customer users now see only a subset of tickets (`CUSTOMER_REQUEST`)
  in some views — need to confirm reports / scoping cleanly handle
  that.
- More documentation needed: a section in
  [docs/system-behavior-audit.md](system-behavior-audit.md) and a
  new line in [docs/test-reliability-audit.md](test-reliability-audit.md).

---

## D. Recommendation

**For the pilot, ship Option 1.** Do not change workflow behavior
between Sprint 13 and pilot launch.

Reasons:

1. The pilot population is two-three companies / ≤ 50 users. The
   admin-override warning text already exists (`workflow_admin_override_approved`,
   `workflow_admin_override_rejected`) and the user agreement is
   one click. Friction is real but bearable.
2. We do not yet know the operator's preferred *naming*. Sprint 12
   pilot feedback was strong enough to surface the ambiguity; it is
   not yet specific enough to choose between Option 2's terse
   boolean and Option 3's enum. Picking either too early bakes in
   a name we may want to rename.
3. Migrations on a model that already has data in pilot are
   cheaper than migrations on a model with two distinct
   workflow-shape histories. Adding a `workflow_type` field with a
   sane default once pilot data exists is a one-step migration; if
   we add it now and rename it later, that's two migrations.

**After pilot feedback:**

- If operators say "internal task should be a one-click thing",
  pick **Option 2**.
- If operators say "we want clearly labelled categories of tickets,
  with different rules and different reports", pick **Option 3**.

If forced to pick now without further feedback, prefer **Option 3**:
the enum is more honest about what is actually changing (the
*kind* of ticket, not just whether one stage is skipped) and is
cheaper to extend later.

**This sprint** explicitly does not touch the workflow code. The
audit feed and notifications continue to behave as documented in
§A.

---

## E. Implementation plan (parking lot — do not implement this sprint)

If, after pilot feedback, the operator picks Option 3
(`workflow_type` enum), this is the implementation plan to follow.
The plan is given for Option 3 because it has the larger surface
area; Option 2 is a strict subset (drop the field rename and the
enum-related copy).

### E.1 Model

```python
# backend/tickets/models.py (add to Ticket)

class TicketWorkflowType(models.TextChoices):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST", "Customer request"
    INTERNAL_TASK = "INTERNAL_TASK", "Internal task"

# field on Ticket
workflow_type = models.CharField(
    max_length=32,
    choices=TicketWorkflowType.choices,
    default=TicketWorkflowType.CUSTOMER_REQUEST,
    db_index=True,
)
```

### E.2 Migration

```python
# tickets/migrations/0006_ticket_workflow_type.py
operations = [
    migrations.AddField(
        model_name="ticket",
        name="workflow_type",
        field=models.CharField(
            choices=[
                ("CUSTOMER_REQUEST", "Customer request"),
                ("INTERNAL_TASK", "Internal task"),
            ],
            default="CUSTOMER_REQUEST",
            max_length=32,
            db_index=True,
        ),
    ),
]
```

**Backfill rule for pre-existing rows:** all rows default to
`CUSTOMER_REQUEST`. Do **not** retroactively flip manager-created
or admin-created tickets to `INTERNAL_TASK` — the `created_by` role
is a poor proxy for intent (admins do raise customer-request
tickets), and rewriting historical workflow type would corrupt
audit semantics.

### E.3 Serializer / API changes

[backend/tickets/serializers.py](../backend/tickets/serializers.py):

- `TicketCreateSerializer.Meta.fields` — add `workflow_type` (writable).
- Validation:
  - Customer users may only create `CUSTOMER_REQUEST` tickets
    (raise `ValidationError({"workflow_type": "..."})` otherwise).
  - Other roles may pick either; default if omitted is
    `CUSTOMER_REQUEST` (preserves current shape for un-updated
    clients).
- `TicketDetailSerializer.Meta.fields` — add `workflow_type`
  (read-only).
- `TicketListSerializer.Meta.fields` — add `workflow_type`
  (read-only) so the list table can show a chip / badge.

### E.4 State machine

[backend/tickets/state_machine.py](../backend/tickets/state_machine.py):

- Split `ALLOWED_TRANSITIONS` into two maps,
  `ALLOWED_TRANSITIONS_CUSTOMER_REQUEST` (today's table) and
  `ALLOWED_TRANSITIONS_INTERNAL_TASK`.
- Internal-task table:

  ```
  OPEN → IN_PROGRESS                  staff in scope
  IN_PROGRESS → CLOSED                staff in scope
  CLOSED → REOPENED_BY_ADMIN          SUPER_ADMIN, COMPANY_ADMIN
  REOPENED_BY_ADMIN → IN_PROGRESS     staff in scope
  ```

  No `WAITING_CUSTOMER_APPROVAL`, no `APPROVED`, no `REJECTED`
  states reachable.
- `can_transition` and `allowed_next_statuses` switch on
  `ticket.workflow_type` to choose the table.
- `apply_transition` is unchanged — it just receives a different
  set of allowed pairs.

### E.5 Frontend create-ticket form

[frontend/src/pages/CreateTicketPage.tsx](../frontend/src/pages/CreateTicketPage.tsx):

- New `<select>` for `workflow_type` with two options. Default
  derived from the user's role:
  - CUSTOMER_USER: locked to `CUSTOMER_REQUEST`.
  - All staff: default to `CUSTOMER_REQUEST` but selectable.
- Helper text: "Customer requests need the customer to approve.
  Internal tasks close directly when the work is done." — placed
  next to the field, not as a dialog.

### E.6 Ticket detail page

[frontend/src/pages/TicketDetailPage.tsx](../frontend/src/pages/TicketDetailPage.tsx):

- Render a small badge near the existing status / priority badges:
  "Internal task" or "Customer request".
- The status-action buttons already consume `allowed_next_statuses`
  from the API, so no client-side workflow logic to change — the
  buttons that aren't valid for the workflow simply don't render.
- Drop the admin-override warning text when `workflow_type ==
  INTERNAL_TASK` (it's no longer a customer override; the workflow
  legitimately doesn't pass through customer approval).

### E.7 Notifications

[backend/notifications/services.py](../backend/notifications/services.py):

- `send_ticket_status_changed_email` — when transitioning into
  `WAITING_CUSTOMER_APPROVAL`, the customer-user audience is *only*
  notified for `workflow_type == CUSTOMER_REQUEST` tickets. For
  internal tasks, no customer email is sent (the status is never
  reached in that workflow anyway, but the guard is defence-in-depth).

### E.8 Reports

[backend/reports/scoping.py](../backend/reports/scoping.py) and the
dimension reports: optional new filter `workflow_type=` so an
operator can split reports by ticket kind. Existing dashboards keep
showing the union by default (preserves pilot data semantics).

### E.9 Tests

New test file `backend/tickets/tests/test_workflow_types.py`:

- `test_default_workflow_is_customer_request` — POST without
  `workflow_type`, response has `CUSTOMER_REQUEST`.
- `test_customer_user_cannot_create_internal_task` — POST as
  customer with `workflow_type=INTERNAL_TASK` returns 400.
- `test_internal_task_workflow_skips_customer_approval` — staff
  creates an internal task, can transition `IN_PROGRESS → CLOSED`
  directly; cannot transition to `WAITING_CUSTOMER_APPROVAL`.
- `test_customer_request_workflow_unchanged` — every existing
  `test_state_machine.py` case still passes when
  `workflow_type=CUSTOMER_REQUEST` (the default for all fixtures).
- `test_customer_user_does_not_get_email_for_internal_task` —
  notification audience excludes customer-users when
  `workflow_type=INTERNAL_TASK`.

### E.10 SLA semantics

The SLA engine
([backend/sla/](../backend/sla/)) currently pauses on
`WAITING_CUSTOMER_APPROVAL`. For internal tasks the status is
unreachable, so no engine change is needed. Verify with one
explicit test that an internal task's SLA is **not** paused while
in `IN_PROGRESS`.

### E.11 Rollback plan

If the field needs to be removed after release, a follow-up
migration drops the column. Pre-existing rows are all
`CUSTOMER_REQUEST` (the default), so dropping the field reverts to
the current single-workflow behavior cleanly. No data restoration
required.

### E.12 Effort estimate

Roughly one focused sprint: ~1 day for backend + migration + state
machine, ~1 day for tests, ~half a day for the frontend form and
detail page, ~half a day for notifications + reports, ~half a day
for documentation updates (system-behavior-audit, test-reliability-audit,
this doc converting from "options" to "shipped"). Total ~3-4 days.

---

## What this document is NOT

- Not a green light to start implementing. Implementation is
  parked until the operator picks an option from §C based on
  pilot feedback.
- Not a replacement for the existing system-behavior audit
  ([system-behavior-audit.md](system-behavior-audit.md)) — that
  doc continues to describe the *current* behavior; this one
  describes the *future-decision* surface.
- Not a security or compliance review. The current workflow is
  not insecure; it is semantically loose.
