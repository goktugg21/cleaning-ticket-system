> **ARCHIVED — historical.** Describes the system as of 2026-07-26. Not
> maintained; do not rely on it as current truth. Live docs: `docs/README.md`.
> Moved out of `docs/planning/sprint-checklist.md` in Sprint 122.1. **Two
> corrections made during that move (verified against the actual commits,
> not copied from the prior write-up):**
> 1. This file's own "Found during Sprint 119 verification, not fixed in
>    it" section originally said K-1 and K-2 were NOT fixed as of Sprint
>    119 — both were in fact fixed in **Sprint 120** (PR #117, commit
>    `f8bcf41` for K-1; the same PR's `fix(ui): exhaustive paging...`
>    commits for K-2, which also found and fixed two MORE truncating pages
>    beyond the two K-2 named).
> 2. Sprint 118 (the intermittent frozen-screen bug) was described
>    elsewhere in the old checklist as "investigation-first, a fix is not
>    promised" — but PR #115's own commit history shows it WAS root-caused
>    and fixed in that same PR. Added below as its own section, since it
>    was missing a proper write-up entirely.
>
> **Engineering-gotcha note (Sprint 122.1):** the Sprint 118 root cause
> (a native `<dialog>` left the document inert if a component unmounts
> without calling `close()` first) is a reusable pattern, not sprint
> history — it is NOT currently documented in
> `docs/engineering/claude-code-operational-notes.md` and arguably should
> be. Out of scope for this docs-only pass (which touches only
> `sprint-checklist.md`, this archive, and one `CLAUDE.md` line); flagged
> here and in the live checklist's `## NEXT` so it isn't lost.

# Sprint 116 — CustomerCompanyPolicy binds Customer Company Admins (DONE)

Branch `feat/sprint-115`, commits `2412e3a` (Session A) + `392a57e`
(Session A2). No migration; no frontend file touched.

**Owner decision (2026-07-26):** `backend/customers/permissions.py::user_can`
previously short-circuited any `is_company_admin` membership straight to the
CCA role defaults, bypassing the customer's `CustomerCompanyPolicy` entirely
(flagged in-source as awaiting a decision). The owner decided **against**
the bypass: **company-level policy toggles now bind a company-wide CCA.**
See [`sot-addendum-a-meeting2.md`](../../product/sot-addendum-a-meeting2.md)
§A.1.1 for the full authoritative writeup.

- **Session A** — `user_can` now consults the customer's policy (via the
  new shared, customer-keyed `_policy_denies_for_customer`) before returning
  the CCA role default.
- **Session A2** — closed two ticket-path bypasses that short-circuited
  *before* ever reaching `user_can`, re-opening the gap for two of the four
  toggles: ticket creation (`tickets/serializers.py`) and the
  `SCOPE_CUSTOMER_LINKED` branch of `tickets/state_machine.py`. Both now
  defer to `user_can`'s own CCA branch.
- **All four `CustomerCompanyPolicy` toggles now bind a CCA:**
  `customer_users_can_create_tickets`,
  `customer_users_can_approve_ticket_completion`,
  `customer_users_can_create_extra_work`,
  `customer_users_can_approve_extra_work_pricing`.
- CCA **visibility** (`scope_tickets_for`, `scope_extra_work_for`,
  `company_admin_customer_ids`) is **unchanged** — denial is action-only.
- No per-building row can downgrade a CCA (unchanged); company policy is the
  only layer that narrows one.

**Regression pattern (kept for future audits — this lesson still applies):**
the #109 audit finding P2-2 ("the customer-approval gate checked only
access-row existence, not the permission layer") was correctly fixed at the
`user_can` gate in `tickets/state_machine.py`. But a **later** CCA
short-circuit was added *above* that same gate (`if ticket.customer_id in
company_admin_customer_ids(user): return True`), so a CCA never reached the
fixed gate at all — the fix was correct and a different code path routed
around it. **Lesson: when an audit finding is fixed at a specific gate,
also check for any caller that returns before reaching that gate** — a
correct fix at one layer does not survive a bypass added at a layer above
it.

---

# Sprint 118 — intermittent frozen-screen bug: root-caused and fixed (DONE)

Branch `feat/sprint-115`, part of the PR #115 batch. Owner-reported symptom:
"sometimes the screen gets frozen — I can scroll the page but can't touch
anything, and I have to refresh to get over it." The original checklist
described this sprint as "investigation-first; a fix is not promised in one
pass" — that framing is stale; a fix WAS shipped in this same PR.

