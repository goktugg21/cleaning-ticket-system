# A3 - The Extra Work <-> Invoice Seam (Osius reference system)

Scope: the JOIN between a work and its invoice. Not the extra-work workflow (A1),
not the invoice UI (A2). Read-only investigation of `/tmp/osius-ref/backend`,
`/tmp/osius-ref/frontend`, and GET-only calls against the live dev API.

Vocabulary note: their **Product** (`extra_work_products`, `CustomerProduct`) is our
**Service**. Every place it meets money is flagged with **[PRODUCT=SERVICE]**.

---

## 1. PLAIN-ENGLISH LOGIC

### 1.1 There are three separate, unconnected "invoiced" mechanisms

This is the single most important fact about this area. The system does not have one
extra-work-to-invoice path. It has three, built at different times, and they do not
know about each other.

**Path A - the live one: `extra_works` -> `invoice_items` -> `invoices`.**
A human filters the extra-work list down to status 8 (Completed), ticks the works they
want, types or accepts an auto-generated invoice number, picks an invoice date, and
presses a button. The server creates one invoice and one invoice line per work, and
stamps every one of those works to status 9 (Gefactureerd). This is the only path with
real data in it: 3 invoices, 31 works.

**Path B - the newer one: `extra_works_v2` -> `invoiceable_items` -> `extra_work_v2_invoices`.**
A "billing configuration" on a V2 work (fixed price / monthly / installments) generates
rows in a staging table called `invoiceable_items`, each with a period and a scheduled
date. A separate screen turns a selection of those staging rows into an invoice.
In live data this path has produced **zero** extra-work staging rows; the only 13
staging rows that exist are of type `project`, and the one V2 invoice that exists has
**no link at all** back to its staging rows.

**Path C - a flag with no invoice behind it: `extra_work_v2_period_products.invoice_number`.**
An endpoint marks a V2 period "invoiced" by writing a free-text invoice number string
onto product rows. There is no foreign key. Nothing checks that the string corresponds
to an invoice that exists.

Everything below is about Path A unless stated, because Path A is the one that has
actually billed customers.

### 1.2 How a work becomes invoiced (Path A), in plain English

Nothing happens by itself. A person opens the extra-work list, switches it to the
"ready to invoice" view, and the browser asks the server for works at status 8. The
browser groups them by customer / building / department / work type, adds up the money
in the browser, and shows the operator a preview with a total.

The operator then presses "invoice". At that moment the **browser** invents the invoice
number - the server never generates one for this path - and sends the server a list of
work IDs, a customer, an optional building, a date, and a note.

The server creates the invoice as a `draft` with zero totals, then loops the works. For
each work it writes one invoice line carrying the work's product money, hard-codes the
VAT rate at 21%, hard-codes quantity 1 and unit "stuks", and flips the work to status 9.
Then it re-adds the lines to get the invoice totals and commits.

From that moment the work disappears from every default list in the system, because the
extra-work list treats status 9 like a soft delete unless you explicitly ask for it.

Sending the invoice generates a PDF and flips the invoice to `sent`. Nothing about the
works changes when an invoice is sent - the works were already at 9 the moment the
invoice was *created*, while it was still a draft.

### 1.3 The link between a work and its invoice is one-directional

There is a column `extra_works.invoice_id`. It looks like the forward link. It is not.
**In live data it is NULL on every single one of the 37 works that are at status 9.**

The reason is a straightforward asymmetry in the code: the bulk-create path never
writes it, but four different delete/revert paths clear it, and one rarely used
single-item "add" path is the only thing that ever sets it. So the column can only ever
be non-null for a work that was added to an already-existing draft invoice one at a
time, and no such work exists in this environment.

The link that actually works is the reverse one: `invoice_items.extra_work_id`. Every
read that needs to get from a work to its invoice - the list column, the sort, the date
filter, the detail panel - goes through `invoice_items`, never through
`extra_works.invoice_id`.

`extra_works.invoice_date` is in the same state: written by only the one rarely used
path, and read by nothing. When a screen says "invoice date" it means
`invoices.invoice_date` reached through the join.

### 1.4 There is no period. At all.

The question "which date decides which period a work lands in" has an uncomfortable
answer for Path A: **no date does, because there is no period.**

`invoices.period_start` and `invoices.period_end` exist as columns. They are never
written by any creation path - the only way to fill them is a human doing a manual PUT
on a draft invoice. All three invoices in live data have them NULL. The only thing that
reads them is the PDF template, and when they are NULL (always) the template silently
falls back to printing the month name of `invoice_date`.

So the "period" a customer sees on the invoice is derived from the date the operator
picked in the modal, and has no relationship to when the work was actually done. A
work completed in November 2025 sits on an invoice dated 5 May 2026, and the PDF will
say "mei 2026".

Which works land together is decided **entirely by the operator's manual selection** in
the browser. There is no server-side rule, no cutoff query, no date window.

The V2 path (Path B) is the only place a real period exists: `BillingService` writes
`period_start` / `period_end` / `scheduled_date` onto each staging row from the work's
`billing_start_date`, `billing_end_date` and `billing_day`. But no extra-work staging
rows exist in live data.

### 1.5 Nothing is automatic. There is no scheduler.

This is a finding, and a firm one. The application has **no task scheduler defined at
all**. Laravel 11 puts the schedule in `routes/console.php` or a `withSchedule()` call
in `bootstrap/app.php`. Neither exists. `routes/console.php` contains the stock
`inspire` command and nothing else. There is no `app/Console/Kernel.php`.

There are three console commands, none billing-related. There are three queued jobs, all
of them auto-translation. There are seven observers, and the extra-work observer touches
activity logging and translation only - it never looks at invoicing.

The consequence: `ExtraWorkV2InvoiceService::checkOverdueInvoices()` exists, is written
correctly, and **is called by nobody**. No route, no controller, no command, no
schedule. The `overdue` invoice status therefore can never be reached in the V2 system.
Invoices sit at `sent` past their due date forever.

