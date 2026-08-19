# Extra Work gap closing — decisions and sprint plan

**Status: decided.** The owner has signed off on every open question below. This file is
the contract for the work. CC reads it; it does not get to relitigate it.

Background evidence: `docs/reference/osius-reference-system/` — a read-only investigation
of the reference system this work is closing the gap against. Where this file says "they
do X", it is verified there.

---

## 0. THE RULES FOR EVERY SPRINT IN THIS PLAN

**One branch.** Everything lands on `feat/ew-gap-closing`. No second branch, no second PR.
The owner reviews once, at the end, and merges when the whole thing is right.

**Run only the tests the change actually needs.** Name the test modules. Never run an app
label. Never run the full suite. The tickets suite alone is ~29 minutes on one CPU and
running it "to be safe" is the single most common way this project has burned an
afternoon. If a change touches a shared function, run the tests of every app that calls
it — but name those modules too.

**Judge a test run by the textual `OK` / `FAILED` line**, never the exit code.

**Frontend gate:** `tsc --noEmit`, `eslint .` (baseline is exactly **44** — 42 errors, 2
warnings; add none, add no `eslint-disable`), `npm run build`.

**i18n:** nl and en in strict lockstep, identical key sets, nl primary. Every user-visible
string through `t()`.

**Git:** stage by explicit path. Never `git add -A`. Never stage
`PRODUCTION_READINESS_AUDIT.md`, the repo-root `logo.png`, `*.code-workspace`, or
`docs/transkript*`.

**Migrations are additive.** No destructive schema changes.

**Tenant scoping is absolute.** No cross-tenant or cross-customer leakage, ever. A change
that contradicts one of the 11 invariants in `docs/reference/rbac-matrix.md` §3 is a P0
even if every test passes.

**Money has one rule:** `rowAmounts()` in `frontend/src/lib/billing.ts`, mirrored
server-side. Zero is a legal price — "unpriced" and "costs nothing" must never render the
same.

**Close the sprint by updating `docs/planning/sprint-checklist.md` in the same commit.**

---

## 1. THE DECISIONS

| # | Question | Decision |
|---|---|---|
| 8 | Default visibility for staff photo uploads | **Internal until a provider promotes it.** Nothing a worker uploads is customer-visible by default. A per-work setting can make staff uploads immediately visible where a customer wants that |
| 12 | Where labour cost is computed | **In `reports/`, not `timesheets/`.** The timesheets module's no-money rule stays intact. **And the UI must say where each number comes from** — the hours screen states plainly that hours live in timesheets and cost is computed in reporting, so nobody hunts for a wage field that does not exist |
| 14 | The billing cutoff | **Option A — the cutoff rule.** Work that is done and waiting on the customer before the cutoff bills in that period. **Option B (provider approves on behalf, with a mandatory reason) stays as the exception path** for one-off cases |
| 1 | Financial totals | **Not attached to the chip.** A small, clearly-labelled figure strip on the Extra Work page and the Chargeable Work page. Four numbers, no more — see §2.4 |

---

## 2. WHAT WE BUILD

### 2.1 Layout (items 2, 3, 4, 5)

- **Item 2** — Department and Work Type under Preferred Date on the Extra Work detail
  page, in the empty space that already exists there. Not a new side card. Customer
  Contacts moves INTO the main card, to the right of the description.

  > Changed in wave 2 (Sprint 190, chat B). This item originally ended *"Customer
  > Contacts extends downward into the freed space"*, and Sprint 189 shipped that:
  > the panel stayed in the right-hand aside and simply got taller. The owner asked
  > for it in the main card instead, beside the description, so the two label fields
  > and the contacts sit in one place rather than either side of the page.
- **Item 3** — Workflow buttons larger and more prominent, on **both** the Extra Work
  detail page and the Ticket detail page.
- **Item 4** — Location and Customer shown prominently at the top-right of the Ticket
  detail page, in roughly title size. **They stay in the Ticket Details card as well** —
  this is an added display, not a move. They appear there **whether or not** the ticket
  has a Convert-to-Extra-Work button.