**Root cause:** `ConfirmDialog` wraps a native `<dialog>` opened with
`showModal()`, which promotes it to the browser's top layer and makes the
rest of the document **inert** (pointer input swallowed while the page
still scrolls — exactly the reported signature). The component exposed
`open()`/`close()` but had no unmount cleanup: if it unmounted while still
open (e.g. a confirm handler that navigates away without calling `close()`
first), the node was torn out of the DOM without `close()` ever running.
Removing an open modal only reliably releases the top-layer/inert state on
engines that run the `<dialog>` "removing steps" correctly — where they
don't, the document is left permanently inert until a manual refresh.

**Fix:** a shared `useEffect` cleanup in `ConfirmDialog` closes the dialog
if it is still open at unmount, while the node is still attached — one
shared fix covering all 28 `ConfirmDialog` consumers (an audit found one
un-mitigated navigate-without-close path, `InvoiceDetailPage`'s delete
handler, plus seven pages that navigate but happened to close first). The
same latent issue existed on `TicketDetailPage`'s attachment-preview
dialog (the only other native `<dialog>` in the app) and got the same
unmount-close fix as a follow-up commit.

**Verification:** reproduced the mechanism via Playwright (vite-preview +
token-inject, dev stack, Chromium 132) — before the fix, unmounting a page
with an open dialog left `dialogOpenBeforeUnmount=1,
close()-calls-during-unmount=0`; after the fix,
`close()-calls-during-unmount=1`. Normal open/cancel/re-open/Esc behaviour
unchanged. **Honest limitation, recorded at the time:** Chromium 132's
plain unmount path self-heals, so the fully persistent freeze could not be
reproduced end-to-end from a navigation in that engine — the persistent
case reproduces via `display:none`-while-open, and the affected behaviour
is browser-dependent (matching the owner's "intermittent, refresh-fixes-it"
description). The fix is correct at the mechanism level on every engine.

**Engineering-gotcha note (Sprint 122.1):** this root cause and fix pattern
(always close a native `<dialog>` on unmount) is reusable and NOT currently
recorded in `docs/engineering/claude-code-operational-notes.md` — see the
banner at the top of this file.

---

# Sprint 119 — staff-credential PDF modal + known-issues batch (DONE)

Branch `feat/sprint-115`, commits `a8d7ee8` (Part A) + `1afce52` (Part B).
Sprint 119.1 (docs-only) audited two carry-forward findings a reviewer
produced under time pressure before recording them — see "Found during
Sprint 119 verification" below for what changed under audit, and the note
at the top of this file for the Sprint 120 resolution of both.

- **Part A** — in-app PDF preview for staff credential documents
  (`frontend/src/components/PdfPreviewDialog.tsx`, wired into
  `StaffCredentialModal.tsx` and `UserDetailPage.tsx`'s
  `CredentialsReadOnlyCard`), mirroring the existing ticket-attachment
  preview. No backend change — reuses the existing resolver-gated download
  endpoint; the EU_NATIONAL_ID hard block is enforced entirely server-side
  and unaffected.
- **Part B — six known issues closed:**
  - `/due/` now reports unbilled work THROUGH the current month, not just
    the current month (§B.10 of the invoicing addendum, now marked FIXED).
  - Two stale invoicing docstrings (`models.py`, `numbering.py`) corrected
    to say numbering is assigned at SEND, not "AT ISSUE".
  - `accounts/scoping.py::company_ids_for`'s BUILDING_MANAGER branch
    de-duplicated (`.distinct()`) — a BM assigned to N buildings in one
    company no longer reports that company N times. The audit also found
    the CUSTOMER_USER branch has the identical latent shape
    (`CustomerUserMembership` is `unique_together=(customer, user)`, not
    `(company, user)`) and fixed it too.
  - `LoginPage.tsx`'s never-wired "remember device" toggle removed (state,
    import, and the orphaned `remember_me` i18n key).
  - `ExtraWorkListPage.tsx`'s stale "unpaginated" comment corrected to
    describe the real, still-open truncation gap (fixed in Sprint 120 —
    see below).
  - Three `ConfirmDialog` consumers (`StaffAssignmentRequestsAdminPage`,
    `ExtraWorkDetailPage`, `RecurringJobDetailPage`) that only closed their
    dialog on the success branch now also close it on the error branch.

## Found during Sprint 119 verification — BOTH fixed in Sprint 120