### 1.6 Cutoff, grace period, overdue

- **Invoice due date, Path A**: `invoices.due_date` is never set on creation and is NULL
  in all live data. The PDF prints a due date anyway, computed at render time as
  `invoice_date + 1 month`. The payment term is therefore a hardcoded constant inside a
  Blade template, not data.
- **Overdue works bucket**: there is one, server-side, but it is for staging rows and
  not for works. Two implementations exist with the same rule (`scheduled_date` earlier
  than the first day of the current month = overdue) and they disagree on the null case:
  one treats a null scheduled date as current, the other excludes it from both buckets.
  Live data: all 13 staging rows have `scheduled_date` NULL, so both bucket counts are
  effectively zero.
- **Overdue invoices**: dead code, see 1.5.
- **No cutoff or lock exists anywhere.** Nothing prevents invoicing a work completed
  two years ago into today's invoice.

### 1.7 What happens to an invoiced work if it is rejected, cancelled or reverted

Following the code rather than the UI, there are five doors out of status 9, and they
behave completely differently.

| Door | Guard | Effect on the work | Effect on the invoice |
|---|---|---|---|
| Delete the invoice | draft only | back to status 8, links cleared | invoice hard-deleted |
| Remove one work from the invoice | draft only | back to status 8, links cleared | line hard-deleted; empty invoice auto-deleted |
| Delete one invoice line | draft only | back to status 8, links cleared | as above |
| Mark invoice cancelled | sent only | **NOTHING** | invoice cancelled |
| `PUT /extra-works/{id}/status` | **none** | any status you like | **NOTHING** |

The last two rows are the problem.

**Cancelling a sent invoice orphans its works permanently.** The cancel handler updates
the invoice row and nothing else. The works stay at status 9 with their invoice lines
still pointing at a cancelled invoice. They will never appear in the status-8 "ready to
invoice" list again, so they can never be re-billed through the UI. The money is simply
lost. (Note the V2 system got this right - its cancel path does release its items. The
live system does not.)

**The generic status endpoint has no invoice guard whatsoever.** It validates only that
the target status exists in the status table. A work at status 9 can be moved to any
status by anyone with the permission, and the invoice is not touched: the line stays,
the amount stays, the invoice total stays. The invoice goes stale and there is no
detection. In the opposite direction, a work can be pushed *to* status 9 with no invoice
behind it at all - and live data shows **six works in exactly that state**
(476, 444, 440, 439, 438, 437: status 9, no invoice line, no invoice). Three of them
even carry an `invoice_date` with no invoice.

The bulk group-status endpoint is worse still: it does a raw mass `update()` on a whole
group with no status validation, no invoice check, and because a mass update bypasses
Eloquent events, no activity log entry either.

### 1.8 Where Product (= our Service) meets money, and gets it wrong

**[PRODUCT=SERVICE] The per-product VAT rate is thrown away.** Each
`extra_work_products` row carries its own `tax_rate` (9%, 21%, 0%). When the work is
invoiced, the invoice line is written with a hard-coded `0.21`. This is not theoretical:
extra work 448 has a product at **9.00%**, and its invoice line (item 413 on invoice
INV-202605-0003, an already-**sent** invoice) records **0.2100**. The customer was
charged 21% VAT on a 9% line. The PDF's VAT breakdown groups by the invoice line rate,
so it prints a single clean 21% block and the error is invisible on the document.

**[PRODUCT=SERVICE] The unit and quantity are lost.** The code reads
`$firstProduct->pivot->quantity` and `$firstProduct->unit->label_nl`, but `products()`
is a `hasMany`, so there is no `pivot`, and `unit` is a plain string column, not the
`productUnit` relation. Both expressions evaluate to null and fall through to the
defaults. Every invoice line in live data is `quantity 1.00, unit "stuks"` - including
lines whose underlying product is priced per **Uur** (hour) or **Per beurt** (per visit).
The money is still right (the amount is the pre-multiplied product total), but the
document misrepresents what was sold.

**[PRODUCT=SERVICE] Labour never reaches an invoice.** The invoice line amount is
`total_products_cost` - products only. The comment in the code says so explicitly.
`ExtraWorkEmployeeHour.total_cost`, surfaced as `total_labor_cost` and shown on the
work's own screens, is never billed by any path.

**Only the first product survives.** A work with three products becomes one invoice line
whose description is the work title and whose unit/quantity come from product #1. The
individual products are not itemised on the invoice.

**The browser and the server compute different totals.** The preview modal sums real
per-product VAT (`total_with_tax - total_subtotal`). The server applies flat 21%. On any
work with a non-21% product the number the operator approves is not the number that gets
invoiced.

### 1.9 Invoice numbering is client-side and unsafe

For Path A the server *requires* `invoice_number` in the request and only checks it is
unique. The browser generates it: `INV-YYYYMM-0001` incrementing in a loop for bulk-all,
or `INV-YYYYMMDD-` plus a **random 4-digit number** for single bulk. Two operators
working simultaneously will collide or leave gaps, and there is no gapless guarantee.
The server *does* have a proper `generateInvoiceNumber()` producing `INV-YYYY-NNNN`, but
it is only used by the invoiceable-items path - which is why the three live invoices are
numbered `INV-202605-000N`, a format the server generator cannot produce.

---

## 2. EVIDENCE - READ / WRITE MAPS

### 2.1 `extra_works.invoice_id`

- **NAME** `extra_works.invoice_id`
- **WRITTEN BY**
  - `InvoiceController::addItem` - CODE `app/Http/Controllers/Admin/InvoiceController.php:619`
    `'invoice_id' => $invoice->id,` (the ONLY setter)
  - Cleared to NULL by `destroy` (CODE `:269`), `removeExtraWork` (CODE `:725`),
    `deleteItem` (CODE `:787`)
  - **NOT written by** `InvoiceController::store` - CODE `:142-152` creates the
    `InvoiceItem` and then only `$work->update(['status_id' => 9]);` (CODE `:152`)
