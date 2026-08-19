# Osius reference system — Area A2: INVOICING

Read-only investigation of a third-party reference system.
Repos: `/tmp/osius-ref/backend` (Laravel 11/12, PHP), `/tmp/osius-ref/frontend` (React/Vite).
Live API: `dev-api.osius.nl`, GET only, through the supplied wrapper.
Investigated: 2026-08-19. Nothing was modified.

Evidence labels used throughout:
**CODE** = read in the repo, path + line + quoted source.
**DATA** = observed from a live GET call, with the real values returned.
**INFERRED** = a conclusion I drew; the confirming step is named.

Their vocabulary is kept. Their "Product" is our "Service"; every place their
Product concept touches money is flagged.

---

# 1. PLAIN-ENGLISH LOGIC — how this actually works

## 1.1 There are two-and-a-half invoicing systems, not one

The reference system contains **two completely separate invoice tables** with
separate controllers, separate numbering schemes, separate status vocabularies
and separate PDF stories. Neither knows the other exists.

| | **v1 — `invoices`** | **v2 — `extra_work_v2_invoices`** |
|---|---|---|
| Created | 2025-11-27 | 2026-02-16 |
| Controller | `Admin/InvoiceController` | `Admin/ExtraWorkV2InvoiceController` + `ExtraWorkV2InvoiceService` |
| Number format | `INV-…` | `EWV2-YYYY-NNNN` |
| Statuses | draft, sent, paid, cancelled | draft, ready, sent, paid, cancelled, overdue |
| Has a real PDF | Yes (mPDF, `pdf.invoice-vertical`) | No — the generator is a stub that writes a path and no file |
| Live rows today | 3 | 1 |
| Frontend route | `/admin/invoices` | `/admin/invoices-v2` |

The "half" is this: one week after v2 was built, the team went **back** to the
v1 `invoices` table and bolted the invoiceable-items pipeline onto it
(`2026_02_23_100000_extend_invoices_for_invoiceable_items`). So the v1 table now
carries *both* the original Extra-Work-v1 flow *and* the newest
invoiceable-items flow, while the purpose-built v2 table sits nearly unused.
Both UIs are still routed and both are still reachable from the API.

## 1.2 The v1 flow (the one with real invoices in it)

1. An operator finishes Extra Works (v1, the `extra_works` table). A finished
   work sits at `status_id = 8` ("Completed").
2. In the Extra Works screen the operator opens a bulk-invoice modal, which
   groups the works by customer/building/department/work-type.
3. **The browser invents the invoice number** — `INV-` + `yyyyMM` + a counter
   that restarts at `0001` every time the modal is opened — and POSTs one
   invoice per group.
4. The backend creates the invoice at `draft`, creates one `invoice_items` row
   per extra work, and flips each extra work to `status_id = 9` ("Invoiced").
   That flip is the only thing that marks a work as billed.
5. "Send" generates a two-page A4 PDF and moves the invoice to `sent`.
6. From `sent` the operator may mark `paid`, mark `cancelled`, or "revert to
   draft".

## 1.3 The invoiceable-items flow (the newest one)

`invoiceable_items` is meant to be a universal billable pool: any source
(extra work, continuous work, project, machine rental, material, labour,
service, other) drops rows into it, then an invoice is cut from a selection.

- Rows are written by: the ExtraWorkV2 `BillingService` (fixed-price billing
  plans, type `extra_work`), `PrjProjectsController::generateSubProjects`
  (type `project`), and a manual "copy income to expenses" button on three
  frontend tabs (types `extra_work`, `continuous_work`, `project`).
- An invoice can be cut from them **two different ways**: through
  `POST /admin/invoices/from-invoiceable-items` (writes to the **v1** table) or
  through `POST /admin/extra-work-v2-invoices` (writes to the **v2** table).
  The two paths handle the item lifecycle **differently** — see §1.5.

**On the live system the pool contains only project rows.** 13 rows, all
`type=project`, 12 draft + 1 ready, zero extra-work rows, zero continuous-work
rows. So the brief's belief is correct for the live data (§1.7).

## 1.4 Numbering

There is **no database sequence anywhere**. Three different number generators
exist and two of them are unreachable in practice:

- **v1, actually used:** the React modal builds
  `INV-${format(today,'yyyyMM')}-0001`, `-0002`, … The counter is the loop index
  inside one modal session. It never consults the server.
- **v1, backend fallback:** `InvoiceController::generateInvoiceNumber()`,
  `INV-{YYYY}-NNNN`, an application-level `max()+1` by string ordering. Only
  used by the from-invoiceable-items path.
- **v2:** `ExtraWorkV2Invoice::generateInvoiceNumber()`, `EWV2-{YYYY}-NNNN`,
  application-level `max()+1` on a cast substring, `withTrashed()`.

All three can collide under concurrency; the front-end one collides
**deterministically** — the second bulk run in the same calendar month restarts
at `-0001` and hits the `invoices.invoice_number` UNIQUE index. And the v1
`store` endpoint takes `invoice_number` straight from the request body, so a
human (or any API client) fully controls it.

## 1.5 Cancellation and correction — the decisive answer

**There is no credit note, no negative line, no invoice-references-invoice
column, and no correction mechanism anywhere in this system.** I looked in the
models, the migrations, the controllers, the services, the blade template and
the whole frontend. The only string `credit_note` in the codebase is a label on
an unrelated `ContractRevision.billing_impact` enum that nothing acts on.

What cancellation actually does depends on which table you are on:

- **v1 `invoices`:** `updateStatus` writes `status='cancelled'` and
  `cancelled_at=now()`. **Full stop.** It does not touch the extra works, which
  stay at `status_id=9` (Invoiced) forever. It does not touch invoiceable items,
  which stay at `invoice_draft` forever. It does not create a reversal document.
  The money is simply erased from the invoice's own status field, and the work
  it consumed is **permanently consumed**. The brief's belief is CONFIRMED for
  the v1 table.
- **v2 `extra_work_v2_invoices`:** `markAsCancelled()` *does* release linked
  invoiceable items back to `ready`, so on that table cancellation is a real
  (if crude) unwind. But it is still not a credit note — no document is
  produced, the original invoice is simply flagged.

The only way to un-bill something in v1 is to **delete the draft invoice** (or
remove an item from it) before it is sent. Those paths do revert extra works to
`status_id=8` and null their invoice pointers. Once `sent`, that door closes:
`destroy`, `deleteItem` and `removeExtraWork` all refuse anything that is not a
draft. "Revert to draft" reopens the door but only from `sent`, and it does not
clear `pdf_path`, so the already-issued PDF remains on disk and downloadable.

Negative amounts are blocked at validation (`amount|min:0`,
`unit_price|min:0`), so you cannot even hand-build a credit line.

## 1.6 What the PDF says versus what the database says

The PDF (`resources/views/pdf/invoice-vertical.blade.php`, 546 lines) is a
two-page document:

- **Page 1 "Overzicht":** exactly **one** summary line. Description, subtitle,
  quantity, unit, price, BTW, total. Then a totals block with an optional
  discount row.
- **Page 2 "SPECIFICATIE":** every `invoice_items` row, one per line, with its
  own BTW, and a per-rate BTW breakdown.

The header block carries `Factuurnummer`, `Factuurdatum`, `Vervaldatum`,
**`Debiteurnummer` = `customer.id`** and **`Bonnummer` = `invoice.id`**. Both of
those are raw internal primary keys presented to the customer as business
identifiers.

Three things about this template matter more than the layout:

1. **`Vervaldatum` ignores the `due_date` column entirely.** The template prints
   `invoice_date + 1 month`. The `due_date` column is written by the
   from-invoiceable-items path and is never read by anything.
2. **The stored totals are never printed.** `subtotal`, `tax_amount` and
   `total_amount` are recomputed inside the blade from the items. If the stored
   values disagree with the items, the PDF silently wins.
3. **The two pages can disagree with each other.** Page 1 applies the invoice
   discount; page 2 does not. And within page 1 the summary line's own "Totaal"
   column is computed *without* the discount while the totals block below it is
   computed *with* it. On any invoice with a discount, the document contradicts
   itself in three places.

## 1.7 InvoiceableItem — the known gap, answered

**What writes a row** (4 writers, all found):

| Writer | Type written | Trigger |
|---|---|---|
| `BillingService` (8 `create` sites) | `extra_work` | ExtraWorkV2 saved with `price_type=fixed`; also "regenerate billing", "update billing dates" |
| `PrjProjectsController::generateSubProjects` (6 `create` sites) | `project` | Saving a project's customer/department cost distribution |
| `InvoiceableItemController::store` | any of 8 types | The "copy income to expenses" button on ProjectFinancialTab / NormalFinancialTab / ContinuousFinancialTab |
| (nothing else) | — | No observer, no job, no scheduler, no migration seeds rows |

**What removes a row:**

| Remover | Kind | Guard |
|---|---|---|
| `BillingService::deleteDraftItems` | soft delete | only `draft`/`ready` |
| `ExtraWorksV2Controller::deleteDraftBillingItems` | soft delete | only `draft`/`ready` |
| `InvoiceableItemController::destroy` | soft delete | refuses `invoiced` |
| `PrjProjectsController::generateSubProjects` | **forceDelete** | **`notes LIKE 'auto_generated%'` only — NO status guard** |

