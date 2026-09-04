# Go-live data import — the plan (P-16 Part E4, 2026-09-03)

**Status: plan only, no code.** The import runs POST-merge, when
Ramazan hands over his real records — that is the owner's earlier
decision, and this page exists so the handover meeting has an agenda
instead of a blank sheet.

## What the real data is

Ramazan's operation, as the transcripts and meetings describe it:

| What | Rough size | Becomes |
|---|---|---|
| His cleaning company | 1 | `Company` (the provider tenant) |
| Customer organisations | ~10–30 | `Customer` + `CustomerCompanyPolicy` |
| Buildings under them | ~20–60 | `Building` + `CustomerBuildingMembership` |
| His people (cleaners, managers) | ~10–40 | `User` (STAFF / BUILDING_MANAGER) + `EmployeeProfile` + building assignments |
| Customer contacts | ~1–3 per customer | `Contact` (+ invoice-recipient flags) |
| Customer logins (if any at go-live) | few | `User` (CUSTOMER_USER) + memberships + building access |
| Standing weekly patterns ("agreed hours") | 1 per cleaner-building pair | `ContractHoursAgreement` (APPROVED, auto-fill on) |
| Contracts (the money agreements) | 1 per customer or building | `Contract` + lines — **waits for the contracts-model meeting** |
| Open work at cutover | small | entered by hand in week one, NOT imported |

## The order (dependencies, not preference)

1. Company → 2. Buildings → 3. Customers (+ policy, billing day,
billing address) → 4. Customer↔building memberships → 5. Provider
users (+ building assignments, employment facts) → 6. Contacts (+
invoice flags) → 7. Customer users (+ memberships + building access)
→ 8. Hour types (the company's own set, or the standard set) →
9. Agreed-hours patterns → 10. Contracts, once the model meeting has
happened. Every step is idempotent by natural key (name/email), the
way `seed_demo_data` already works — run it twice, get one of each.

## What the seed already proves

`seed_demo_data` builds this exact shape today (company, buildings,
customers, memberships, access rows, patterns, hour types) and is
idempotent against marker drift. The import is that command with a
spreadsheet reader in front of it: the model wiring, the access-row
subtleties (membership + per-building access, H-1 scoping) and the
pattern approval rule (only APPROVED fills the sheet, P-15 0.2) are
all already encoded and tested there.

## Questions for the owner (the handover agenda)

1. In what form does the data exist — spreadsheet, another system's
   export, paper? (Decides whether we write a CSV reader or type it.)
2. Which people get LOGINS at go-live, and which are records only?
   Workers who log hours need accounts; the rest can wait.
3. Do customers get logins in wave one, or does the provider operate
   alone first? (The system supports both; H-6/H-7 gates CCA grants.)
4. Billing day + billing address per customer — the invoice run and
   SEND both need them (billing_address_required is a hard refusal).
5. The email domain question: real addresses from day one (password
   resets go out), or placeholder addresses until people are ready?
6. Which buildings' history (if any) must come along? Recommendation:
   none — start clean, keep the old system read-only for lookback.

## Estimated size

One sprint: a management command (`import_go_live <file>`), dry-run
mode that prints what it WOULD create, per-row error report, and an
idempotency pin. Plus one supervised run against crmtest with the
real file before the production run.