- **READ BY** nothing in application code. Referenced only inside a DB view definition:
  CODE `database/migrations/2025_12_09_031108_fix_portal_extra_works_view_category_name.php:87`
  `ew.invoice_id,`. Model relations use `invoice_items` instead:
  CODE `app/Models/ExtraWork.php:344`
  `return $this->hasOneThrough(Invoice::class, InvoiceItem::class, 'extra_work_id', 'id', 'id', 'invoice_id');`
- **IF NULL/EMPTY** no effect - every consumer goes through `invoice_items`.
- **GATES** nothing.
- **DEAD?** **Effectively DEAD.** DATA: `GET /admin/extra-works?statuses=9&per_page=100`
  returned 37 rows, `invoice_id` NULL on **37/37**, including all 31 that demonstrably
  sit on an invoice.

### 2.2 `extra_works.invoice_date`

- **WRITTEN BY** `InvoiceController::addItem` only - CODE `:620` `'invoice_date' => now(),`.
  Cleared by `destroy` `:270`, `removeExtraWork` `:726`, `deleteItem` `:788`.
- **READ BY** nothing. The `invoice_date` sort and filter in the extra-work list both
  resolve to the *invoice* table:
  - CODE `app/Http/Controllers/Admin/ExtraWorksController.php:231-233`
    `elseif ($dateField === 'invoice_date') { $query->whereHas('invoice', function($q) ... $q->whereBetween('invoice_date', [$dateStart, $dateEnd]); }`
  - CODE `:303` `"(SELECT i.invoice_date FROM invoices i JOIN invoice_items ii ON ii.invoice_id = i.id WHERE ii.extra_work_id = extra_works.id LIMIT 1) $sortOrder"`
- **DEAD?** **DEAD as a read source.** DATA: of 37 status-9 works, 34 have it NULL; the
  3 that have it (`437`, `438`, `444`, value `2025-11-30`) have **no invoice line and no
  invoice**, i.e. the value is stale garbage.

### 2.3 `invoice_items.extra_work_id` - the real link

- **WRITTEN BY**
  - `InvoiceController::store` - CODE `:141` `'extra_work_id' => $work->id,`
  - `InvoiceController::addItem` - CODE `:608` `'extra_work_id' => $extraWork->id,`
  - Made nullable by CODE `database/migrations/2026_02_23_110000_make_extra_work_id_nullable_in_invoice_items.php:15`
    so invoiceable-item lines can omit it.
- **READ BY**
  - `ExtraWork::invoiceItem()` - CODE `app/Models/ExtraWork.php:337-340` `hasOne(InvoiceItem::class)`
  - `ExtraWork::invoice()` hasOneThrough - CODE `:344`
  - `Invoice::extraWorks()` hasManyThrough - CODE `app/Models/Invoice.php:88`
  - `pendingExtraWorks` availability filter - CODE `InvoiceController.php:308`
    `->whereDoesntHave('invoiceItem'); // Not yet in any invoice`
  - the sort subquery and the date filter above
  - PDF: eager-loaded as `items.extraWork.products.productUnit` - CODE `InvoiceController.php:338`
- **IF NULL/EMPTY** the line is an invoiceable-item line or an installment summary line;
  `Invoice::extraWorks()` and the sort subquery simply skip it.
- **GATES** yes - it is the sole gate keeping a work out of the "ready to invoice" list
  (`whereDoesntHave('invoiceItem')`).
- **DEAD?** No. Live and load-bearing. DATA: `GET /admin/invoices?per_page=100` -> 31
  distinct `extra_work_id` values across 3 invoices; 0 works appear on more than one
  invoice.

### 2.4 `invoice_items.tax_rate` - the VAT loss

- **WRITTEN BY** `InvoiceController::store` CODE `:143` `'tax_rate' => 0.21, // Default 21% KDV`
  and `addItem` CODE `:610` (identical hard-coded literal). The
  `createInvoiceFromItems` path is the only one that carries a real rate:
  CODE `:1204` `'tax_rate' => ($itemData['tax_rate'] ?? 21) / 100,`
- **READ BY** `recalculateInvoiceTotals` CODE `:1035`; the PDF `resources/views/pdf/invoice-vertical.blade.php:478`
  `$itemTaxRate = floatval($item->tax_rate ?? 0.21);` and the BTW breakdown block at `:533`.
- **THE SOURCE IT IGNORES** `extra_work_products.tax_rate`, a real per-product column
  (CODE `app/Models/ExtraWorkProduct.php:18,30`) with a real accessor
  CODE `:85-88` `getTaxAmountAttribute(): return round($this->subtotal * ($this->tax_rate / 100), 2);`
- **EVIDENCE OF HARM** DATA, `GET /admin/invoices/89` (status **sent**):
  `item 413, extra_work_id 448, amount 30.12, tax_rate "0.2100"` while that work's
  product reads `('30.12', '1.00', '9.00', 'Uur')` - product VAT **9%**, invoiced at 21%.
  Invoice totals `subtotal 542.16 / tax 113.85` and `542.16 * 0.21 = 113.85` exactly,
  confirming a single flat rate across the whole document.
- **GATES** changes the price. Yes.

### 2.5 `invoice_items.quantity` / `unit_name`

- **WRITTEN BY** CODE `InvoiceController.php:132-139`:
  ```php
  $quantity = 1.00; $unitName = 'stuks';
  if ($work->products && $work->products->isNotEmpty()) {
      $firstProduct = $work->products->first();
      $quantity = floatval($firstProduct->pivot->quantity ?? 1);
      if ($firstProduct->unit) { $unitName = $firstProduct->unit->label_nl ?? $firstProduct->unit->label_en ?? 'stuks'; }
  }
  ```
  `products()` is CODE `app/Models/ExtraWork.php:280` `hasMany(ExtraWorkProduct::class, 'extra_work_id')`
  - a `hasMany` has **no `pivot`**. `unit` is a plain fillable string column
  (CODE `ExtraWorkProduct.php:22`, also in `$hidden` at `:46` with the comment
  "Use unit_name instead (derived from productUnit->label)"); the relation is named
  `productUnit()` (CODE `:67`). Both expressions therefore fall through to the defaults.