That last one is the dangerous one: re-saving a project's cost distribution
hard-deletes its auto-generated invoiceable items **regardless of whether they
have already been invoiced**. The `invoice_items.invoiceable_item_id` FK is
`nullOnDelete`, so the invoice line survives as an orphan with a null source
pointer.

**What the table actually holds right now:** 13 rows, 100% `type=project`,
`entity_type` NULL on every single one, `invoice_id` NULL on every single one,
`invoiced_at` NULL on every single one. **Zero extra-work rows.** So yes — on
the live system the v1 Extra-Work-to-invoice path bypasses `invoiceable_items`
completely, because that path predates the table and was never migrated onto it.

## 1.8 The dead ends

- **`invoiceable_items.invoice_id` is dead.** Declared, migrated, indexed,
  serialized to the frontend — and **never written by any code path**. Every one
  of the 13 live rows has it NULL, including the ones already reserved on
  invoices. The only back-link that exists is the reverse one
  (`invoice_items.invoiceable_item_id`).
- **`invoiceable_items.invoiced_at` is dead in the v1 path.** Only
  `ExtraWorkV2InvoiceService::updateStatus` sets it. Since the v1 path never
  advances an item past `invoice_draft`, an item billed through v1 is never
  marked `invoiced` and never gets a timestamp.
- **`invoices.due_date` is write-only.** Nothing reads it.
- **`extra_works.invoice_id` / `extra_works.invoice_date` are write-only in
  practice.** The bulk path (the only one anyone uses) does not set them —
  confirmed live: a *sent* invoice's four extra works all have
  `invoice_id: null, invoice_date: null, status_id: 9`.
- **Status `overdue` is unreachable.** The only writer is
  `checkOverdueInvoices()`, and **there is no scheduler in this application at
  all** — no `app/Console/Kernel.php`, and `routes/console.php` contains only
  Laravel's stock `inspire` command. Nothing ever calls it.
- **The v2 PDF does not exist.** `ExtraWorkV2InvoiceService::generatePdf()` is a
  `// TODO` that writes a filename into `pdf_path` and returns. `sendInvoice()`
  is a `// TODO` that marks the invoice sent without sending anything. So on the
  v2 table, `pdf_path` points at a file that was never created and `sent_at`
  means "somebody clicked a button".

## 1.9 Where the totals disagree with themselves

Four independent total formulas run over the same `invoice_items` rows:

| # | Where | Formula |
|---|---|---|
| 1 | `InvoiceController::recalculateInvoiceTotals()` | `Σ(amount × quantity)`, tax `Σ(amount × quantity × tax_rate)` |
| 2 | `Invoice::recalculateTotals()` (model) | `Σ(amount)`, tax `Σ(amount × tax_rate)` — **quantity ignored** |
| 3 | PDF page 1 | one summary line, discount applied |
| 4 | PDF page 2 | `Σ(amount × quantity)`, discount **not** applied |

Formula 1 is used by the v1 extra-work path; formula 2 by the
from-invoiceable-items path. An invoice created from invoiceable items with any
`quantity != 1` therefore stores a `total_amount` that its own PDF contradicts.
This is invisible today only because every live row has `quantity = 1.00`.

The v2 table has its own arithmetic problem: `ExtraWorkV2InvoiceItem` stores
`subtotal` **after** discount *and* stores `discount_amount`, and then
`ExtraWorkV2Invoice::calculateTotals()` computes
`subtotal + tax − discount_amount` — subtracting the discount a second time.

## 1.10 Double-billing holes

1. `createFromInvoiceableItems` deliberately re-accepts items already sitting at
   `invoice_draft` ("the previous invoice may have been cancelled/deleted").
   Since the v1 path *never* advances an item past `invoice_draft`, an item on a
   **sent** v1 invoice is still eligible to be put on a second invoice.
2. `InvoiceableItemController::updateStatus` lets a human set any item to
   `ready` — including one currently reserved on a draft invoice — putting it
   back in the pool while it is still on the invoice.
3. The same endpoint lets a human set an item to `invoiced` with **no invoice in
   existence**, which permanently locks it (update, delete and status change all
   refuse `invoiced`).

---

# 2. EVIDENCE — read/write maps

## 2.1 Model: `Invoice` → table `invoices`

`app/Models/Invoice.php` (191 lines). SoftDeletes. No `$appends`.

Base table: `database/migrations/2025_11_27_131834_create_invoices_table.php`.

| Column | Migration definition | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|---|
| `id` | `$table->id()` | auto | PDF prints it as **`Bonnummer`** (`invoice-vertical.blade.php:302`) | n/a | no | no |
| `invoice_number` | `string()->unique()` | `InvoiceController::store` (client-supplied, `:88` validator `required\|string\|unique`), `:192 update` (draft only), `createInvoiceFromItems:1179`, `createInstallmentInvoices:1288` | PDF header, list search, ZIP filename, download filename | `store` rejects | UNIQUE index blocks a duplicate; frontend collides on it | no |
| `invoice_date` | `date()` | all 3 create paths; `update` | PDF `Factuurdatum`; PDF `Vervaldatum` (= +1 month); list ordering; `date_from`/`date_to` filters | `store` rejects | drives the printed due date | no |
| `due_date` | added `2026_02_23_100000`, nullable | ONLY `createInvoiceFromItems:1186` and `createInstallmentInvoices:1291` | **nothing** | — | none | **DEAD (write-only)** |
| `status` | `enum('draft','sent','paid','cancelled') default 'draft'` | `store` (`'draft'`), `sendInvoice:361`, `updateStatus:875`, `revertToDraft:537`, `update` (validator allows it but `update` itself refuses non-draft invoices) | `isDraft/isSent/isPaid/isCancelled`, every guard in the controller, PDF "DRAFT FACTUUR" banner (`blade:239`), frontend action buttons | default draft | **the master gate** — edit, delete, add/remove item, send are all draft-only; paid/cancelled are sent-only | no |
| `source_type` | added `2026_02_23_100000`, `string(50) default 'extra_work'` | `createInvoiceFromItems:1177` (`mixed` if the group has >1 type), `createInstallmentInvoices` | `isFromInvoiceableItems()` and `scopeOfSourceType()` — **neither is called anywhere** | defaults `extra_work` | none | **effectively DEAD** |
| `customer_id` | FK restrict | all 3 create paths | PDF address block, PDF `Debiteurnummer`, list filter, search-by-name | `store` rejects | no | no |
| `building_id` | FK restrict, nullable | all 3 create paths | PDF (bold line under customer name; page-2 header) | PDF omits the line | no | no |
| `customer_department_id` | added `2026_02_23_100000`, FK nullOnDelete | only the from-invoiceable-items paths | **nothing** (not in the PDF, not in any query) | — | none | **DEAD** |
| `subtotal`,`tax_amount`,`total_amount` | `decimal(10,2) default 0` | `recalculateInvoiceTotals()` (controller, `:1021`) and `Invoice::recalculateTotals()` (model, `:160`) — **two different formulas** | frontend list/detail columns only. **Not the PDF.** | 0 | no | no, but not authoritative |
| `notes` | `text` nullable | `store` (auto-note "Department - WorkType" from the modal), `update` | PDF "Opmerkingen" block (`blade:270`) | block omitted | no | no |
| `pdf_path` | `string` nullable | `sendInvoice:363`, `regeneratePdf:511` | `downloadInvoice`, `bulkDownload`, `hasPDF()` (never called) | download 404s | blocks `bulkDownload` (it filters `whereNotNull`) | no |
| `pdf_generated_at` | added `2025_11_27_230515` | `sendInvoice`, `regeneratePdf` | nothing | — | none | **DEAD** |
| `sent_at` | idem | `sendInvoice:364`, cleared by `revertToDraft:538` | frontend display | — | none | no |
| `paid_at` | idem | `updateStatus` when status=paid | frontend display | — | none | no |
| `cancelled_at` | idem | `updateStatus` when status=cancelled | frontend display | — | none | no |
| `created_by` | FK restrict | all create paths, `auth()->id()` | `creator` relation, eager-loaded | — | no | no |
| `summary_description` | `2026_02_18_100000` | `update` only | PDF page-1 summary line | PDF falls back to building names + period/month string (`blade:337-347`) | no | no |
| `summary_subtitle` | `2026_02_18_085212` **and again** `2026_02_18_100000` | `update` only | PDF page-1 sub-line | falls back to "`N` meerwerken - Zie bijlage voor specificatie" | no | no |
| `summary_quantity` | `decimal(10,2) default 1` | `update` | PDF "Aantal" on the summary line | falls back to 1 | no | no |
| `summary_unit` | `string(50) default 'stuks'` | `update` | PDF "Eenheid" | falls back to `stuks` | no | no |
| `summary_price` | `decimal` nullable | `update` | PDF "Prijs" AND the page-1 subtotal | **falls back to `Σ(amount × quantity)`** — this is the only place a null changes a printed money figure | **yes: overrides the computed subtotal on the printed invoice** | no |
| `summary_tax_rate` | `decimal(5,2) default 0.21` | `update` (validator `min:0\|max:1`, i.e. a fraction) | PDF BTW % and BTW amount on page 1 | falls back to the weighted average item rate | yes, changes the printed tax | no |
| `discount_type` | `2026_02_18_085426`, `enum('percentage','fixed')` nullable | `update` only | PDF page 1 only | no discount row | yes, changes the printed total | no |
| `discount_value` | `decimal(10,2)` nullable | `update` only | PDF page 1 only | idem | idem | no |
| `period_start` / `period_end` | `2026_02_18_100000`, date nullable | `update` only | PDF: the fallback summary description string, and a "Periode: … t/m …" line under the totals (`blade:415`) | falls back to the invoice month | no | no |
| `deleted_at` | softDeletes | never (all delete paths use `forceDelete()`) | Eloquent global scope | — | no | **DEAD** — v1 invoices are always hard-deleted |