- **Item 5** — Right column order on the Ticket detail page:
  **Location & Customer → Workflow → Assignment → Responsible Manager → Scheduling →
  Ticket Details.**

  > Changed in wave 2 (Sprint 190 §1). This item originally read
  > *Workflow → Location & Customer → ...* and shipped that way in Sprint 189. The owner
  > reviewed it on the test site and swapped the first two: the two facts that tell you
  > WHICH job you are looking at belong above the control that changes it, directly under
  > the Convert-to-Extra-Work button. The line above is the current order.

### 2.2 The planning layer (items 6, 10, 11, and item 7's flags)

- **Budget hours** on the extra work, set when the work is planned.
- **Distributed across the assigned workers** — planned hours per person.
- **Requested dates and planned dates are separate stored values.** The customer's
  requested start and deadline are not overwritten by what the provider commits to.
- **Plan and start in one action**, as they do.
- **Bulk plan** — the same fields for many works in one table.
- **Planned vs actual side by side on the approval screen**, so the manager approving sees
  an overrun before approving.
- **Warn on overrun. Never block.**

> The no-block rule is not a preference. In the reference system the hard cap exists as a
> complete function, `validateTotalHours()`, and is never called — the model carries the
> comment `// Hours validation removed per user request`. Somebody built the block and the
> business had it removed. We warn.

**Budget hours never touches money.** It is a planning and control number. `rowAmounts()`
remains the only money rule.

**Do not build a "coordinator" concept.** In the reference backend the word does not
appear at all — it is a frontend label with no behaviour. We already have responsible
managers and staff assignments.

### 2.3 Completion requirements (item 7)

Two independent booleans on the work, set at plan time, **both default off**:
`file_upload_required`, `completion_notes_required`.

Enforced **server-side, in the completion transition, in one place**. Today our slot gate
accepts a note **OR** a photo, hardcoded (`backend/tickets/models.py:661`). That becomes
configurable.

Bulk plan must carry both flags. In the reference system bulk plan writes both to `false`
on every selected work, silently wiping whatever was set.

### 2.4 Financial totals (item 1)

A clearly-labelled figure strip on the Extra Work page and the Chargeable Work page. Four
numbers, each one plainly named so an operator knows what it means without asking:

1. **Quoted, not yet started** — priced work the customer has approved that has not become
   operational work yet. Money committed but not earned.
2. **In progress** — the value of work that is started and not yet done. Money that lands
   when the work finishes.
3. **Done this period** — value completed in the current billing month.
4. **Invoiced this period** — of that, how much has actually been billed.

Every figure computed through `rowAmounts()` or its server-side mirror. **No second money
formula.** The reference system computes work totals six different ways with three
rounding points and two of them disagree by cents on the same record; we are not going
there.

Also, the chip fix: selecting **Quote & Price** or **Chargeable Work** also selects
**All**.

### 2.5 The photo pool (item 8)

- Staff uploads land **internal** by default.
- A provider manager promotes a photo to customer-visible with one action.
- A per-work setting can make staff uploads immediately customer-visible.
- **Phase (before / after) is a separate label from visibility.** The reference system
  conflates them, which is why its "Draft Images" render to customers under that heading.

We already have `TicketAttachment.is_hidden` and the visibility model from Addendum A
§A.3.3 (every artefact carries a level, default most-restrictive). Build on those.

### 2.6 The billing cutoff (item 14)

Add a second arm to `is_earned()` in `backend/extra_work/billing.py`: a work is also
earned if its ticket is at `WAITING_CUSTOMER_APPROVAL` **and** `sent_for_approval_at` is on
or before the customer's cutoff.

`WAITING_MANAGER_REVIEW` must **not** qualify — that is staff saying done with nobody
having checked.

Two things this touches and one it does not:

- It changes what "earned" means, and `reports.dimensions` classifies earned the same way.
  One place, deliberately.
- The customer needs a plain, prominent explanation that work completed before the cutoff
  may appear on the coming invoice before their approval lands.
- **The rejection case needs nothing new.** A SENT invoice is immutable and reversal
  releases the work back to the unbilled pool via `invoice__reversed_by__isnull=True` in
  `backend/invoicing/selectors.py`. Reject after billing → reverse, credit note, work
  returns for the next cycle.

### 2.7 Time-driven warnings and escalation

`backend/sla/` already runs every 5 minutes over every non-terminal ticket with real
business-hours arithmetic and **notifies nobody**. All nine of our notification event types
are event-driven; "nothing happened and it should have" is an empty category.