- **READ BY** `recalculateInvoiceTotals` CODE `:1030` (`subtotal = amount * quantity`);
  PDF CODE `invoice-vertical.blade.php:497-512`.
- **EVIDENCE** DATA, invoice 89: **all 21 lines** are `qty 1.00, unit "stuks"`, while the
  underlying products are `Per beurt` and `Uur`.
- **NOTE** the PDF repeats the same broken pivot access as a fallback:
  CODE `invoice-vertical.blade.php:502` `if (!$item->quantity) { $quantity = floatval($firstProduct->pivot->quantity ?? 1); }`
- INFERRED: because `quantity` is always 1, the `amount * quantity` multiplication in
  `recalculateInvoiceTotals` is currently harmless; if the pivot bug were "fixed" without
  also changing `amount` (which is already `sum(price*qty)` via
  CODE `ExtraWorkProduct.php:80-83`), every multi-quantity line would be double-counted.
  Confirmation would need a work whose product quantity is > 1 - none exists in live data.

### 2.6 `invoices.period_start` / `period_end`

- **WRITTEN BY** only `InvoiceController::update` - CODE `:236` in the `$request->only([...])`
  whitelist, guarded to draft invoices only (`:196`). **No creation path sets them**:
  `store` (`:113-123`), `createInvoiceFromItems` (`:1177-1190`) and
  `createInstallmentInvoices` (`:1283-1297`) all omit them.
- **READ BY** the PDF only:
  - CODE `invoice-vertical.blade.php:342-345`
    `if ($invoice->period_start && $invoice->period_end) { $periodStr = ...format('d M Y') ... } elseif ($invoice->invoice_date) { $periodStr = Carbon::parse($invoice->invoice_date)->isoFormat('MMMM YYYY'); }`
  - CODE `:424-426` a conditional "Periode: ... t/m ..." banner
- **IF NULL/EMPTY** the PDF silently substitutes the **month of `invoice_date`**. No
  warning, no blank.
- **DEAD?** **DEAD in practice on the extra-work path.** DATA: all 3 invoices return
  `period_start: null, period_end: null`. Only a human editing a draft can populate them.
- **GATES** changes what the PDF prints. Nothing else.

### 2.7 `invoices.due_date`

- **WRITTEN BY** `createInvoiceFromItems` CODE `:1184` and `createInstallmentInvoices`
  CODE `:1288` (invoiceable-items path). **Not** by `store` (extra-work path).
- **READ BY** PDF CODE `invoice-vertical.blade.php:293`
  `{{ \Carbon\Carbon::parse($invoice->invoice_date)->addMonth()->format('d.m.Y') }}`
  - note this **ignores the column entirely** and always prints invoice_date + 1 month.
- **DATA** all 3 live invoices: `due_date: null`.
- **Finding**: the payment term for Path A is a hardcoded `+1 month` in a Blade template.

### 2.8 `invoiceable_items.invoice_id` and `invoiced_at`

- **`invoice_id` WRITTEN BY** nobody. Grep of `app/` finds `invoice_id` on this model
  only in `$fillable` (CODE `app/Models/InvoiceableItem.php:33`) and as a **read**
  (CODE `app/Http/Controllers/Admin/ExtraWorksV2Controller.php:6042`
  `'invoice_id' => $item->invoice_id,`). Every creation path writes `status` instead:
  CODE `InvoiceController.php:1194` `->update(['status' => InvoiceableItem::STATUS_INVOICE_DRAFT]);`
  and CODE `ExtraWorkV2InvoiceService.php:113-115` the same.
- **DEAD?** **DEAD.** DATA: `GET /admin/invoiceable-items?per_page=200` -> 13 rows,
  `invoice_id` set on **0/13**.
- **`invoiced_at` WRITTEN BY** CODE `ExtraWorkV2InvoiceService.php:248` only, inside the
  sent/paid branch of `updateStatus`. **READ BY** CODE `ExtraWorksV2Controller.php:6043`
  (display only). DATA: set on **0/13** live rows.
- The real state machine for a staging row is the `status` string:
  `draft -> ready -> invoice_draft -> invoiced`, plus `cancelled`
  (CODE `InvoiceableItem.php:74-78`).

### 2.9 `extra_work_v2_invoice_items.invoiceable_item_id` - the V2 reverse link

- **WRITTEN BY** `ExtraWorkV2InvoiceItem::createFromInvoiceableItem` CODE
  `app/Models/ExtraWorkV2InvoiceItem.php:169` `'invoiceable_item_id' => $invoiceableItem->id,`
- **READ BY** release-on-cancel CODE `ExtraWorkV2InvoiceService.php:239-246`, delete
  CODE `:365-370`, mark-invoiced CODE `:240-250`, and
  `ExtraWorkV2Invoice::markAsCancelled` CODE `app/Models/ExtraWorkV2Invoice.php:232-235`.
- **IF NULL** the line is a manually added item; every release path skips it, so it can
  never be traced to a source work.
- **DATA** the single live V2 invoice `EWV2-2026-0004` has 3 items, `invoiceable_item_id`
  NULL on **3/3** - yet their descriptions read `"Maandelijkse facturatie - vanuit inkomsten"`,
  which is the literal string authored by
  CODE `app/Services/BillingService.php:380` `'description' => 'Maandelijkse facturatie - vanuit inkomsten',`.
  So the lines demonstrably originated from `BillingService`-generated staging rows, but
  the FK is empty. Either the staging rows were later deleted, or a copy path wrote the
  fields without the link. **The reverse link does not exist in any live V2 row.**

### 2.10 The invoiced status flag on the work