**CODE — the summary/discount block, `resources/views/pdf/invoice-vertical.blade.php:328-368`:**
```php
$summaryPrice = ($invoice->summary_price !== null) ? floatval($invoice->summary_price) : $itemSubtotal;
$summaryTaxRate = $invoice->summary_tax_rate ? floatval($invoice->summary_tax_rate) : $avgTaxRate;
...
$subtotalAfterDiscount = $summaryPrice - $discountAmount;
$summaryTax = $subtotalAfterDiscount * $summaryTaxRate;
$summaryTotal = $subtotalAfterDiscount + $summaryTax;
$summaryLineTotal = $summaryPrice + ($summaryPrice * $summaryTaxRate);   // <-- discount NOT applied
```
The table row prints `$summaryLineTotal`; the totals block prints
`$summaryTotal`. **CODE** — they differ by the discount plus its tax.

**CODE — `Vervaldatum` ignores `due_date`, `blade:290`:**
```php
<td class="value-col">{{ \Carbon\Carbon::parse($invoice->invoice_date)->addMonth()->format('d.m.Y') }}</td>
```

**CODE — Debiteurnummer / Bonnummer, `blade:294-303`:**
```php
<td class="label-col">Debiteurnummer</td> ... {{ $invoice->customer->id ?? 'N/A' }}
<td class="label-col">Bonnummer</td>      ... {{ $invoice->id }}
```

**DATA — `GET /admin/invoices?per_page=100`:** 3 invoices total.
`89 INV-202605-0003 sent extra_work due=null items=21 total=656.01`,
`88 INV-202605-0002 sent extra_work due=null items=4 total=364.45`,
`87 INV-202605-0001 draft extra_work due=null items=6 total=282.45`.
Status counter `{sent: 2, draft: 1}`; `source_type` counter `{extra_work: 3}`.
Zero paid, zero cancelled, zero from-invoiceable-items invoices.

### Relations and helpers on `Invoice`

| Member | Status |
|---|---|
| `customer()`, `building()`, `items()`, `creator()` | live, eager-loaded everywhere |
| `customerDepartment()` | **DEAD** — never eager-loaded, never read |
| `extraWorks()` (hasManyThrough) | **DEAD** — no caller |
| `scopeDraft/scopeSent/scopePaid` | **DEAD** — no caller (the controller filters `whereIn('status', …)` by hand) |
| `scopeOfSourceType` | **DEAD** |
| `isDraft/isSent/isPaid/isCancelled` | `isDraft` heavily used; `isSent`/`isPaid`/`isCancelled` unused in PHP (the frontend does its own string compare) |
| `canEdit()`, `canDelete()` | **DEAD** — the controller inlines `!$invoice->isDraft()` |
| `hasPDF()` | **DEAD** |
| `recalculateTotals()` | live — but only on the from-invoiceable-items path, and it disagrees with the controller's private version |
| `isFromInvoiceableItems()` | **DEAD** |

## 2.2 Model: `InvoiceItem` → table `invoice_items`

`app/Models/InvoiceItem.php` (47 lines). **No SoftDeletes**, no boot hooks, no
calculation logic — everything is set by the caller.

| Column | Migration | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|---|
| `invoice_id` | FK cascade | all item creators | everything | — | cascade delete | no |
| `extra_work_id` | originally `unsignedBigInteger` + **`unique('extra_work_id')`**; made nullable by `2026_02_23_110000` | `store:142`, `addItem:607` | PDF page-2 "EW" column; `pendingExtraWorks` (`whereDoesntHave('invoiceItem')`); `deleteItem`/`destroy` revert logic; ReportsController `invoice_ids` filter | PDF prints `-` | **the UNIQUE index is the only structural guarantee that one extra work is billed once** | no |
| `invoiceable_item_id` | added `2026_02_23_100000`, FK **nullOnDelete** | `createInvoiceFromItems:1204`; explicitly NULL in `createInstallmentInvoices:1302` | `deleteItem`/`destroy` release logic; `InvoiceController::index` project filter | release is skipped | no | no |
| `source_type` | added `2026_02_23_100000`, `string(50)` nullable | only from-invoiceable-items paths | **nothing** | — | none | **DEAD** |
| `amount` | `decimal(10,2) default 0` | `store` (= `extraWork->total_products_cost`), `addItem`, `updateItem` (`min:0`), `createInvoiceFromItems` (= item `subtotal`) | both total formulas; PDF page-2 "Prijs" | treated as 0 | **`min:0` — negative lines impossible** | no |
| `tax_rate` | `decimal(5,4) default 0.2100` — a **fraction**, not a percentage | `store` hardcodes `0.21`, `addItem` hardcodes `0.21`, `updateItem` (`min:0\|max:1`), `createInvoiceFromItems` writes `tax_rate/100` | both total formulas; PDF per-rate BTW breakdown | defaults 0.21 in every reader | no | no |
| `description` | `text` nullable | `store` (= extra work title), `createInvoiceFromItems` (= `title - description`) | PDF page-2 fallback when the extra work has no building/title | falls back to `'N/A'` | no | no |
| `unit_name` | `string(50)` nullable, `2025_11_30_192254` | `store`/`addItem` from the first product's unit label; `createInvoiceFromItems` from `unit.name` | PDF page-2 "Eenh." | PDF re-derives from the extra work's first product, then `'stuks'` | no | no |
| `quantity` | `decimal(10,2) default 1.00` | `store`/`addItem` = **the first product's quantity only**; `createInvoiceFromItems` = item quantity | controller total formula; PDF page 2. **Not** the model total formula | both readers default to 1 | no | no |
| `unit_price` | added `2026_02_23_100000`, `decimal(12,2)` nullable | only from-invoiceable-items | **nothing** | — | none | **DEAD** |

**CODE — the v1 amount/quantity mismatch, `InvoiceController.php:132-149`:**
```php
$quantity = 1.00;
if ($work->products && $work->products->isNotEmpty()) {
    $firstProduct = $work->products->first();
    $quantity = floatval($firstProduct->pivot->quantity ?? 1);
    ...
}
InvoiceItem::create([
    'amount' => $work->total_products_cost ?? 0, // Only products, not labor
```
`ExtraWork::getTotalProductsCostAttribute()` (`app/Models/ExtraWork.php:427`)
sums **every** product's `subtotal`, which is already quantity-inclusive. The
controller then multiplies that total by the **first** product's quantity
(`recalculateInvoiceTotals:1035: $itemSubtotal = $itemAmount * $itemQuantity;`).
For any extra work whose first product has quantity ≠ 1 this **double-counts**.
Every live row has `quantity = 1.00`, so it has not bitten yet. **CODE +
DATA.**

Also note the comment `// Only products, not labor` — labour hours never reach
the invoice on the v1 path at all. Their "Product" is our "Service", and this is
one of the places that concept meets money: **the invoice line is the product
total, and labour is silently excluded.**

**DATA — `GET /admin/invoices/88`:** 4 items, each
`amount=75.30 quantity=1.00 unit_name=stuks tax_rate=0.2100 source_type=null
unit_price=null invoiceable_item_id=null`. Stored header:
`subtotal=301.20 tax_amount=63.25 total_amount=364.45`. 4 × 75.30 = 301.20 —
formula 1 confirmed live.

## 2.3 Model: `InvoiceableItem` → table `invoiceable_items`

`app/Models/InvoiceableItem.php` (287 lines). SoftDeletes. **Has a boot hook.**

**CODE — `InvoiceableItem.php:88-119`:**
```php
static::saving(function ($model) { $model->calculateTotals(); });
...
$this->subtotal = $this->quantity * $this->unit_price;      // BEFORE discount
...
$afterDiscount = $this->subtotal - $discountAmount;
$this->tax_amount = $afterDiscount * ($this->tax_rate / 100);
$this->total = $afterDiscount + $this->tax_amount;
```
So on this model `subtotal` is pre-discount. On `ExtraWorkV2InvoiceItem`
`subtotal` is **post**-discount (§2.5). Same word, two meanings, and the two
models feed each other.

Base table: `2026_01_29_140000_create_invoiceable_items_table.php`.