Two items a reviewer flagged were audited in Sprint 119.1 before being
recorded here — **both claims were technically correct but each needed a
correction** to how reachable/severe they actually were. Recorded below as
the VERIFIED version, not the original report. **Both were then fixed in
Sprint 120** (PR #117) — recorded as still-open in the original Sprint 119
text; that is now stale, corrected by the Sprint 122.1 audit.

- **(K-1) `unbilled_extra_work_through` can crash on an unresolvable
  billing month** — `backend/invoicing/selectors.py`, the
  `unbilled_extra_work_through` comprehension (Sprint 119's new `/due/`
  selector). `extra_work.billing.billing_month(ew, ticket)` returns `None`
  when `ew.invoice_date` is unset AND (`ticket is None` or
  `ticket.closed_at is None`); `is_earned(ticket)` only checks
  `ticket.status == CLOSED` and does **not** require `closed_at` to be set,
  so the two conditions are not mutually exclusive. The comprehension
  gates on `is_earned(...) and billing_month(...) <= (year, month)`: the
  old exact-match selector's `== (year, month)` evaluates `None == tuple`
  safely to `False`, but the new selector's `<=` evaluates `None <= tuple`,
  which raises `TypeError` in Python 3 — uncaught, this would 500 the
  `/due/` endpoint.
  **Reviewer's original framing, corrected:** the reviewer listed "a data
  import, a raw `QuerySet.update()`, a migration, or seed/test fixtures"
  as reachability vectors. Audited each and found **none of them exist**:
  every non-test `.update()` on `Ticket` touches only SLA fields, never
  `status`/`closed_at`; the one migration touching `Ticket` fields only
  backfills `extra_work_request_id`; `seed_demo_data.py` walks every ticket
  to CLOSED exclusively via the real `apply_transition` state machine.
  **Not reachable through the application, and not reachable through any
  existing migration, management command, or bulk update either.**
  The one thing that WAS real: `backend/invoicing/tests/_helpers.py`'s
  `InvoicingFixture.make_ew` signature defaulted to
  `ticket_status=TicketStatus.CLOSED, closed_at=None` with a docstring
  claiming "default: earned in May 2026" — misleading, since the actual
  default silently produced exactly the None/CLOSED combination.
  **FIXED in Sprint 120** (commit `f8bcf41`): `unbilled_extra_work_through`
  now resolves `billing_month(...)` once per row and excludes it when
  None; `make_ew`'s default was fixed with a sentinel so
  `ticket_status=CLOSED` no longer silently pairs with `closed_at=None`;
  regression coverage added at both the selector and `/due/`-endpoint
  layers (125 tests, OK).

- **(K-2) `ExtraWorkListPage.tsx` silently truncates past 100 rows** —
  `frontend/src/pages/ExtraWorkListPage.tsx`'s `load()` effect requested
  `page_size: 100` and never followed `next`, feeding the KPI strip, the
  rendered list, AND the CSV export from the same truncated set, with no
  "showing X of Y" indicator anywhere.
  **Reviewer's finding: confirmed correct.** `listAllExtraWork` (same
  file) already existed and paged exhaustively (a usable interim fix, at
  the cost of `ceil(matching_rows / 100)` sequential requests).
  **Newly found in the Sprint 119 audit session — the same shape was
  systemic:** `FacturenPage.tsx`'s invoice list had the identical pattern.
  **FIXED in Sprint 120** (PR #117): `ExtraWorkListPage` and `FacturenPage`
  both moved to their exhaustive fetchers (`listAllExtraWork` /  the new
  `listAllInvoices`, mirroring `listAllExtraWork`'s exact template). Sprint
  120 ALSO found and fixed **two further instances** while auditing this
  shape: `DashboardPage.tsx`'s billing-KPI widget (`page_size: 500` — over
  DRF's `max_page_size=200`, so silently clamped, confirmed by direct curl
  against the dev stack: `count: 220, results.length: 200` for 220 real
  rows) and `CustomerReportsPage.tsx`'s customer-facing report tab (the
  same `page_size: 500` shape). All four now use the exhaustive
  accumulate-until-`next`-is-null fetcher; empirically verified against
  220 seeded rows crossing both the old 100-row and the DRF 200-row
  boundaries, then cleaned up (220 EW + 220 tickets deleted, recount
  confirmed 0 remaining).

*(Note: proposal-10's `f — 1.00 x OTHER @ 0.00` line was confirmed junk demo
data, not a bug.)*