- **`extra_works.status_id = 9` WRITTEN BY** exactly two lines:
  CODE `InvoiceController.php:152` `$work->update(['status_id' => 9]);` (bulk create) and
  CODE `:618` `'status_id' => 9,` (add single item). Grep across `app/` finds no third
  setter of the literal.
- Reverted to `8` by CODE `:266` (destroy), `:724` (removeExtraWork), `:785` (deleteItem).
- **GATES, heavily**:
  - it is the *only* thing hiding invoiced works from every default list -
    CODE `ExtraWorksController.php:~250`
    `// EXCLUDE: Status 9 (Invoiced) ... $query->where('status_id', '!=', 9);`
    with the comment "If statuses parameter is not provided, treat status 9 like soft-deleted records"
  - it triggers the invoice eager-load: CODE `ExtraWorksController.php:141-143`
    `if (in_array(9, $statusIds)) { $query->with(['invoiceItem', 'invoice:invoices.id,invoice_number,status,notes,invoice_date']); }`
  - it blocks re-adding: CODE `InvoiceController.php:587`
    `if ($extraWork->status_id === 9) { ... 'This extra work is already invoiced' }` (in
    `addItem` **only** - `store` has no such check)
- **UNGUARDED WRITERS** CODE `ExtraWorksController.php:3625-3635`:
  ```php
  $validated = $request->validate(['status_id' => 'required|exists:t_ticket_status,id', ...]);
  $extraWork = ExtraWork::findOrFail($id);
  $extraWork->status_id = $validated['status_id'];
  ```
  No invoice check anywhere in the method. And
  CODE `ExtraWorksController.php:6254` `$updatedCount = $query->update(['status_id' => $newStatusId]);`
  - a mass update, no status validation at all, and it bypasses model events (so no
  `ExtraWorkObserver::updated`, no `ExtraWorkActivityLogger::logStatusChange`).
- **EVIDENCE OF DRIFT** DATA: works `476, 444, 440, 439, 438, 437` are at status 9 with
  `invoice_item: false` and `invoice: false` - 6 of 37 (16%) are marked billed with no
  invoice behind them.

### 2.11 Scheduler / jobs / observers - the automation audit

- CODE `bootstrap/app.php:24-30`:
  ```php
  return Application::configure(basePath: dirname(__DIR__))
      ->withRouting(web: ..., api: ..., commands: __DIR__.'/../routes/console.php', health: '/up',)
  ```
  No `->withSchedule(...)`. No `app/Console/Kernel.php` (confirmed absent).
- CODE `routes/console.php` in full is the stock `inspire` command. Grep for
  `->daily|->cron|->everyMinute|withSchedule` across `app/`, `routes/`, `bootstrap/`
  returns **no scheduling call anywhere** (only unrelated matches on the word
  "reschedule" and "scheduled_entries").
- `app/Console/Commands/`: `ProcessIncomingMail.php`, `RecalculateGradesScores.php`,
  `VerifyInspectionScore.php` - none billing-related, and none scheduled.
- `app/Jobs/`: `AutoTranslateCommentJob`, `AutoTranslateExtraWorkJob`, `AutoTranslateJob`
  - translation only.
- `app/Observers/ExtraWorkObserver.php`: `created` -> activity log + translation;
  `updated` -> activity log over `$importantFields` (CODE `:33-49`, which includes
  `status_id` but **not** `invoice_id`). Nothing invoicing-related.
- **DEAD CODE PROVEN**: `ExtraWorkV2InvoiceService::checkOverdueInvoices()`
  (CODE `:383-397`) and `ExtraWorkV2Invoice::checkOverdue()` (CODE
  `app/Models/ExtraWorkV2Invoice.php:246-258`) - grep across `app/` and `routes/` finds
  no caller; `grep -n "checkOverdue" ExtraWorkV2InvoiceController.php` returns nothing.
  The `overdue` status (CODE `ExtraWorkV2Invoice.php:25`) is therefore unreachable.
- `ExtraWorkV2Invoice::boot()` has a `saved` hook whose body is a comment only:
  CODE `:96-98` `static::saved(function ($invoice) { // Totals are recalculated via service when items are modified });`

### 2.12 The overdue bucket (works side)

Two implementations, both server-side, both by `scheduled_date` month:

- CODE `InvoiceController::getInvoiceableItemsForCustomer:1360-1378`
  ```php
  $currentMonth = $now->format('Y-m');
  $currentItems = $items->filter(function ($item) use ($currentMonth) {
      if (!$item->scheduled_date) { return true; }
      return $item->scheduled_date->format('Y-m') >= $currentMonth; });
  $overdueItems = $items->filter(... if (!$item->scheduled_date) { return false; } ...);
  ```
  Null scheduled date -> **current**.
- CODE `ExtraWorkV2InvoiceService::getInvoiceableItems:33-64`
  ```php
  $items = (clone $baseQuery)->where(function ($q) use ($startOfMonth, $endOfMonth) {
      $q->whereNull('scheduled_date')->orWhereBetween('scheduled_date', [$startOfMonth, $endOfMonth]); })
  $overdueItems = (clone $baseQuery)->whereNotNull('scheduled_date')->where('scheduled_date', '<', $startOfMonth)
  ```
  Note: the "current" bucket here is *only* the current month, so a **future**-scheduled
  item appears in neither bucket and is invisible on that screen.
- Both are computed server-side and returned as `overdue_count`. Neither writes anything.
- DATA: all 13 live staging rows have `scheduled_date: null` -> `overdue_count` 0 in both.

### 2.13 Where the period is actually computed (V2 only)

CODE `app/Services/BillingService.php:337-399`, `createMonthlyInvoicesFromAmount`:
```php
$startDate = $work->billing_start_date ?? $work->start_date ?? now();
$endDate   = $work->billing_end_date ?? $work->end_date ?? Carbon::parse($startDate)->addMonths(12);
$billingDay = $work->billing_day ?? 1;
...
$periodStart = $currentMonth->copy()->day(min($billingDay, $currentMonth->daysInMonth));
$periodEnd   = $currentMonth->copy()->endOfMonth();
... InvoiceableItem::create([... 'period_start' => $periodStart, 'period_end' => $periodEnd,
    'scheduled_date' => $periodStart, 'tax_rate' => 21, ...]);
```
So on the V2 path the period comes from the work's **billing configuration**, not from
any work-execution date (not `completed_at`, not `customer_start_date`). `tax_rate` is
again a hard-coded `21`. **[PRODUCT=SERVICE]**