| Column | Migration | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|---|
| `type` | `enum(extra_work, continuous_work, project*, machine_rental, material, labor, service, other) default 'other'`; `project` added by `2026_02_19_100000` | `BillingService` (`'extra_work'`), `PrjProjectsController` (`'project'`), `InvoiceableItemController::store` | invoice `source_type` derivation; `BillingService` lookups (`where type=extra_work`); `ExtraWorksV2Controller:6018`; `ContinuousWorkController:1777`; `PrjProjectsController:460`; `ExtraWorkV2InvoiceItem::createFromInvoiceableItem` type mapping | default `other` | decides which tab shows the item; decides the invoice's `source_type` | no |
| `entity_id` | `2026_01_29_150000`, nullable | `BillingService` (= ExtraWorkV2 id), `PrjProjectsController` (= **sub-project** id), `store` | every `where('entity_id', …)` lookup; the project filter on `InvoiceController::index` | item is orphaned from its source | yes — the delete/regenerate paths key on it | no |
| `entity_type` | `2026_02_23_120000`, `string(100)` nullable | `InvoiceableItemController::store`/`update` only (the frontend ProjectFinancialTab sends `'PrjProject'`); a one-off backfill migration `2026_02_23_140000` | `InvoiceController::index` project filter, which explicitly tolerates NULL as legacy | filter falls back to `type='project'` | no | **NULL on 100% of live rows (DATA)** |
| `customer_id` | FK cascade | all writers | grouping, all pool queries, invoice header | required | yes | no |
| `building_id` | FK set null | all writers | pool filter, invoice header | invoice gets a null building | no | no |
| `customer_department_id` | FK set null | `BillingService`, `PrjProjectsController` | `per_department` grouping (`groupInvoiceableItems:1148`), invoice header | grouped under key `0` | **yes — decides how many invoices get cut** | no |
| `customer_works_type_id` | FK set null | idem | pool filter, eager load | — | no | no |
| `title` | `string` required | all writers | invoice item description, EWV2 item title | rejected | no | no |
| `description` | `text` nullable | all writers | appended to the invoice line description | line = title only | no | no |
| `quantity` | `decimal(10,2) default 1` | all writers (BillingService always writes 1) | `calculateTotals`, invoice item quantity | 0 → zero line | no | no |
| `unit_id` | FK `product_units` set null | `store` (`exists:product_units,id`), copy-to-expense buttons | `unit` relation → `unit.name` onto the invoice line | line has no unit | no | no |
| `unit_price` | `decimal(10,2) default 0` | all writers | `calculateTotals`, invoice amount, `BillingService` invoiced-amount arithmetic | 0 | no | no |
| `discount_percentage` / `discount_amount` | `decimal` nullable | `store`/`update` only | `calculateTotals` (percentage wins if both set) | no discount | changes the price | no |
| `subtotal`,`tax_amount`,`total` | `decimal(12,2) default 0` | **always overwritten by the `saving` hook** | `createInvoiceFromItems` uses `subtotal` as the invoice line `amount`; `InvoiceableItemController::index` totals block | recomputed | no | no (but any value a caller writes is ignored) |
| `tax_rate` | `decimal(5,2) default 21` — a **percentage** | all writers (always 21) | `calculateTotals`; converted to a fraction (`/100`) for the invoice line | 21 | validator restricts to `0,9,21` | no |
| `status` | `enum('draft','ready','invoiced','cancelled')`; `invoice_draft` added by `2026_02_17_100000` | `BillingService` (`draft`), `PrjProjectsController` (`draft`), `store` (`draft`), `createInvoiceFromItems:1216` (`invoice_draft`), `createInstallmentInvoices:1262` (`invoice_draft`), `ExtraWorkV2InvoiceService` (`invoice_draft` → `invoiced` → `ready`), `InvoiceController::destroy:277`/`deleteItem:794` (`ready`), `InvoiceableItemController::updateStatus` (**any of draft/ready/invoiced/cancelled, by hand**) | every pool query; edit/delete guards | default `draft` | **the pool gate.** `invoiced` locks the row against update, delete and status change | no |
| `invoice_id` | `unsignedBigInteger` nullable, indexed | **NOTHING** | `PrjProjectsController:481` serialises it to the frontend | always NULL | none | **DEAD — declared, indexed, never written** |
| `invoiced_at` | `timestamp` nullable | ONLY `ExtraWorkV2InvoiceService::updateStatus:248` | `ExtraWorksV2Controller:6043` display | always NULL on the v1 path | none | **DEAD in the v1 path** |
| `period_start` / `period_end` | date nullable | `BillingService` (billing period), `store` | copied onto EWV2 invoice items → `period_label` accessor (itself dead) | no period shown | no | mostly dead |
| `scheduled_date` | `2026_02_13_130000`, date nullable | `BillingService` only | **the current/overdue split** in `getInvoiceableItemsForCustomer:1361` and `ExtraWorkV2InvoiceService::getInvoiceableItems:47`; default ordering | **treated as "current", never overdue** | yes — decides which bucket the item appears in | no |
| `reference_number` | `string` nullable | `store` only | copied onto EWV2 invoice items | — | no | mostly dead |
| `notes` | `text` nullable | all writers; `BillingService`/`PrjProjects` write sentinel values `auto_generated_from_task` / `auto_generated_from_product` | **`PrjProjectsController` deletes rows by `notes LIKE 'auto_generated%'`** | manual rows survive the purge | **yes — `notes` is load-bearing as a deletion key** | no |
| `metadata` | `json` nullable | `store`/`update` only | **nothing** | — | none | **DEAD** |
| `installment_number` / `installment_total` | `2026_02_13_120000`, tinyint nullable | `BillingService` only | **nothing** — no query, no display, no PDF | — | none | **DEAD** |
| `created_by` / `updated_by` | FK set null | all writers | relations declared, never eager-loaded | — | no | mostly dead |
| `deleted_at` | softDeletes | `deleteDraftItems`, `deleteDraftBillingItems`, `destroy` | global scope; `createFromInvoiceableItems` validator `exists:…,deleted_at,NULL` | — | yes | no |

**DATA — `GET /admin/invoiceable-items?per_page=500`** (13 rows, the whole
table): `by type: {project: 13}`, `by status: {draft: 12, ready: 1}`,
`invoice_id: {None: 13}`, `invoiced_at set: {False: 13}`,
`entity_type: {None: 13}`, `installment_total: {None: 13}`,
`scheduled_date nonnull: 0`, `unit_id nonnull: 0`, `reference_number nonnull: 0`,
`metadata nonnull: 0`, `discount_percentage nonnull: 0`, `period_start nonnull: 0`.

**DATA — the API also returns `project_id` and `task_id` on every row**, both
NULL on all 13. Neither column appears in any migration under
`database/migrations/` and neither is in `$fillable`. They exist in the live
schema but are unreachable from Eloquent. (See COULD NOT DETERMINE.)

**DATA — `GET /admin/customers/2029/invoiceable-items`** (the EWV2 service
path) → `{"items":[],"overdue_items":[],"overdue_count":0}`.
**DATA — `GET /admin/invoices/customers/2048/invoiceable-items`** → 2 items,
both `type=project status=draft total=0.00 scheduled_date=null`.

### The destructive project purge

**CODE — `app/Http/Controllers/Admin/PrjProjectsController.php:875-878`, inside
`generateSubProjects()`:**
```php
InvoiceableItem::where('type', 'project')
    ->where('entity_id', $sub->id)
    ->forceDelete();
```
**CODE — same file, `:903-906`:**
```php
InvoiceableItem::where('type', 'project')
    ->where('entity_id', $subProject->id)
    ->where('notes', 'LIKE', 'auto_generated%')
    ->forceDelete();
```
No status filter on either. `forceDelete()` on a `SoftDeletes` model is a real
`DELETE`. `invoice_items.invoiceable_item_id` is `nullOnDelete`, so an existing
invoice line quietly loses its source pointer instead of blocking the delete.

### Dead accessors and scopes on `InvoiceableItem`

`getTypeLabelAttribute`, `getStatusLabelAttribute`, `getFormattedTotalAttribute`,
`getCanEditAttribute`, `getCanInvoiceAttribute`, `scopeDraft`, `scopeReady`,
`scopeInvoiced`, `scopePending`, `scopeForCustomer`, `scopeOfType` — **all
dead**. The model declares no `$appends`, so none of the accessors is
serialized, and no controller references any of them. (The status label map even
contains an untranslated Turkish string, `'Taslak fatura'` for
`invoice_draft` — visible proof it is never rendered.)

## 2.4 Model: `ExtraWorkV2Invoice` → table `extra_work_v2_invoices`

`app/Models/ExtraWorkV2Invoice.php` (339 lines). SoftDeletes. Boot hook
generates the number.

Migration: `2026_02_16_200000_create_extra_work_v2_invoices_table.php`.