Build: wire the existing SLA engine to the existing notification layer, give Extra Work its
own clock (today the engine covers tickets only), and add one escalation hop to the
responsible manager.

Three warnings:
- work completed and awaiting customer approval as a billing cutoff approaches;
- work waiting on a manager's approval past its target;
- work that should have started and has not.

### 2.8 The hours screen (item 12)

The model is already built — `TimeEntry` carries `source_type` / `source_id` with
`HourSource` = CONTRACT / EXTRA_WORK / TICKET / OTHER, and contract-hours approval already
has DRAFT / SAVED / APPROVED.

What is missing is the screen: an hours grid on the Extra Work (worker × day × hour type)
and the roll-up of budget / entered / cost. **Labour cost is computed in `reports/`.** The
screen states where each number lives.

---

## 3. WHAT WE DELIBERATELY DO NOT BUILD

| Not building | Why |
|---|---|
| An Archive state | Their status 8 "Voltooid" sits after customer approval and is the sole billing gate. That is our `CLOSED`. Two names for one fact |
| A coordinator role | The word does not exist in their backend |
| Instalment billing | Exists only in their v2; one record uses it; the father works in v1 |
| A hard cap on hours | Their business had it removed |
| Invoicing as a work status | Their status 7 reads "Gefactureerd" but means something else; an operator moved ~25 live works to the wrong one |
| A `summary_price` style override | On their invoice it wins on page 1, loses on page 2, and never reaches the database |
| Copying their state model | They validate only that the status id exists. Any status to any status, either direction, one permission bit |
| Bulk approve as a mass update | Their group approve jumps straight past customer approval into the billing pool; eight live records are in that state |

---

## 4. THE SPRINTS

Three waves. Sprints inside a wave touch **no shared file** and run as parallel CC chats.
Waves are sequential because wave 2 builds on wave 1's files.

### Wave 1 — three chats in parallel

| Sprint | Scope | Owns |
|---|---|---|
| **W1-A — Layout** | Items 2, 3, 4, 5. Frontend only. No backend, no migration | `frontend/src/pages/ExtraWorkDetailPage.tsx`, `frontend/src/pages/TicketDetailPage.tsx` and components used only by those two |
| **W1-B — Billing cutoff + warnings** | Item 14 and §2.7. Mostly backend | `backend/extra_work/billing.py`, `backend/tickets/state_machine.py`, `backend/sla/*`, `backend/notifications/*`, the customer-facing cutoff notice |
| **W1-C — Financial totals** | Item 1 | `frontend/src/pages/ExtraWorkListPage.tsx`, `frontend/src/pages/DashboardPage.tsx` (the `chargeable-work` variant), and a new aggregation endpoint in `backend/extra_work/` |

### Wave 2 — three chats in parallel, after wave 1 lands

| Sprint | Scope | Owns |
|---|---|---|
| **W2-D — Planning layer** | Items 6, 10, 11 + item 7's two flags on the model | `backend/extra_work/models.py` + migration, the plan modal, the bulk-plan table. Planned hours per worker go in a **new model in `extra_work`** — not in `tickets`, not in `timesheets` |
| **W2-E — Photo pool** | Item 8 | `backend/tickets/models.py` (TicketAttachment) + migration, attachment components, the promote action |
| **W2-F — Hours screen** | Item 12 | `backend/timesheets/` read APIs, `backend/reports/` labour cost, a new hours tab component |

### Wave 3 — one chat

| Sprint | Scope | Depends on |
|---|---|---|
| **W3-G — Completion enforcement** | Item 7's server-side gate and the completion screen | W2-D (the flags exist) and W2-E (the photo pool exists) |

---

## 5. BRANCH MECHANICS FOR PARALLEL CHATS

One branch. Create and push it **once, before any chat starts**:

```
git checkout -b feat/ew-gap-closing && git push -u origin feat/ew-gap-closing
```

Each parallel chat then works in its own worktree, detached, and pushes to that one branch:

```
git worktree add /home/adm-local/w1a --detach origin/feat/ew-gap-closing
# ... work, commit by explicit path ...
git pull --rebase origin feat/ew-gap-closing
git push origin HEAD:feat/ew-gap-closing
```

Because the sprints in a wave own disjoint files, the rebase is clean. If a push is
rejected, pull-rebase again and retry — never force-push.