### 2.14 Path C - the flag with no invoice

CODE `app/Http/Controllers/Admin/ExtraWorksV2Controller.php:5236-5252`
(`PUT /extra-works-v2/{id}/periods/{periodId}/mark-invoiced`):
```php
$query->update(['is_invoiced' => true, 'invoiced_at' => now(),
                'invoice_number' => $validated['invoice_number'] ?? null,]);
$period->update(['status_id' => 7, ...]);
```
`invoice_number` is `nullable|string|max:100` - a free string with no FK, no existence
check, no uniqueness. A period can be marked invoiced with `invoice_number = null`.

### 2.15 Invoice numbering

- Path A: CODE `InvoiceController::store:90` `'invoice_number' => 'required|string|unique:invoices,invoice_number',`
  - the client must supply it.
  - CODE `frontend/src/pages/finalosius/extra-works/modals/ExtraWorkBulkAllInvoiceModal.jsx:104`
    ``const prefix = `INV-${format(today, 'yyyyMM')}`;`` + `:73-77` pad an incrementing index.
  - CODE `frontend/src/pages/finalosius/extra-works/modals/ExtraWorkBulkInvoiceModal.jsx:120-122`
    ``const randomNum = Math.floor(1000 + Math.random() * 9000); setInvoiceNumber(`INV-${dateStr}-${randomNum}`);``
- Server generator (invoiceable-items path only): CODE `InvoiceController.php:1321-1341`,
  format `INV-{YYYY}-{NNNN}`, `orderByDesc('invoice_number')` string sort - which breaks
  ordering once the counter passes 9999 or when a `-1/3` installment suffix is present
  (CODE `:1272` `$invoiceNumber = "{$baseInvoiceNumber}-{$i}/{$installments}";`).
- V2 generator: CODE `ExtraWorkV2Invoice::generateInvoiceNumber:105-124`, `EWV2-{YYYY}-{NNNN}`,
  numeric sort with `withTrashed()` - the only correctly gapless-safe one of the three.
- DATA: live invoice numbers are `INV-202605-0001/0002/0003` - the client format,
  confirming Path A is what produced them.

### 2.16 The V1 vs V2 invoice tables side by side

| | Path A (live) | Path B (V2) |
|---|---|---|
| Work table | `extra_works` | `extra_works_v2` |
| Staging | none | `invoiceable_items` |
| Invoice | `invoices` | `extra_work_v2_invoices` |
| Line | `invoice_items` | `extra_work_v2_invoice_items` |
| Line -> work link | `extra_work_id` (works) | `invoiceable_item_id` -> `entity_id` (NULL in all live rows) |
| Work -> invoice link | `extra_works.invoice_id` (dead) | none |
| Statuses | draft/sent/paid/cancelled | draft/ready/sent/paid/cancelled/overdue |
| Release on cancel | **no** | yes (CODE `ExtraWorkV2Invoice.php:232-235`) |
| Numbering | client-side | server-side, gapless |
| Live rows | 3 invoices / 31 lines | 1 invoice / 3 lines |

Note the two systems also disagree on the cancel guard: `ExtraWorkV2Invoice::markAsCancelled`
(CODE `:232-235`) releases items to `'ready'` with **no status predicate**, so cancelling
a `sent` V2 invoice will pull already-`invoiced` items back to `ready`; the service layer
then runs a second, narrower release (CODE `ExtraWorkV2InvoiceService.php:264-272`,
`->where('status', STATUS_INVOICE_DRAFT)`). Two release passes with different predicates
on the same transaction.

---

## 3. THIS AREA'S CONNECTION MAP

### 3.1 The numbered sequence: user action -> last row touched (Path A)

1. **UI** operator opens the extra-work list / grouped invoice view. Browser calls
   `GET /api/admin/extra-works?type=1&statuses=8&per_page=200&context=admin`
   (CODE `ExtraWorkInvoiceGroupedView.jsx:157`). No date filter is applied by default.
2. **UI** browser groups rows by customer / building / department / work type and sums
   money **client-side** using each work's `products[].total_with_tax` and
   `total_subtotal` (CODE `ExtraWorkBulkAllInvoiceModal.jsx:122-140`). Zero-amount groups
   are excluded by default (`excludeZeroAmount`).
3. **UI** browser generates the invoice number and defaults `invoiceDate` to today
   (CODE `ExtraWorkBulkAllInvoiceModal.jsx:102-104`, `ExtraWorkBulkInvoiceModal.jsx:118-122`).
4. **HTTP** `POST /api/admin/invoices` with
   `{invoice_number, invoice_date, customer_id, building_id, extra_work_ids[], notes}`
   (CODE `ExtraWorkBulkInvoiceModal.jsx:197-210`), middleware `ucb.permission:invoices,create`
   (CODE `routes/api.php:1107`).
5. **DB** `BEGIN` (CODE `InvoiceController.php:106`).
6. **DB WRITE 1** `INSERT invoices` - status `draft`, subtotal/tax/total all **0**,
   `created_by = auth()->id()`, `due_date` NOT SET, `period_start`/`period_end` NOT SET,
   `source_type` NOT SET (CODE `:113-123`).
7. **DB WRITE 2..N** per work, `INSERT invoice_items` with
   `extra_work_id`, `amount = $work->total_products_cost` (products only, labour excluded),
   `tax_rate = 0.21` **hard-coded**, `description = $work->title`,
   `quantity = 1` and `unit_name = 'stuks'` (both from the broken pivot/unit access)
   (CODE `:132-147`).