| Column | Migration | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|---|
| `invoice_number` | `string(50) unique` | **only** the `creating` boot hook via `generateInvoiceNumber()` — the controller never accepts one from the payload | list display, `generatePdf` filename | hook always fills it | UNIQUE | no |
| `customer_id` | FK restrict | `createFromInvoiceableItems`, `duplicateInvoice` | scoping, statistics | required | items must belong to this customer (`Service:83`) | no |
| `building_id` | FK set null | idem | `scopeForBuilding` | — | no | no |
| `invoice_date` | `date` required | idem | list ordering, `scopeInDateRange` | — | no | no |
| `due_date` | `date` nullable | `store`/`update` | `checkOverdue()` and `checkOverdueInvoices()` — **neither is ever called** | never overdue | none in practice | **effectively DEAD** |
| `scheduled_date` | `date` nullable | `store`/`update` | **nothing** | — | none | **DEAD** |
| `status` | `enum(draft,ready,sent,paid,cancelled,overdue) default draft` | `markAsReady/Sent/Paid/Cancelled`, `checkOverdue` | `isEditable()`, every service guard, frontend | draft | **the gate** — see §2.4.1 | `overdue` unreachable |
| `subtotal`,`tax_amount`,`discount_amount`,`total_amount` | `decimal(12,2) default 0` | ONLY `calculateTotals()` | list display, `getCustomerStatistics` sums | 0 | no | no |
| `notes` / `internal_notes` | `text` nullable | `store`/`update`, copied by `duplicateInvoice` | frontend only (no PDF exists) | — | no | no |
| `pdf_path` | `string(255)` nullable | `generatePdf()` — **which writes no file** | `download()`; `sendInvoice` uses it as an "exists" check | PDF is "generated" | no | **misleading — points at a nonexistent file** |
| `pdf_generated_at` | timestamp | `generatePdf()` | nothing | — | none | **DEAD** |
| `sent_at` | timestamp | `markAsSent()` | display | — | none | no |
| `paid_at` | timestamp | `markAsPaid()` | display | — | none | no |
| `cancelled_at` | timestamp | `markAsCancelled()` | display | — | none | no |
| `created_by` / `updated_by` | FK | service | `creator`/`updater` relations, eager-loaded in `index` | — | no | no |
| `deleted_at` | softDeletes | `deleteInvoice()` (draft only) | global scope; `generateInvoiceNumber` uses `withTrashed()` so numbers are not reused | — | yes | no |

**CODE — numbering, `ExtraWorkV2Invoice.php:100-118`:**
```php
public static function generateInvoiceNumber(): string
{
    $year = date('Y');
    $prefix = "EWV2-{$year}-";
    $lastInvoice = self::where('invoice_number', 'like', "{$prefix}%")
        ->withTrashed()
        ->orderByRaw("CAST(SUBSTRING(invoice_number, -4) AS UNSIGNED) DESC")
        ->first();
    if ($lastInvoice) {
        $lastNumber = (int) substr($lastInvoice->invoice_number, -4);
        $nextNumber = $lastNumber + 1;
    } else { $nextNumber = 1; }
    return $prefix . str_pad($nextNumber, 4, '0', STR_PAD_LEFT);
}
```
Application-level `max()+1`. No `lockForUpdate`, no transaction around the
read-then-write (the `creating` hook fires inside `DB::transaction` in
`createFromInvoiceableItems`, but that is READ COMMITTED — two concurrent
transactions both read `0004` and both try to write `0005`; the UNIQUE index
turns the loser into a 500). It also breaks past 9999 (`SUBSTRING(...,-4)`).

**DATA — `GET /admin/extra-work-v2-invoices?per_page=100`:** total 1.
`4 EWV2-2026-0004 draft inv_date 2026-02-23 due 2026-03-25 sub 8058.77 tax
1692.34 disc 0.00 tot 9751.11 sent None paid None canc None pdf None del None`.
Numbers 0001–0003 are absent from the visible list — consistent with
`deleteInvoice()` soft-deleting them, which is exactly why the generator uses
`withTrashed()`.

### 2.4.1 v2 status machine (the only real state machine in this area)

**CODE — `ExtraWorkV2Invoice.php:176-234`:**
```php
public function markAsReady()     { if ($this->status !== self::STATUS_DRAFT) return false; ... }
public function markAsSent()      { if (!in_array($this->status, [DRAFT, READY])) return false; ... }
public function markAsPaid()      { if ($this->status !== self::STATUS_SENT) return false; ... }
public function markAsCancelled() { if (in_array($this->status, [PAID, CANCELLED])) return false;
                                    $this->items()->whereNotNull('invoiceable_item_id')->each(function ($item) {
                                        InvoiceableItem::where('id', $item->invoiceable_item_id)
                                            ->update(['status' => 'ready']); }); ... }
```
Legal transitions: `draft→ready`, `draft→sent`, `ready→sent`, `sent→paid`,
`{draft,ready,sent,overdue}→cancelled`, `sent→overdue` (unreachable).
Illegal and refused: anything out of `paid`, anything out of `cancelled`,
`ready→draft`, `sent→draft`. **There is no un-send and no un-pay on v2.**

Note `markAsCancelled()` releases items with **no status filter** — it forces
them to `ready` even if they were `invoiced`. The service-level cancel block
(`ExtraWorkV2InvoiceService.php:257-266`) does filter on `invoice_draft`, but
the model method has already run by then, so the unfiltered version wins.

**CODE — `ExtraWorkV2InvoiceService.php:236-254`, what `sent`/`paid` do to the
underlying works:**
```php
if (in_array($newStatus, [STATUS_SENT, STATUS_PAID])) {
    $invoiceableItemIds = $invoice->items()->whereNotNull('invoiceable_item_id')->pluck('invoiceable_item_id');
    if ($invoiceableItemIds->isNotEmpty()) {
        InvoiceableItem::whereIn('id', $invoiceableItemIds)
            ->update(['status' => InvoiceableItem::STATUS_INVOICED, 'invoiced_at' => now()]);
    }
}
```
This is the **only** code in the entire application that writes
`InvoiceableItem::STATUS_INVOICED` or `invoiced_at`.

**DATA — a consequence, from `GET /admin/extra-work-v2-invoices/4`:** all three
of invoice 4's items have `invoiceable_item_id: null` (items 10, 11, 12; titles
"sadsadsad - February 2026", "tg - February 2026", "Na voltoid - Termijn 1/5";
descriptions "Maandelijkse facturatie - vanuit inkomsten" etc., which is
`BillingService` wording, so they *were* created from invoiceable items). With
the link gone, sending or cancelling this invoice will mark and release
**nothing**.

## 2.5 Model: `ExtraWorkV2InvoiceItem` → table `extra_work_v2_invoice_items`

`app/Models/ExtraWorkV2InvoiceItem.php` (228 lines). No SoftDeletes. Three boot
hooks.

**CODE — `ExtraWorkV2InvoiceItem.php:83-97`:**
```php
static::saving(function ($item) { $item->calculateTotals(); });
static::saved(function ($item)  { $item->invoice->calculateTotals(); });
static::deleted(function ($item){ $item->invoice->calculateTotals(); });
```

**CODE — `:102-124`, note `subtotal` is stored POST-discount:**
```php
$subtotalAfterDiscount = $subtotal - $discountAmount;
$taxAmount = $subtotalAfterDiscount * ((int) $this->tax_rate / 100);
$this->subtotal = round($subtotalAfterDiscount, 2);
$this->discount_amount = round($discountAmount, 2);
$this->total = round($subtotalAfterDiscount + $taxAmount, 2);
```
**CODE — against `ExtraWorkV2Invoice.php:152-165`:**
```php
$subtotal = $this->items()->sum('subtotal');          // already post-discount
$discountAmount = $this->items()->sum('discount_amount') ?? 0;
'total_amount' => $subtotal + $taxAmount - $discountAmount,   // subtracted a SECOND time
```
**The header total under-states the sum of its own lines by exactly the
discount.** Live data cannot confirm it (`discount_amount = 0.00` on the single
live invoice); the confirming step would be a v2 invoice item with a non-zero
discount.

| Column | Migration | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|---|
| `invoice_id` | FK cascade | `createFromInvoiceableItem`, `addManualItem`, `duplicateInvoice` | everything | — | cascade | no |
| `invoiceable_item_id` | FK **set null** | `createFromInvoiceableItem` only; explicitly omitted by `duplicateInvoice` | the invoiced/release blocks in `updateStatus`, `removeItem`, `deleteInvoice` | **the item is never marked invoiced and never released** | yes | no |
| `type` | `enum(extra_work, continuous_work, material, labor, service, other)` | mapped from the source `InvoiceableItem.type` (`:157-165`) — **`project` has no mapping and silently becomes `other`** | `getTypeLabelAttribute` (dead) | default `other` | no | **effectively DEAD** |
| `title`,`description` | string/text | all creators | frontend detail table | — | no | no |
| `quantity`,`unit_price` | decimal | all creators | `calculateTotals` | defaults 1 / 0 | no | no |
| `unit_id` | `unsignedBigInteger` nullable, **FK deliberately omitted** ("units table may not exist") | copied from the invoiceable item; `addItem` validates `exists:units,id` | `unit()` → `ProductUnit` (i.e. table `product_units`) | no unit | **`addItem` with a `unit_id` always 422s — there is no `units` table** | no |
| `discount_percentage`,`discount_amount` | decimal nullable | `addManualItem`, `updateItem`; `discount_amount` is also overwritten by the saving hook | `calculateTotals`, and the double-subtraction above | 0 | changes the price | no |
| `subtotal`,`tax_amount`,`total` | decimal | saving hook | invoice `calculateTotals` | recomputed | no | no |
| `tax_rate` | `tinyInteger default 21` — a **percentage** | copied from the invoiceable item (whose `tax_rate` is a `decimal(5,2)` percentage) | `calculateTotals` | 21 | no | no |
| `period_start`,`period_end` | date nullable | copied from the invoiceable item; nulled by `duplicateInvoice` | `getPeriodLabelAttribute` — **dead** | — | none | **DEAD** |
| `reference_number` | `string(100)` nullable | copied; nulled by duplicate | nothing | — | none | **DEAD** |
| `sort_order` | `integer default 0` | creators, `reorderItems` | `items()` relation `orderBy('sort_order')` | 0 | no | no |

