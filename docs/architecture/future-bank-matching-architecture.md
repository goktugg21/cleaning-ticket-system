# Future architecture — bank-transaction matching

**Status:** PARKED. Schema slot description only. No feature code
ships in Sprint 28. No new columns are added to existing models
today — the placeholder columns described below are added by the
future sprint that ships the matching feature.

**Sources:**

- [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §9.2.
- Backlog row `FUTURE-BANK-MATCHING-1` in
  [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md).

---

## 1. What bank matching means here

The system will eventually receive a feed of incoming bank
transactions (e.g. via a CAMT.053 / MT940 export, or a bank API such
as PSD2 / EquensWorldline) and match them against open receivables
on Proposals (and, later, Subscription executions) to mark them
**paid**.

The product floor (spec §9.2) is:

- Schema needs an `external_reference` / `paid_at` / `paid_amount`
  slot on the receivable side, but the **matching logic** and the
  bank-import integration are out of scope.
- The receivable owner is not yet decided — Proposal vs. spawned
  Ticket vs. Subscription invoice. The future sprint picks one.

---

## 2. Schema shape (placeholder, NOT shipped)

### 2.1. `BankTransaction`

The raw imported row from the bank feed. The "left side" of the
match.

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `external_reference` | char(64) | Stable identifier from the bank export. Most banks include a unique transaction ID per row; use that. |
| `bank_date` | Date | When the bank posted the transaction. |
| `paid_amount` | Decimal(12,2) | Positive for incoming. |
| `paid_at` | DateTime | When the matching engine flipped the receivable to paid. NULL until matched. |
| `payer_name` | char(255) | Free-text counterparty name. |
| `payer_iban` | char(34, nullable) | Counterparty IBAN if the feed exposes it. |
| `reference_text` | char(140) | Free-text "betalingskenmerk" / SEPA remittance info. The matching engine's primary input. |
| `raw_payload` | JSONField | Full bank-row payload as imported. Audit-friendly; never user-edited. |
| `match_status` | TextChoices | `UNMATCHED`, `AUTO_MATCHED`, `MANUAL_MATCHED`, `REJECTED`, `IGNORED`. |
| `match_confidence` | small int (0–100) | Score from the auto-matcher; meaningful only for `AUTO_MATCHED`. |
| `matched_to_type` | char(32, nullable) | `proposal`, `subscription_execution`, etc. Discriminator for the receivable owner. |
| `matched_to_id` | int (nullable) | FK-by-id (no DB constraint — same posture as `audit.AuditLog`). |
| `matched_by` | FK → `accounts.User` (SET_NULL, nullable) | The operator who confirmed a `MANUAL_MATCHED`; NULL for `AUTO_MATCHED`. |
| `matched_at` | DateTime (nullable) | |
| `created_at` / `updated_at` | DateTime | |

**Constraints:**
- `UniqueConstraint(external_reference)` to block double-imports from
  rerun batches.

**Audit:**
- Register in `audit/signals.py` with `_*_TRACKED_FIELDS` covering
  `match_status`, `matched_to_type`, `matched_to_id`, `matched_by_id`.
  The audit trail of a payment-applied event is regulatory-relevant.

### 2.2. Receivable-side placeholder columns

Added on whichever entity owns the receivable. The future sprint
picks one; the placeholder columns are the same shape regardless:

- `external_reference` — `char(64), unique=True, null=True, blank=True`.
  Generated when the invoice is issued. The matching engine searches
  for this string inside `BankTransaction.reference_text`.
- `paid_at` — `DateTime, null=True, blank=True`. Set on a successful
  match.
- `paid_amount` — `Decimal(12,2), null=True, blank=True`. The actual
  amount applied. NULL when unmatched; the receivable's own
  `total_amount` is the *expected* figure.

**Where these columns go in the eventual sprint** — open question
parked below. **The columns do NOT exist today on any model**, and
this doc is not authorising them.

---

## 3. Matching engine (placeholder)

Out of scope for Sprint 28. A future sprint will:

1. Implement an import command `manage.py import_bank_transactions
   <file>` that parses CAMT.053 / MT940 and creates `BankTransaction`
   rows.
2. Implement `extra_work.tasks.match_unmatched_bank_transactions` — a
   Celery task that for each `UNMATCHED` row:
   - Scans `external_reference` strings of open receivables.
   - Scores candidates by amount equality + reference substring match
     + name fuzziness.
   - If a single candidate scores above the auto-match threshold,
     flips both rows atomically (`BankTransaction.match_status =
     AUTO_MATCHED`, `receivable.paid_at = now`, etc.).
   - If multiple candidates or below threshold, leaves
     `UNMATCHED` for manual review.
3. Provider-side review UI `/admin/bank-transactions/` for
   `UNMATCHED` rows — search receivables, click to manually match.

All matching writes go through the audit trail.

---

## 4. API surface placeholder

- `POST /api/bank-transactions/import/` — provider-only multipart
  upload (CAMT.053 / MT940 / CSV); SUPER_ADMIN only.
- `GET /api/bank-transactions/` — paginated list with
  `?match_status=UNMATCHED` default. Provider-only.
- `POST /api/bank-transactions/<id>/match/` — manual match. Body:
  `{ "matched_to_type": "proposal", "matched_to_id": <int> }`.
  Provider-only, audit-tracked.
- `POST /api/bank-transactions/<id>/reject/` — flag a row as not a
  payment (refunds, fees, etc.). Provider-only.

No customer-side surface in v1 — payment status surfaces on the
existing proposal / subscription detail as the existing total +
paid_at field.

---

## 5. Open questions parked for the future sprint

These intentionally do not bind a decision today:

- **Receivable owner.** Today the Proposal is the source of the
  customer-facing total (Sprint 28 Batch 8); the spawned Ticket has
  no money field. Future sprint must decide:
  - Option A — receivable lives on `Proposal` (one invoice per
    proposal, regardless of how many tickets it spawned).
  - Option B — receivable lives on the spawned `Ticket` (one invoice
    per executed line item).
  - Option C — both receivables exist; ticket invoice rolls up to
    proposal totals.

  Option A is cleanest for the customer view; Option B is closer to
  operational reality (some lines may be partial-paid). Pick at the
  matching-feature sprint kick-off.

- **Subscription executions.** Whatever owner is picked above applies
  to subscription executions too (see
  [`future-subscription-architecture.md`](./future-subscription-architecture.md)).

- **Refunds and partial payments.** The placeholder columns assume
  one-shot full payment. `paid_amount < total_amount` is technically
  representable but not semantically defined. Future sprint pins the
  posture (auto-flag for review? track per-installment?).

- **Bank feed source.** CAMT.053 file imports vs. live PSD2 / API
  integration. The schema doesn't care; the import command does.
  Decision deferred.

- **Reconciliation reporting.** "What is unmatched older than 30
  days?" "What's our DSO trend?" These are reports built on top of
  the schema above; not Batch 14 scope.

- **Tax / accounting export.** Out of scope. Bank matching is about
  recognising the payment; downstream accounting export is a
  separate integration.

---

## 6. What this doc explicitly does NOT do

- Does not add `external_reference`, `paid_at`, or `paid_amount` to
  any existing model today. Master plan §2A.9 forbids premature
  columns.
- Does not create a `BankTransaction` model class.
- Does not wire any URL / view / serializer / management command.
- Does not ship a UI surface.

When bank-matching work is scheduled, that future sprint:

1. Picks the receivable owner (see §5 first bullet).
2. Adds the three placeholder columns on the chosen owner model
   (own migration).
3. Lands the `BankTransaction` model class + migration.
4. Registers `BankTransaction` in `audit/signals.py` with
   `_BANK_TRANSACTION_TRACKED_FIELDS` covering match status + match
   target + matched_by.
5. Wires the API surface above with provider-only RBAC.
6. Adds the import management command + the matching Celery task
   + integration tests covering the auto-match / manual-match /
   reject paths and the idempotency lock on `external_reference`.

Until then, this document is the contract.