8. **DB WRITE N+1..2N** per work, `UPDATE extra_works SET status_id = 9`
   (CODE `:152`). `invoice_id` and `invoice_date` are **left untouched**.
   Side effect: `ExtraWork::booted()->updated` fires (CODE `app/Models/ExtraWork.php:~560`)
   -> a system comment "Status gewijzigd: ... -> Gefactureerd" is appended to the work,
   plus an FCM notification. `ExtraWorkObserver::updated` writes an activity-log row.
9. **DB WRITE** `$invoice->refresh()` then `recalculateInvoiceTotals` ->
   `UPDATE invoices SET subtotal, tax_amount, total_amount` where
   `subtotal = SUM(amount * quantity)` and `tax = SUM(amount * quantity * tax_rate)`
   (CODE `:1021-1046`).
10. **DB** `COMMIT` (CODE `:150`). The work is now invisible in every default extra-work
    list (CODE `ExtraWorksController.php` status-9 exclusion).
11. **LATER, separate action** `POST /api/admin/invoices/{id}/send` -> renders
    `resources/views/pdf/invoice-vertical.blade.php` via mPDF, then
    `UPDATE invoices SET status='sent', pdf_path, pdf_generated_at, sent_at`
    (CODE `:361-367`). **No work row is touched.** The email send is commented out:
    CODE `:370` `// $this->sendInvoiceEmail($invoice);`.
12. **LATER** `PUT /api/admin/invoices/{id}/status` -> `paid` or `cancelled`, sent-only
    guard, `UPDATE invoices` and **nothing else** (CODE `:840-895`).

Last row touched in the happy path: `invoices` (the totals update). No audit table, no
history table, no ledger row is written for the invoice itself at any point.

### 3.2 Pointer graph

```
                       [ operator's manual selection ]
                                    |
extra_works(status_id=8) ---------->|
   |  \                             v
   |   \                    POST /admin/invoices
   |    \                           |
   |     \                +---------+----------+
   |      \               v                    v
   |       \        invoices               extra_works.status_id := 9
   |        \        (draft)                (invoice_id NOT set  <-- BROKEN FORWARD LINK)
   |         \           |
   |          \          v
   |           +--> invoice_items.extra_work_id  <-- THE ONLY REAL LINK (reverse)
   |                     |  ^                        |
   |                     |  |                        +--> Invoice::extraWorks() hasManyThrough
   |                     |  +---- ExtraWork::invoice() hasOneThrough
   |                     |  +---- pendingExtraWorks whereDoesntHave('invoiceItem')  [GATE]
   |                     |  +---- list sort_by=invoice_date subquery
   |                     |  +---- list date_field=invoice_date whereHas('invoice')
   |                     v
   |               invoice-vertical.blade.php (PDF)
   |                     |
   |                     +-- due date  := invoice_date + 1 month  (template constant)
   |                     +-- "periode" := period_start..period_end  ELSE  month(invoice_date)
   |                     +-- BTW block := grouped by invoice_items.tax_rate (always 0.21)
   |
   +--> extra_work_products.tax_rate / unit_id / quantity  ---X--- NEVER REACH THE INVOICE
   +--> extra_work_employee_hours.total_cost (labour)      ---X--- NEVER REACHES ANY INVOICE


extra_works_v2 --(BillingService)--> invoiceable_items --(EWV2InvoiceService)--> extra_work_v2_invoices
                 period from billing_*    status: draft/ready/                 items.invoiceable_item_id
                 tax_rate hard-coded 21   invoice_draft/invoiced               (NULL in all live rows)
                                          invoice_id: NEVER WRITTEN [DEAD]

extra_work_v2_period_products.invoice_number : free string, no FK, no validation [PATH C]
```

### 3.3 What action changes what

| Action | Endpoint | Writes | Does NOT write |
|---|---|---|---|
| Bulk invoice works | `POST /admin/invoices` | `invoices`, `invoice_items`, `extra_works.status_id` | `extra_works.invoice_id`, `invoice_date`, `due_date`, `period_*`, `source_type` |
| Add one work to draft | `POST /admin/invoices/{id}/items` | `invoice_items`, `extra_works.status_id/invoice_id/invoice_date`, invoice totals | - |
| Send invoice | `POST /admin/invoices/{id}/send` | `invoices.status/pdf_path/pdf_generated_at/sent_at` | anything on the works; no email (commented out) |
| Revert to draft | `POST /admin/invoices/{id}/revert-to-draft` | `invoices.status='draft'`, `sent_at=null` | `pdf_path` / `pdf_generated_at` are left stale |
| Mark paid | `PUT /admin/invoices/{id}/status` | `invoices.status/paid_at` | works untouched |
| **Mark cancelled** | `PUT /admin/invoices/{id}/status` | `invoices.status/cancelled_at` | **works stay at 9 forever - orphaned** |
| Delete draft invoice | `DELETE /admin/invoices/{id}` | works -> 8 + links cleared; items + invoice force-deleted | blocked on non-draft |
| Remove one work | `DELETE /admin/invoices/{id}/items/by-extra-work/{ewId}` | work -> 8 + links cleared; auto-deletes now-empty invoice | blocked on non-draft |
| **Change work status** | `PUT /admin/extra-works/{id}/status` | `extra_works.status_id` (any value, no guard) | **invoice left stale** |
| **Bulk group status** | `PUT /admin/extra-works/groups/{id}/status` | mass `UPDATE`, no validation, no events | no activity log, no invoice check |
| Mark V2 period invoiced | `PUT /extra-works-v2/{id}/periods/{pid}/mark-invoiced` | `is_invoiced`, `invoiced_at`, free-text `invoice_number`, period status 7 | no invoice row exists |

### 3.4 Dead fields, collected