Dead accessors: `getFormattedSubtotalAttribute`, `getFormattedTotalAttribute`,
`getPeriodLabelAttribute`, `getTypeLabelAttribute` — no `$appends`, no callers.

## 2.6 EVERY controller/service that creates an invoice

I grepped the whole `app/` tree for `Invoice::create`, `new Invoice`,
`ExtraWorkV2Invoice::create`, `InvoiceItem::create`, `items()->create`,
`DB::table('invoices')->insert`, `firstOrCreate`, `updateOrCreate`. **Five
creation paths exist. Nothing else creates an invoice.** There is no observer
(`app/Observers/` has 7 files, none invoice-related) and no job
(`app/Jobs/` has 3, all translation).

| # | Path | Table | Belongs to | Number source | Line item source |
|---|---|---|---|---|---|
| **1** | `InvoiceController::store` — `POST /admin/invoices` | `invoices` (**v1**) | **v1** — the original Extra-Work-v1 flow | **client payload** | `extra_works` (v1) |
| **2** | `InvoiceController::createInvoiceFromItems` (private, via `createFromInvoiceableItems`) — `POST /admin/invoices/from-invoiceable-items` | `invoices` | the newest flow, retro-fitted onto the v1 table | `InvoiceController::generateInvoiceNumber()` | `invoiceable_items` |
| **3** | `InvoiceController::createInstallmentInvoices` (private, same endpoint, when `installments > 1`) | `invoices` | idem | `generateInvoiceNumber()` + `-{i}/{n}` suffix | one **synthetic summary line**, `invoiceable_item_id = null` |
| **4** | `ExtraWorkV2InvoiceService::createFromInvoiceableItems` — `POST /admin/extra-work-v2-invoices` | `extra_work_v2_invoices` (**v2**) | v2 | model boot hook | `invoiceable_items` |
| **5** | `ExtraWorkV2InvoiceService::duplicateInvoice` — `POST /admin/extra-work-v2-invoices/{id}/duplicate` | `extra_work_v2_invoices` | v2 | model boot hook | **copies the lines of another invoice, deliberately dropping `invoiceable_item_id`, `period_*` and `reference_number`** |

Path 3 deserves a callout: it creates N invoices whose **only** line is
`"Termijn {i}/{n} - X items"`, computes `tax_rate` as
`$installmentTax / $installmentAmount` (a **division by zero** if the selected
items total 0.00 — and 12 of the 13 live invoiceable items have `total = 0.00`),
and marks every source item `invoice_draft` exactly once regardless of how many
invoices are produced. Its invoice numbers contain a `/` character.

**CODE — `InvoiceController.php:1308`:**
```php
'tax_rate' => $totalTax > 0 ? ($installmentTax / $installmentAmount) : 0.21,
```
The guard checks `$totalTax`, not `$installmentAmount`. A zero-amount, non-zero-tax
selection is impossible, but a zero `$totalAmount` with `$totalTax > 0` is not
reachable either — so in practice `$totalTax > 0` implies `$installmentAmount > 0`.
Flagged as a latent hazard rather than a live bug.

## 2.7 v1 status machine and what each status permits

**CODE — the guards, all in `InvoiceController`:**
```php
:196  if (!$invoice->isDraft())  -> 403 'Only draft invoices can be updated'
:253  if (!$invoice->isDraft())  -> 403 'Only draft invoices can be deleted'
:341  if ($invoice->status !== 'draft') -> 403 'Only draft invoices can be sent'
:347  if ($invoice->items->isEmpty())   -> 422 'Cannot send invoice without items'
:483  if ($invoice->status === 'draft') -> 422 'Use the send action for draft invoices'   (regeneratePdf)
:527  if ($invoice->status !== 'sent')  -> 422 'Only sent invoices can be reverted to draft'
:563  if (!$invoice->isDraft())  -> 403 'Can only add items to draft invoices'
:648  if (!$invoice->isDraft())  -> 403 'Can only edit items in draft invoices'
:711  if (!$invoice->isDraft())  -> 403 'Can only remove items from draft invoices'
:772  if (!$invoice->isDraft())  -> 403 'Can only delete items from draft invoices'
:867  if ($invoice->status !== 'sent')  -> 403 'Only sent invoices can be marked as paid or cancelled'
```

| Status | Reached from | Permits | Forbids |
|---|---|---|---|
| `draft` | create; `revertToDraft` from `sent` | update header, add/update/delete items, delete invoice, preview PDF, send | regenerate PDF, mark paid/cancelled |
| `sent` | `sendInvoice` (draft only) | download PDF, regenerate PDF, revert to draft, mark paid, mark cancelled | any edit |
| `paid` | `updateStatus` from `sent` | download, regenerate PDF | everything else — **terminal** |
| `cancelled` | `updateStatus` from `sent` | download, regenerate PDF | everything else — **terminal** |

**What `paid` DOES to the underlying works:** nothing at all. Follow
`updateStatus:869-885` — it writes `status` and `paid_at` inside a transaction
and commits. There is no other statement in the method.

**What `cancelled` DOES to the underlying works:** nothing at all. Same method,
same two writes. **CODE — `InvoiceController.php:869-885`:**
```php
$updateData = ['status' => $request->status];
if ($request->status === 'paid')          { $updateData['paid_at'] = now(); }
elseif ($request->status === 'cancelled') { $updateData['cancelled_at'] = now(); }
$invoice->update($updateData);
```
The extra works remain at `status_id = 9`. The invoiceable items remain at
`invoice_draft`. The PDF on disk is untouched. Nothing anywhere reads
`cancelled` to exclude the invoice from a total, because **nothing reads the
`invoices` table for reporting at all** (see §2.9).

### The only real "route back to the billable pool" in v1

**CODE — `InvoiceController::destroy:265-281` (draft only):**
```php
$extraWorkIds = $invoice->items->pluck('extra_work_id')->filter();
if ($extraWorkIds->isNotEmpty()) {
    ExtraWork::whereIn('id', $extraWorkIds)->update([
        'status_id' => 8, 'invoice_id' => null, 'invoice_date' => null, ]);
}
$invoiceableItemIds = $invoice->items->pluck('invoiceable_item_id')->filter();
if ($invoiceableItemIds->isNotEmpty()) {
    InvoiceableItem::whereIn('id', $invoiceableItemIds)->update(['status' => InvoiceableItem::STATUS_READY]);
}
$invoice->items()->forceDelete();
$invoice->forceDelete();
```
`deleteItem` (`:767-838`) and `removeExtraWork` (`:705-765`) do the same for one
line, and both **auto-delete the whole invoice when the last line goes**.
All three are draft-only. That is the entire correction surface.

## 2.8 Invoice numbering — the full picture

**CODE — the generator that actually produced the live numbers,
`frontend/src/pages/finalosius/extra-works/modals/ExtraWorkBulkAllInvoiceModal.jsx`:**
```js
:103   const today = new Date();
:104   const prefix = `INV-${format(today, 'yyyyMM')}`;
:75    const generateInvoiceNumber = (prefix, index) => {
:76      const paddedIndex = String(index).padStart(4, '0');
:77      return `${prefix}-${paddedIndex}`;
:78    };
:239   const invoiceNumber = generateInvoiceNumber(invoicePrefix, i + 1);
:251   const response = await apiClient.post('/admin/invoices', payload);
```
`i` is the loop index over the selected groups **within one modal session**. The
prefix is editable by the user in a text field (`:419-427`). Nothing consults
the server for the last used number.

