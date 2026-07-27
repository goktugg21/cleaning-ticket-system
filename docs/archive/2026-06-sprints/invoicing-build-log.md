> **ARCHIVED — historical.** Describes the system as of 2026-07-20 (the
> subsystem shipped as PR #112, with #113/#114 follow-ups the same week).
> Not maintained; do not rely on it as current truth. **For the current,
> authoritative description of the invoicing subsystem, read
> [`sot-addendum-b-invoicing.md`](../../product/sot-addendum-b-invoicing.md)
> — where it and this build log differ, the addendum (and the code) win.**
> In particular the Phase-2b entries below say numbering was assigned "at
> issue", which is how it shipped then; **PR #113 later moved allocation to
> SEND** — the addendum has the corrected description. Moved out of
> `docs/planning/sprint-checklist.md` in Sprint 122.1.

# Invoicing subsystem — build log (Phases 1–5, `feat/invoicing`)

Multi-phase invoicing build. All phases landed on the ONE branch
`feat/invoicing`; the owner opened ONE PR (#112) after Phase 5, plus
follow-up fixes (#113) and UI polish (#114).

**Phases:**
- [x] **Phase 1 — data model**: `invoicing` app (`Invoice`, `InvoiceLine`) + `Customer` billing-schedule (`invoice_day_rule`, `invoice_granularity_default`) + `Customer.contract_pdf` + numbering scaffolding (`number` NULL-while-draft, `year`, per-company unique). Migrations `invoicing/0001_initial`, `customers/0012`. NO generation/lifecycle/UI/PDF.
- [x] **Phase 2a — unbilled rollup + draft generation + claim/release**: `invoicing/selectors.py::unbilled_extra_work` (Option-1 semantics), `invoicing/services.py::generate_draft_invoices` (per-customer / per-building, claim) + `delete_draft_invoice` (release), legacy mark/clear neutralized to no-ops. NO lifecycle/numbering/reversal/PDF/UI.
- [x] **Phase 2b — lifecycle + numbering + reversal**: `invoicing/state_machine.py` (issue/send/reverse + assert_mutable), `invoicing/numbering.py` (gapless per-company-per-year via `InvoiceNumberSequence`, row-locked), migration `invoicing/0002`. NO PDF/UI.
- [x] **Phase 3 — two-page PDF** (page 1 summary; page 2 detail = EW month / work performed / date): `invoicing/invoice_pdf.py::render_invoice_pdf` + provider-only fetch endpoint `GET /api/invoices/<id>/pdf/`. NO Facturen UI (Phase 4).
- [x] **Phase 4a — invoice REST surface + editable draft + billing-schedule/contract-PDF write** (backend only): the full provider Invoice API (list/due/generate/issue/send/reverse/delete + line add/edit/remove + meta/fee/summary PATCH), editable draft lines with EW-release-on-remove, `Invoice.summary_text` + PDF wiring, recompute-on-edit, `Customer` billing-schedule serializer + contract-PDF upload/serve. Migration `invoicing/0003`. NO frontend.
- [x] **Phase 4b — provider "Facturen" UI** (due panel + invoice list) + the dedicated invoice-detail page (PDF preview + lifecycle + full line editing + editable summary + fee, DRAFT-gated) + the "Facturatie" section on Customer Overview (contract PDF + billing schedule). ALSO removed the legacy Facturen page + the deprecated `/extra-work/mark-invoiced/` + `/clear-invoiced/` no-op endpoints.
- [x] **Phase 5 — customer-portal visibility** (SEND): a CUSTOMER_USER sees their own SENT invoices (read-only) + the PDF, via a SEPARATE membership-level customer scope + redacted serializer + `/api/invoices/my/` read endpoints + a dedicated customer "Facturen" surface.

**LOCKED DECISIONS as originally built (see the addendum for what's current):**
- No contract entity. A contract is just an uploaded PDF on the customer (informational, ZERO behavioral effect). The billing schedule is a simple setting on the customer.
- Invoices sum unbilled EXTRA WORK (Phase 2) + an optional free-text fee (amount + label). No recurring contract-fee amount exists in the system.
- Lifecycle DRAFT → ISSUED → SENT. Numbering was assigned at ISSUE in this original build; **PR #113 later moved it to SEND** (see the addendum). SENT invoices are immutable (reversal only).
- Reversal = auto-generated NEGATIVE counter-invoice, editable, releases the claimed EW back to unbilled (Phase 2 logic). A reversal is TERMINAL (cannot reverse a reversal).
- Draft claims its EW rows on creation; releasing/deleting a draft releases them (Phase 2). Invoice total is the source of truth once issued. Billing-schedule due date is informational (drives the "who's due" list, gates nothing).
- One active contract PDF per customer, replace-on-reupload, no version history.
- Invoice email delivery was deferred at v1: SEND = customer-portal visibility only.

**Phase 2a delivered (2026-07-20):**
- **Unbilled rollup (Option 1):** `unbilled_extra_work(actor, company, customer, year, month, building_id=None)` = earned + in-month EW that is NOT settled — excluded if EITHER `is_invoiced=True` (fast flag; also the legacy M4 bulk-run rows, treated as ALREADY SETTLED so they NEVER resurface) OR claimed by a LIVE (non-soft-deleted) `InvoiceLine`. Reuses `extra_work.billing` (build_ticket_map / is_earned / billing_month) + `scope_extra_work_for` verbatim.
- **Draft generation + claim:** `generate_draft_invoices(...)` creates one draft per customer (building=NULL) or one per building; defaults granularity from `Customer.invoice_granularity_default`; one `InvoiceLine` per EW carrying the EW's EARNED amount (final-with-quoted-fallback, mirroring `reports.dimensions._amounts_for_state`); freezes the invoice subtotal/vat/total; claims each EW atomically (`is_invoiced=True` + live line). Idempotent: a second run finds nothing unbilled → returns `[]` (no empty draft, no double-claim). number/year stay NULL (numbering is Phase 2b).
- **Release on draft delete:** `delete_draft_invoice(...)` soft-deletes the DRAFT and clears `is_invoiced`/`invoiced_at` on its claimed EW → they reappear in the unbilled pool (DRAFT-only; ISSUED/SENT guard is Phase 2b).
- **Legacy mark/clear neutralized:** `/extra-work/mark-invoiced/` + `/clear-invoiced/` are DEPRECATED NO-OPS — keep the route + provider gate + response shape (`{"invoiced_count":0,"ew_ids":[]}` / `{"cleared_count":0,"ew_ids":[]}`), mutate nothing. Endpoints + the old Facturen page are removed together in Phase 4.
- **Assumption:** every `ExtraWorkRequest.building` is NON-nullable/PROTECT → no buildingless / company-wide EW, so per-building generation is clean.

**Phase 2b delivered (2026-07-20):**
- **Lifecycle (forward-only) DRAFT→ISSUED→SENT** in `invoicing/state_machine.py`, mirroring the tickets `@transaction.atomic` + `select_for_update` + locked-status-precondition pattern: `issue_invoice(actor, invoice)` (DRAFT→ISSUED, assigns number+year at the time, stamps issued_at), `send_invoice(actor, invoice)` (ISSUED→SENT, stamps sent_at; portal visibility is Phase 5, email deferred). Provider-operator-gated; forward-only.
- **Gapless numbering** via a DEDICATED `InvoiceNumberSequence` (per-(company, year), unique) locked with `select_for_update` in `numbering.py::allocate_invoice_number(company_id, year) -> (number_str, seq_int)`, format `"YYYY-NNNN"`. Always exactly one row to lock → no empty-set race. Proven gapless + serialized under a real threaded/`TransactionTestCase` concurrency test.
- **ISSUE-YEAR DECISION (as built; later renamed when numbering moved to SEND):** the numbering year is the CURRENT Amsterdam-local calendar year at allocation time (`timezone.localtime(now).year`), NOT the invoice's billing `period_year`.
- **SENT immutability:** `assert_mutable(invoice)` raises on SENT (the future edit path gates on it); `delete_draft_invoice` already rejects any non-DRAFT (ISSUED + SENT). The only SENT mutation is a reversal.
- **Reversal** (`state_machine.py::reverse_invoice`): only a SENT, non-reversal invoice can be reversed (terminal — cannot reverse a reversal). Auto-generates a NEW already-ISSUED counter-invoice (`is_reversal=True`, `reverses=original`, its own number from the same sequence, negated totals + negated mirror lines with `extra_work=NULL` — the counter-entry does NOT re-claim EW). RELEASES the original's EW (clears `is_invoiced`/`invoiced_at`); the original stays SENT on the books (NOT soft-deleted). To make the release actually surface under Option-1, the unbilled selector also ignores claims held by a REVERSED original.

**Phase 3 delivered (2026-07-20):**
- **Two-page Dutch invoice PDF** — `invoicing/invoice_pdf.py::render_invoice_pdf(invoice) -> bytes`, reusing the shared `config.pdf_branding` (Osius logo, embedded DejaVu font with real €, accent rule) and the canonical proposal-PDF formatters so the PDF families cannot drift. **Page 1 = summary** (branded header; number or CONCEPT; klant + optional gebouw; uitgegeven/verzonden dates; periode; a one-line samenvatting; the optional free-text fee; subtotaal/BTW/totaal). **Page 2 = itemized detail** — one width-safe row per line with EW-maand / uitgevoerd werk / datum + aantal / eenheidsprijs / BTW% / subtotaal / BTW / totaal, and a totals footer.
- **DRAFT marker:** while DRAFT, "CONCEPT" shows in the number slot + a prominent page-1 banner + a per-page header band; ISSUED/SENT show the real number and no marker.
- **Reversal:** titled **"Creditnota"**; amounts already negative in the data render negative.
- **Fetch endpoint:** `GET /api/invoices/<id>/pdf/` (`invoicing/urls.py`), provider-operator only + tenant-scoped via `selectors.scope_invoices_for`: 200 `application/pdf` inline for an in-scope operator, 403 for a customer/staff, 404 cross-tenant. Customer visibility is Phase 5.

**Phase 4a delivered (2026-07-20) — backend only (the Facturen UI is Phase 4b):**
- **Editable draft (source-of-truth recompute):** `Invoice.summary_text` (nullable-blank `TextField`, migration `invoicing/0003`) for Ramazan's hand-written page-1 samenvatting — the two-page PDF prefers it when non-empty, else the auto-composed line. `services.recompute_invoice_totals(invoice)` re-derives the frozen subtotal/vat/total from the LIVE lines + the optional fee after any edit. **Fee-VAT decision:** the optional fee is a VAT-exempt (0% BTW) additional post.
- **Line + meta services** (`invoicing/line_services.py`, DRAFT-only; provider-operator-gated): `add_invoice_line`, `update_invoice_line` (both origins, an EW-linked line's amount is editable IN PLACE, the claim survives), `remove_invoice_line` (if EW-linked, releases the EW back to unbilled before deleting), `update_invoice_meta`. Every mutation recomputes the invoice totals.
- **Invoice REST surface** (`invoicing/serializers.py` + `invoicing/filters.py` + `invoicing/views.py::InvoiceViewSet`, wired via a `DefaultRouter`). All endpoints provider-operator-gated + tenant-scoped via `scope_invoices_for`.
- **"Who's due" (`GET /api/invoices/due/`) — informational, gates NOTHING:** for every ACTIVE, in-scope customer with a billing schedule set, reports the unbilled EW count + total for the CURRENT Amsterdam-local period, plus `is_due` — a soft hint (this is the endpoint whose current-month-only anchor was later fixed — see [`sot-addendum-b-invoicing.md`](../../product/sot-addendum-b-invoicing.md) §B.10).
- **Customer billing-schedule + contract-PDF write:** `CustomerSerializer` exposes `invoice_day_rule` + `invoice_granularity_default` as writable + a read-only `contract_pdf_url`. Contract PDF endpoints mirror the customer logo. One active PDF, replace-on-reupload.
- **Tests:** invoicing suite 115 green (24 line-service + 25 HTTP added); customers Part-D 13 green.

**Phase 4b delivered (2026-07-20) — frontend + a small backend removal:**
- **`frontend/src/api/invoices.ts`** — thin axios wrappers 1:1 with the Phase-4a `InvoiceViewSet`. `types.ts` gained `Invoice` / `InvoiceLine` / `InvoiceDueRow` + status/granularity/day-rule enums.
- **Facturen page** (`pages/FacturenPage.tsx`, replacing the deleted `InvoicesPage`): a "Due now / upcoming" panel + the full invoice list (customer/building/status/period filters).
- **Invoice-detail page** (`pages/InvoiceDetailPage.tsx`): the two-page PDF preview, lifecycle buttons gated by status, and — WHILE DRAFT ONLY — full line editing, the editable page-1 summary, and the fee box.
- **"Facturatie" section on Customer Overview**: billing-schedule settings + contract PDF upload/view/replace/remove.
- **Legacy retirement:** removed the `mark_invoiced` / `clear_invoiced` ViewSet actions from `extra_work/views.py`, the matching frontend helpers, and the old `InvoicesPage.tsx`.
- **Verification:** FE gate green; backend `extra_work` + `audit` suites green (806 tests, OK). MEASURED smoke (vite-preview + dev-backend + token-inject).

**Phase 5 delivered (2026-07-20) — customer-portal visibility (FINAL phase):**
- **Customer scope (SEPARATE from the provider scope):** `selectors.scope_customer_invoices_for(user)` — MEMBERSHIP-level via `CustomerUserMembership`, `status == SENT`, `deleted_at IS NULL`. The provider `scope_invoices_for` is UNCHANGED.
- **Three HARD INVARIANTS** baked into the scope + tested: SENT-only; own-customer(s) only; never a soft-deleted invoice.
- **Redacted serializer:** `CustomerInvoiceSerializer` + `CustomerInvoiceLineSerializer` drop the provider-internal fields — invoice `company` / `customer` / `year` / `reverses` / timestamps; line `extra_work` (the key redaction) / `id` / `ordering` / timestamps.
- **Customer read endpoints:** `GET /api/invoices/my/`, `GET /api/invoices/my/<id>/`, `GET /api/invoices/my/<id>/pdf/` (reuses `render_invoice_pdf`). Every one scopes through `scope_customer_invoices_for`.
- **Customer "Facturen" surface:** `pages/MyInvoicesPage.tsx` + `pages/MyInvoiceDetailPage.tsx` (read-only). `components/CustomerRoute.tsx` admits only CUSTOMER_USER.
- **Verification:** invoicing suite green (131 tests, OK); FE gate green; no migration.