| Field | Written by | Read by | Verdict |
|---|---|---|---|
| `extra_works.invoice_id` | `addItem` only | nothing (a DB view mentions it) | DEAD - NULL on 37/37 live status-9 works |
| `extra_works.invoice_date` | `addItem` only | nothing (all readers use `invoices.invoice_date`) | DEAD - the 3 non-null values are stale |
| `invoiceable_items.invoice_id` | **nobody** | display only | DEAD - 0/13 live rows |
| `invoiceable_items.invoiced_at` | `EWV2InvoiceService:248` | display only | Live but unused - 0/13 |
| `invoices.period_start` / `period_end` | manual PUT only | PDF only | DEAD on the EW path - NULL on 3/3 |
| `invoices.due_date` | invoiceable-items path only | PDF ignores it and computes +1 month | DEAD on the EW path - NULL on 3/3 |
| `invoices.source_type` | invoiceable-items path only | `isFromInvoiceableItems()`, `scopeOfSourceType` | populated as `extra_work` in live data despite `store()` not setting it (see gaps) |
| `ExtraWorkV2Invoice` `overdue` status | `checkOverdue()`, never called | scopes only | UNREACHABLE - no scheduler |
| `ExtraWorkV2Invoice::boot()` `saved` hook | - | - | empty body, comment only |

---

## 4. COULD NOT DETERMINE

1. **How `invoices.source_type` got the value `extra_work` in live data.**
   `InvoiceController::store` (CODE `:113-123`) does not set it, and it is not in a
   migration default I found. Yet DATA shows `source_type: "extra_work"` on all three
   live invoices. *To close*: read
   `database/migrations/2026_02_23_100000_extend_invoices_for_invoiceable_items.php` for a
   column default, or find another writer (I greped `app/` for `source_type` only within
   `InvoiceController`).

2. **Which migration created `extra_works.invoice_id` / `invoice_date`.**
   No migration in `database/migrations/` adds them - I greped every file that mentions
   `extra_works` for `invoice_id` and found only the DB-view definition that *reads*
   them. The columns exist (the API returns them). *To close*: inspect the base schema
   dump / `database/schema/*.sql`, or the earliest pre-October-2025 migration set, which
   may not be in this clone.

3. **Whether the 6 orphaned status-9 works (476, 444, 440, 439, 438, 437) came from
   `PUT /extra-works/{id}/status`, from `bulkUpdateGroupStatus`, or from a hard-deleted
   invoice.** The code proves all three are possible; the data cannot distinguish them.
   *To close*: read `extra_work_activities` for those IDs via
   `GET /admin/extra-works/{id}/activities` (an endpoint exists at
   `ExtraWorksController:1520`) - I did not call it. Note the bulk path bypasses model
   events, so absence of an activity row would itself point at `bulkUpdateGroupStatus`.

4. **Why the live V2 invoice's items have `invoiceable_item_id = NULL` while carrying
   `BillingService`-authored descriptions and real periods.** Either the source staging
   rows were soft-deleted (the list endpoint hides trashed rows), or a copy path wrote
   the fields without the FK. *To close*: call
   `GET /admin/invoiceable-items?with_trashed=1` if such a parameter is supported, or read
   `ExtraWorkV2InvoiceController::store` and `addItem` in full (I read the *service*, not
   the controller wrapper) to see whether a payload-driven create path copies fields
   without the link.

5. **Whether `$firstProduct->pivot->quantity` raises a fatal or a warning.** In PHP 8
   reading a property on `null` is a warning that evaluates to `null`, so `?? 1` applies -
   this matches the observed data (every line is `quantity 1.00`). But I did not read the
   PHP version or the error handler config, and a strict `error_reporting` setup could
   turn it into a `TypeError`. *To close*: read `composer.json` `require.php` and
   `config/app.php`. This does not change the conclusion (quantity is always 1 either
   way), only the failure mode.

6. **Whether any non-21% product has ever been bulk-invoiced other than extra work 448.**
   I confirmed one instance conclusively. I did not enumerate all 31 invoiced works'
   products. *To close*: page `GET /admin/invoices/{87,88,89}` and compare every line's
   `tax_rate` against `extra_work.products[].tax_rate` - the data for this is already in
   the `show` response, I simply only tabulated invoice 89.

7. **Whether the frontend exposes the `PUT /admin/invoices/{id}` period fields at all.**
   The backend accepts `period_start`/`period_end` on a draft. `EditInvoiceModal.jsx`
   exists but I did not read it. *To close*: read
   `frontend/src/pages/finalosius/invoices/modals/EditInvoiceModal.jsx`. If it does not
   expose them, `invoices.period_start` is unreachable from the UI and fully dead rather
   than merely unused.

8. **What `ExtraWorksV2Controller` lines 4560-4600 and 6171-6223 belong to.** I read the
   ranges around the `invoiced_at` and `invoice_date` writes but did not identify the
   enclosing method names, so I have not stated what user action triggers them. They
   operate on `extra_work_v2_schedules` / `extra_works_v2`, not on the Path A tables, so
   they do not change any conclusion above. *To close*: `grep -n "public function"` on
   that file and map the line numbers.

9. **Permission reality.** Every route in scope carries `ucb.permission:invoices,<verb>`,
   but `PUT /admin/extra-works/{id}/status` carries `ucb.permission:extra_works,update` -
   meaning a user who may edit extra works but has no invoice permission at all can still
   move a work off status 9 and stale an invoice. I read the route middleware but did not
   read `UcbPermissionMiddleware` or verify that any real role has that split. *To close*:
   read `app/Http/Middleware/UcbPermissionMiddleware.php` and `app/Services/PermissionService.php`.
   This belongs to the RBAC agent's area.

### Where I stopped

I completed all seven assigned questions with code and live-data evidence. I did not
read: `ExtraWorkV2InvoiceController` (only its service), `EditInvoiceModal.jsx`,
`InvoiceDetail.jsx`, `NormalFinancialTab.jsx` / `ContinuousFinancialTab.jsx`, the
`ContinuousWork*` family, or `ProjectInvoicesTab.jsx`. Those cover the V2/project/
continuous-work billing surfaces, which are adjacent to but not on the extra-work seam.