**DATA:** the three live invoices are `INV-202605-0001`, `INV-202605-0002`,
`INV-202605-0003`, all `invoice_date 2026-05-05`, created within one minute
(`created_at 2026-05-05T01:21:26` for #88/#89). That is one modal session
producing 1, 2, 3 — an exact match. **A second session in May 2026 would restart
at 0001 and 422 on the UNIQUE index.**

A second, different frontend generator exists —
`ExtraWorkBulkInvoiceModal.jsx:118-122`, `INV-${yyyymmdd}-${random 1000..9999}` —
a **random** number, birthday-collision prone.

**Can a human overwrite it?** Yes, two ways.
- `POST /admin/invoices` takes `invoice_number` as a required payload key
  (`InvoiceController:88`), with only `unique:invoices,invoice_number` as the
  rule. Any string is acceptable.
- `PUT /admin/invoices/{id}` accepts `invoice_number` (`:198`,
  `'invoice_number' => 'sometimes|string|max:50'` — note it **drops the unique
  rule**, relying on the DB index) while the invoice is a draft.

The v2 number cannot be overwritten: `invoice_number` is in `$fillable` but
neither `store` nor `update` passes it, and the boot hook fills it.

**Can they collide under concurrency?** Yes, all three generators.
- Frontend v1: collides deterministically, not just under concurrency.
- `InvoiceController::generateInvoiceNumber()`: `orderByDesc('invoice_number')`
  (string ordering) then `max()+1`, no lock, no retry.
- `ExtraWorkV2Invoice::generateInvoiceNumber()`: `max()+1` on a cast substring,
  no lock, no retry, and the substring breaks past 9999.

There is also a **gap** problem in v1: `createInvoiceFromItems` assigns the
number at **creation**, then `destroy`/`deleteItem`/`removeExtraWork` **hard
delete** the invoice. The number is burned and, because the generator takes
`max()+1` over surviving rows, it will be **re-issued** to the next invoice.
v2 avoids this with `withTrashed()`.

Finally, the two generators write into the **same unique column with different
formats** (`INV-2026-0001` from the backend, `INV-202605-0001` from the browser),
so `orderByDesc('invoice_number')` on a mixed table returns
`INV-202605-0003` as "highest", `str_replace('INV-2026-','')` yields
`05-0003`, `(int)` yields `5`, and the next generated number is `INV-2026-0006`.
**CODE + DATA** — the live table is exactly in this mixed state today (the
`INV-2026-` prefix is a strict prefix of `INV-202605-`).

## 2.9 What reads invoice money downstream — nothing

- `ReportsController` (10 revenue/EW report methods) filters on
  `extra_works.status_id = 9` with the comment `// Faturalanan`, and joins the
  `invoices` table only for an optional `invoice_ids` filter
  (`ReportsController:732`) and for sorting extra works by invoice date
  (`ExtraWorksController:301-306`). It never sums `invoices.total_amount`.
- `DashboardController`: zero references to `Invoice`.
- No PDF, export or notification other than `pdf.invoice-vertical` reads the
  invoice tables.

So an invoice's stored amounts and its `paid` / `cancelled` status feed **no
report, no dashboard and no aggregate anywhere in the application.** Revenue is
measured on the extra-work side.

## 2.10 Route table and authorisation

`routes/api.php`, all under the admin prefix. Middleware `ucb.permission:<area>,<verb>`.

| Method | Path | Controller method | Middleware |
|---|---|---|---|
| GET | `/admin/invoices` | `index` | `invoices,list` |
| POST | `/admin/invoices` | `store` | `invoices,create` |
| GET | `/admin/invoices/pending-extra-works` | `pendingExtraWorks` | `invoices,view` |
| GET | `/admin/invoices/{id}` | `show` | `invoices,view` |
| PUT | `/admin/invoices/{id}` | `update` | `invoices,update` |
| DELETE | `/admin/invoices/{id}` | `destroy` | `invoices,delete` |
| POST | `/admin/invoices/{id}/send` | `sendInvoice` | `invoices,update` |
| GET | `/admin/invoices/{id}/preview` | `previewInvoice` | `invoices,view` |
| GET | `/admin/invoices/{id}/download` | `downloadInvoice` | `invoices,view` |
| PUT | `/admin/invoices/{id}/status` | `updateStatus` | `invoices,update` |
| POST | `/admin/invoices/{id}/regenerate-pdf` | `regeneratePdf` | `invoices,update` |
| POST | `/admin/invoices/{id}/revert-to-draft` | `revertToDraft` | `invoices,update` |
| POST | `/admin/invoices/bulk-download` | `bulkDownload` | `invoices,view` |
| POST | `/admin/invoices/from-invoiceable-items` | `createFromInvoiceableItems` | `invoices,create` |
| GET | `/admin/invoices/customers/{customerId}/invoiceable-items` | `getInvoiceableItemsForCustomer` | `invoices,view` |
| POST/PUT/DELETE | `/admin/invoices/{id}/items…` | `addItem`/`updateItem`/`deleteItem`/`removeExtraWork` | `invoices,update` |
| GET/POST/PUT/DELETE | `/admin/invoiceable-items…` | `InvoiceableItemController` | `invoices,{view,create,update,delete}` |
| PUT | `/admin/invoiceable-items/{id}/status` | `updateStatus` | `invoices,update` |
| GET/POST/PUT/DELETE | `/admin/extra-work-v2-invoices…` | `ExtraWorkV2InvoiceController` | `invoices,{view,create,update,delete}` |
| GET | `/admin/customers/{customerId}/invoiceable-items` | `getInvoiceableItems` | `invoices,view` |
| GET | `/admin/customers/{customerId}/extra-work-v2-invoices` | `getCustomerInvoices` | `invoices,view` |

Two observations:
- `PUT /admin/invoiceable-items/{id}/status`, which can mark an item
  `invoiced` with no invoice or release one off a live draft invoice, needs only
  `invoices,update` — the same permission as editing a line.
- There is **no per-customer scoping** on `InvoiceController::index`; the
  `ucb.permission` middleware is the only gate, and `customer_id` is an optional
  query filter, not an enforced scope. (Tenant scoping is outside A2's brief but
  is flagged for whoever owns authorisation.)

## 2.11 Migration hazards found while reading the schema

- **`summary_subtitle` is added twice.** `2026_02_18_085212_add_summary_subtitle_to_invoices_table`
  does `$table->string('summary_subtitle')->nullable()->after('summary_description');`
  while `summary_description` does not yet exist (it arrives in
  `2026_02_18_100000`), and `2026_02_18_100000` adds `summary_subtitle` a second
  time. Neither uses a `hasColumn` guard. By filename order 085212 runs first, so
  on a clean database one of the two must fail. **DATA** confirms the column
  exists on the live schema (`summary_subtitle: null` on every invoice), so the
  live database is in a state a fresh `migrate` cannot reproduce.
- `2026_02_18_085426_add_discount_fields_to_invoices_table` uses
  `->after('summary_tax_rate')`, another column that does not exist until
  `2026_02_18_100000`.
- `2026_02_19_100000_add_project_type_to_invoiceable_items`'s `down()` is
  identical to its `up()` — rolling back does not remove `project` from the enum.
- The live `invoiceable_items` table has `project_id` and `task_id` columns that
  **no migration in the repository creates**.

---

# 3. CONNECTION MAP

## 3.1 The two pipelines

```
                          ==== V1 EXTRA-WORK PIPELINE (the live one) ====

  extra_works (status_id 8 = Completed)
        |
        |  browser: ExtraWorkBulkAllInvoiceModal groups + invents INV-yyyyMM-000N
        v
  POST /admin/invoices  (InvoiceController::store)
        |
        +--> invoices                (status=draft, number from the CLIENT)
        +--> invoice_items           (one per extra work; amount = total_products_cost, LABOUR EXCLUDED)
        +--> extra_works.status_id = 9      <-- the ONLY "this is billed" marker
             (extra_works.invoice_id / .invoice_date are NOT set here — DATA-confirmed null)
        |
        v
  POST /admin/invoices/{id}/send  -> mPDF -> storage/invoices/YYYY/MM/…pdf
        |                            status=sent, sent_at, pdf_path, pdf_generated_at
        v
  PUT /admin/invoices/{id}/status  -> paid (paid_at)      TERMINAL, touches nothing else
                                   -> cancelled (cancelled_at)  TERMINAL, touches nothing else
                                      ^^^ extra works stay at status_id 9 FOREVER


                          ==== INVOICEABLE-ITEMS POOL ====

  ExtraWorkV2 (price_type=fixed) --BillingService--> invoiceable_items (type=extra_work)
  PrjProject distribution save   --PrjProjectsCtl--> invoiceable_items (type=project)   [13 live rows]
  "copy income to expenses" UI   --ItemCtl::store--> invoiceable_items (any type)
        |
        |  status: draft -> ready (manual) -> invoice_draft (reserved on an invoice)
        |
        +---- PATH A: POST /admin/invoices/from-invoiceable-items
        |         -> invoices (v1 table), number from InvoiceController::generateInvoiceNumber
        |         -> invoice_items.invoiceable_item_id
        |         -> item.status = invoice_draft ... AND NEVER ADVANCES FURTHER
        |            (item.invoice_id and item.invoiced_at are never written)
        |
        +---- PATH B: POST /admin/extra-work-v2-invoices
                  -> extra_work_v2_invoices (v2 table), number EWV2-YYYY-NNNN
                  -> extra_work_v2_invoice_items.invoiceable_item_id
                  -> item.status = invoice_draft
                     on SENT/PAID  -> item.status = invoiced + invoiced_at  (ONLY place in the app)
                     on CANCELLED  -> item.status = ready   (the only real unwind in the system)
```

## 3.2 What action changes what

| Action | Endpoint | Writes | Also changes |
|---|---|---|---|
| Bulk-invoice extra works | `POST /admin/invoices` | `invoices`, `invoice_items` | `extra_works.status_id → 9` |
| Add one extra work to a draft | `POST /admin/invoices/{id}/items` | `invoice_items` | `extra_works.status_id → 9`, `.invoice_id`, `.invoice_date`; header totals |
| Remove an extra work from a draft | `DELETE …/items/by-extra-work/{ewId}` | deletes the line | `extra_works.status_id → 8`, `.invoice_id → null`; **deletes the invoice if it was the last line** |
| Delete a line | `DELETE …/items/{itemId}` | deletes the line | reverts the extra work AND releases the invoiceable item to `ready`; deletes the invoice if last |
| Delete a draft invoice | `DELETE /admin/invoices/{id}` | hard-deletes invoice + lines | reverts all extra works to 8, releases all invoiceable items to `ready` |
| Edit the header | `PUT /admin/invoices/{id}` | summary_*, discount_*, period_*, notes, **invoice_number**, invoice_date | **changes the printed PDF totals** |
| Send | `POST …/send` | status, sent_at, pdf_path, pdf_generated_at | writes the PDF file |
| Revert to draft | `POST …/revert-to-draft` | status=draft, sent_at=null | **leaves `pdf_path` pointing at the issued PDF** |
| Mark paid | `PUT …/status {paid}` | status, paid_at | nothing |
| Mark cancelled | `PUT …/status {cancelled}` | status, cancelled_at | **nothing** |
| Create from invoiceable items | `POST /admin/invoices/from-invoiceable-items` | invoices + lines | items → `invoice_draft` (accepts items already at `invoice_draft`) |
| Change an item's status by hand | `PUT /admin/invoiceable-items/{id}/status` | `status` | can pull an item off a live draft, or lock it as `invoiced` with no invoice |
| Save a project cost distribution | `PUT /admin/prj-projects/{id}/…` (`generateSubProjects`) | sub-projects + products | **forceDeletes** the project's auto-generated invoiceable items regardless of status |
| Regenerate EWv2 billing | `POST /admin/extra-works-v2/{id}/regenerate-billing` | invoiceable items | soft-deletes draft/ready items, recreates them |
| Cancel a v2 invoice | `PUT /admin/extra-work-v2-invoices/{id}/status {cancelled}` | status, cancelled_at | **releases linked items to `ready`** |

## 3.3 Field-level pointer graph

```
customers.id ─────┬─> invoices.customer_id ──> PDF "Debiteurnummer"
                  ├─> invoiceable_items.customer_id ──> per_customer grouping
                  └─> extra_work_v2_invoices.customer_id

buildings.id ─────┬─> invoices.building_id ──> PDF second address line
                  └─> invoiceable_items.building_id

invoices.id ──────┬─> PDF "Bonnummer"
                  ├─> invoice_items.invoice_id (cascade)
                  └─> (invoiceable_items.invoice_id — DECLARED, NEVER WRITTEN)

extra_works.id ───> invoice_items.extra_work_id  (UNIQUE — the one-work-one-invoice guarantee)
extra_works.status_id 8<->9 ── the real billed/unbilled flag

invoiceable_items.id ─┬─> invoice_items.invoiceable_item_id      (nullOnDelete)
                      └─> extra_work_v2_invoice_items.invoiceable_item_id (nullOnDelete)
                            └─> drives invoiced/release; NULL on all 3 live v2 lines

invoiceable_items.entity_id ─┬─ type=extra_work  -> extra_works_v2.id
                             └─ type=project     -> prj_projects.id (the SUB-project)
invoiceable_items.notes LIKE 'auto_generated%' ── the deletion key for the project purge
invoiceable_items.scheduled_date ── decides the "current" vs "overdue" bucket
```

## 3.4 Where their "Product" meets money

1. `ExtraWork::total_products_cost` = `Σ product.subtotal` → becomes
   `invoice_items.amount` on the v1 path. **Labour is excluded by design**
   (`// Only products, not labor`).
2. `invoice_items.quantity` / `unit_name` are taken from the **first product
   only**, then multiplied against the already-summed product total.
3. `ExtraWorkV2Product` → `BillingService::regenerateFromIncome` → the fixed
   price is split into `invoiceable_items` ("Uitgaven" generated from
   "Inkomsten").
4. `PrjProject` products → `invoiceable_items` at 21% flat.
5. `product_units.label_nl` → `invoice_items.unit_name` → the printed "Eenheid".
   Note `ExtraWorkV2InvoiceItem::addItem` validates `unit_id` against a
   non-existent `units` table while the relation points at `product_units`.

---

# 4. COULD NOT DETERMINE

1. **Whether `invoices` ever held cancelled or paid rows.** The live table has
   3 rows: 2 sent, 1 draft. Zero paid, zero cancelled, zero
   from-invoiceable-items, zero with a discount, zero with `period_start`, zero
   with a `summary_*` override. So every claim about what those code paths
   *produce* is CODE-only. **To close:** a record with `status='cancelled'` and
   one with a non-null `discount_type` — or a DBA-level `SELECT ... FROM invoices
   WHERE deleted_at IS NOT NULL` (there should be none, since v1 always
   force-deletes).

2. **Whether v2 invoices 1–3 were soft-deleted or never existed.** Only
   `EWV2-2026-0004` is visible and the generator uses `withTrashed()`, so
   1–3 most likely exist as soft-deleted rows. **To close:** a query with
   `withTrashed()`, or an endpoint that exposes trashed v2 invoices (there is
   none).

3. **Why `extra_work_v2_invoice_items.invoiceable_item_id` is NULL on all three
   live lines.** The FK is `set null`, and `InvoiceableItem` uses SoftDeletes, so
   the application's own delete paths (`->delete()`) should *not* have triggered
   it. Either something hard-deleted those rows outside the code paths I read
   (a manual DB operation, or a `forceDelete` I did not find), or the rows were
   created differently. **To close:** `SELECT id, deleted_at FROM invoiceable_items
   WHERE type='extra_work'` including trashed, and the DB's
   `information_schema.referential_constraints` for that FK.

4. **The `project_id` and `task_id` columns on `invoiceable_items`.** They are
   returned by the API on every row but appear in **no migration** in
   `database/migrations/` and in no `$fillable`. **To close:** `SHOW CREATE TABLE
   invoiceable_items` plus a search of any out-of-repo migration or manual DDL.

5. **Which of the duplicate `summary_subtitle` migrations actually ran.** Both
   would fail on a clean database in filename order, yet the column exists live.
   **To close:** `SELECT migration, batch FROM migrations WHERE migration LIKE
   '2026_02_18%'`.

6. **The exact labels of `extra_works.status_id` 8 and 9.** I have only the
   inline comments (`// Update extra work status to 9 (Invoiced)` at
   `InvoiceController:151`, `'status_id' => 8, // Completed` at `:786`, and
   `// Faturalanan` throughout `ReportsController`). The lookup endpoints I
   probed (`/admin/lookup-tables?category=task_status`,
   `/admin/extra-works/statuses`) did not return a usable status list.
   **To close:** the correct lookup route for task statuses, or
   `SELECT id,label FROM task_statuses`.

7. **Whether the v1 double-count (`amount × quantity` where `amount` is already
   quantity-inclusive) ever produced a wrong invoice.** Every live
   `invoice_items.quantity` is `1.00`. **To close:** an invoice whose first
   extra-work product has quantity ≠ 1, or
   `SELECT COUNT(*) FROM invoice_items WHERE quantity <> 1`.

8. **Whether the v2 header double-subtracts the discount in practice.** The one
   live v2 invoice has `discount_amount = 0.00`. The code reading is
   unambiguous, but I have no DATA. **To close:** a v2 invoice item with a
   non-zero `discount_percentage`.

9. **`invoices.pdf_path` after `revert-to-draft`.** I read that `revertToDraft`
   nulls `sent_at` but not `pdf_path`, so `downloadInvoice` should keep serving
   the already-issued PDF from a draft invoice. No live invoice is in that state.
   **To close:** an invoice that has been sent and reverted, then
   `GET /admin/invoices/{id}/download`.

10. **Whether the invoicing area enforces any per-customer/tenant scoping beyond
    the `ucb.permission:invoices,*` middleware.** I read the middleware alias
    registration in `bootstrap/app.php` but did not read
    `App\Http\Middleware\UcbPermissionMiddleware` itself — that belongs to the
    authorisation agent's area. `InvoiceController::index` applies no scope of
    its own. **To close:** whoever owns RBAC reads
    `app/Http/Middleware/UcbPermissionMiddleware.php` and reports whether it
    narrows the query or only allows/denies the route.

11. **Whether any queue worker or cron exists on the deployed host.** The
    application declares no scheduler (`routes/console.php` has only `inspire`;
    there is no `app/Console/Kernel.php`), so `checkOverdueInvoices()` cannot be
    driven from inside Laravel. A host-level cron calling something else is
    conceivable but nothing in `deploy.sh`, `crm-laravel.service` or
    `crm-socket.service` was read. **To close:** read those three files and the
    host crontab.
